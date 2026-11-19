"""
fuentes_estaticas.py — S14: fuentes estáticas por nicho (canales fijos), revisadas a mano con "Ejecutar".

    python -m investigacion.fuentes_estaticas ejecutar zapatillas_peru [--dias 7 | --ultimos 10]
    python -m investigacion.fuentes_estaticas listar zapatillas_peru            # candidatos pendientes
    python -m investigacion.fuentes_estaticas procesar zapatillas_peru <id> [...] | --todos
    python -m investigacion.fuentes_estaticas descubrir zapatillas_peru         # canales nuevos para agregar

Configuración: `investigacion/<nicho>/fuentes.yaml` (CLIP-60). Estado y registro (CLIP-61/62):
  - `fuentes_estado.json`: última revisión por canal;
  - `fuentes_historial.jsonl`: cada video detectado con su estado (nuevo, descartado y por qué, procesado, error).
Canales de YouTube vía su feed RSS público (sin cuenta, sin API, sin costo). Kick queda previsto en el formato pero no
se revisa todavía; el módulo "Live" (vivo) va aparte. Sin cron: decisión del operador (2026-11-18).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from core import exclusion
from core.fuente import nombre_sobre
from investigacion import comun

LEGACY = Path(__file__).resolve().parent.parent
_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
       "media": "http://search.yahoo.com/mrss/"}


# ── Configuración y estado ──────────────────────────────────

def cargar_config(nicho: str) -> dict:
    ruta = comun.carpeta_nicho(nicho) / "fuentes.yaml"
    return (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}) if ruta.exists() else {}


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defecto


def leer_historial(nicho: str) -> list[dict]:
    ruta = comun.carpeta_nicho(nicho) / "fuentes_historial.jsonl"
    if not ruta.exists():
        return []
    return [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]


def _guardar_historial(nicho: str, filas: list[dict]) -> None:
    ruta = comun.carpeta_nicho(nicho) / "fuentes_historial.jsonl"
    ruta.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas), encoding="utf-8")


def estado_actual(historial: list[dict]) -> dict[str, dict]:
    """Último registro por video (el historial se agrega, no se reescribe por video). Puro."""
    actual: dict[str, dict] = {}
    for f in historial:
        actual[f["id"]] = {**actual.get(f["id"], {}), **f}
    return actual


# ── Lectura de canales ──────────────────────────────────────

def channel_id(url: str) -> str | None:
    m = re.search(r"/channel/(UC[\w-]{20,})", url or "")
    return m.group(1) if m else None


def parsear_feed(xml: str) -> list[dict]:
    """Feed RSS de un canal de YouTube → [{id, titulo, descripcion, publicado (datetime UTC)}]. Puro."""
    raiz = ET.fromstring(xml)
    videos = []
    for e in raiz.findall("a:entry", _NS):
        vid = e.findtext("yt:videoId", default="", namespaces=_NS)
        publicado = e.findtext("a:published", default="", namespaces=_NS)
        videos.append({
            "id": vid,
            "titulo": e.findtext("a:title", default="", namespaces=_NS),
            "descripcion": e.findtext("media:group/media:description", default="", namespaces=_NS) or "",
            "publicado": datetime.fromisoformat(publicado.replace("Z", "+00:00")) if publicado else None,
        })
    return videos


def leer_canal(canal: dict) -> list[dict]:
    """Últimos videos de un canal (el feed de YouTube trae los 15 más recientes)."""
    if canal.get("plataforma", "youtube") != "youtube":
        return []                                    # kick: previsto, todavía no
    cid = channel_id(canal.get("url", ""))
    if not cid:
        raise ValueError(f"URL sin /channel/UC…: {canal.get('url')} (usa la URL con el id del canal)")
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "clipeo"}), timeout=30) as r:
        return parsear_feed(r.read().decode("utf-8"))


# ── Filtro y deduplicación ──────────────────────────────────

def palabras_relevancia(config: dict) -> list[str]:
    """Palabras clave del nicho + nombre y apodos de la entidad, normalizadas."""
    palabras = list(config.get("palabras_clave") or [])
    sobre = config.get("sobre")
    if sobre:
        palabras.append(nombre_sobre(sobre))
        ruta = LEGACY / "contexto" / "entidades" / f"{str(sobre).lower()}.yaml"
        try:
            ent = (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("entidad") or {}
            palabras += [ent.get("nombre_real") or ""] + list(ent.get("apodos") or [])
        except OSError:
            pass
    return sorted({exclusion.normalizar(p) for p in palabras if p and len(exclusion.normalizar(p)) > 3})


def decidir(video: dict, canal: dict, palabras: list[str]) -> tuple[str, str]:
    """(estado, motivo) para un video nuevo. Puro."""
    if exclusion.motivo(canal=canal.get("nombre")):
        return "descartado", "canal en la lista de exclusión (R-01)"
    if canal.get("rol") == "propio":
        return "nuevo", "canal propio del cliente"
    texto = exclusion.normalizar(f"{video.get('titulo', '')} {video.get('descripcion', '')}")
    coincide = next((p for p in palabras if p in texto), None)
    return ("nuevo", f"menciona «{coincide}»") if coincide else ("descartado", "no menciona al cliente")


def ids_ya_procesados(stream_data: Path) -> set[str]:
    from investigacion.fuentes_medios import ids_procesados
    return ids_procesados(stream_data)


def _stream_data() -> Path:
    from core.config_local import ruta
    return ruta("CLIPEO_STREAM_DATA", LEGACY / "stream_data")


# ── Ejecutar (CLIP-61) ──────────────────────────────────────

def ejecutar(nicho: str, dias: int | None = None, ultimos: int | None = None,
             lector=leer_canal, ahora: datetime | None = None) -> dict:
    """Revisa los canales activos del nicho y registra lo nuevo. Devuelve un resumen por canal."""
    config = cargar_config(nicho)
    if not config.get("activo", True):
        return {"activo": False, "canales": []}
    ahora = ahora or datetime.now(timezone.utc)
    carpeta = comun.carpeta_nicho(nicho)
    estado = _leer_json(carpeta / "fuentes_estado.json", {})
    historial = leer_historial(nicho)
    vistos = set(estado_actual(historial)) | ids_ya_procesados(_stream_data())
    palabras = palabras_relevancia(config)
    resumen = []
    for canal in config.get("canales") or []:
        if not canal.get("activo", True):
            continue
        clave = canal.get("url")
        try:
            videos = lector(canal)
        except Exception as e:   # noqa: BLE001 — un canal caído no frena a los demás
            resumen.append({"canal": canal.get("nombre"), "error": str(e)[:200], "nuevos": 0, "descartados": 0})
            continue
        if ultimos:
            videos = sorted(videos, key=lambda v: v["publicado"] or ahora, reverse=True)[:ultimos]
        else:
            desde = (ahora - timedelta(days=dias)) if dias else (
                datetime.fromisoformat(estado[clave]) if clave in estado
                else ahora - timedelta(days=config.get("ventana_inicial_dias", 7)))
            videos = [v for v in videos if v["publicado"] and v["publicado"] >= desde]
        nuevos = descartados = 0
        for v in videos:
            if not v["id"] or v["id"] in vistos:
                continue
            vistos.add(v["id"])
            est, motivo = decidir(v, canal, palabras)
            historial.append({"id": v["id"], "url": f"https://www.youtube.com/watch?v={v['id']}",
                              "titulo": v["titulo"], "canal": canal.get("nombre"), "rol": canal.get("rol"),
                              "publicado": v["publicado"].isoformat() if v["publicado"] else None,
                              "detectado": ahora.isoformat(timespec="seconds"), "estado": est, "motivo": motivo})
            nuevos += est == "nuevo"
            descartados += est == "descartado"
        estado[clave] = ahora.isoformat(timespec="seconds")
        resumen.append({"canal": canal.get("nombre"), "nuevos": nuevos, "descartados": descartados})
    _guardar_historial(nicho, historial)
    (carpeta / "fuentes_estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"activo": True, "canales": resumen}


def candidatos(nicho: str) -> list[dict]:
    return [f for f in estado_actual(leer_historial(nicho)).values() if f.get("estado") == "nuevo"]


# ── Procesar ────────────────────────────────────────────────

def procesar(nicho: str, ids: list[str]) -> list[dict]:
    """Corre el pipeline (con Colab) para cada candidato elegido y registra el resultado."""
    config = cargar_config(nicho)
    actual = estado_actual(leer_historial(nicho))
    historial = leer_historial(nicho)
    resultados = []
    for vid in ids:
        f = actual.get(vid)
        if not f or f.get("estado") not in ("nuevo", "error"):
            continue
        sesion = f"{datetime.now():%Y%m%d}_{'medios' if f.get('rol') == 'medios' else 'propio'}_{vid}"
        cmd = [sys.executable, str(LEGACY / "pipeline.py"), "--video", f["url"], "--config", nicho, "--colab",
               "--session-id", sesion]
        if f.get("rol") == "medios":
            cmd += ["--medios", "--sobre", str(config.get("sobre") or "")]
        print(f"[FUENTES] Procesando «{f['titulo'][:60]}» → {sesion}")
        r = subprocess.run(cmd, cwd=str(_stream_data().parent))
        estado = "procesado" if r.returncode == 0 else "error"
        historial.append({"id": vid, "estado": estado, "sesion": sesion,
                          "procesado": datetime.now().isoformat(timespec="seconds")})
        resultados.append({"id": vid, "estado": estado, "sesion": sesion})
        _guardar_historial(nicho, historial)
    return resultados


# ── Descubrir canales (CLIP-64) ─────────────────────────────

def descubrir(nicho: str) -> list[dict]:
    """Canales que aparecieron en la búsqueda por palabras (S8) y no están en fuentes.yaml, por frecuencia."""
    config = cargar_config(nicho)
    ya = {exclusion.normalizar(c.get("nombre")) for c in config.get("canales") or []}
    from investigacion.fuentes_medios import leer_lista
    conteo: dict[str, int] = {}
    for f in leer_lista(nicho):
        canal = f.get("canal") or ""
        if canal and exclusion.normalizar(canal) not in ya:
            conteo[canal] = conteo.get(canal, 0) + 1
    return [{"canal": c, "apariciones": n} for c, n in sorted(conteo.items(), key=lambda x: -x[1])]


def main() -> None:
    ap = argparse.ArgumentParser(description="S14: fuentes estáticas por nicho (manual)")
    sub = ap.add_subparsers(dest="accion", required=True)
    e = sub.add_parser("ejecutar"); e.add_argument("nicho")
    g = e.add_mutually_exclusive_group(); g.add_argument("--dias", type=int); g.add_argument("--ultimos", type=int)
    l = sub.add_parser("listar"); l.add_argument("nicho")
    p = sub.add_parser("procesar"); p.add_argument("nicho"); p.add_argument("ids", nargs="*")
    p.add_argument("--todos", action="store_true")
    d = sub.add_parser("descubrir"); d.add_argument("nicho")
    args = ap.parse_args()

    if args.accion == "ejecutar":
        r = ejecutar(args.nicho, dias=args.dias, ultimos=args.ultimos)
        if not r["activo"]:
            print("[FUENTES] El nicho está inactivo en fuentes.yaml")
            return
        for c in r["canales"]:
            print(f"  {c['canal']:22s} " + (f"⚠ {c['error']}" if c.get("error") else
                                            f"{c['nuevos']} nuevo(s) · {c['descartados']} descartado(s)"))
        args.accion = "listar"
    if args.accion == "listar":
        cands = candidatos(args.nicho)
        print(f"\n[FUENTES] {len(cands)} candidato(s) para procesar:")
        for f in sorted(cands, key=lambda x: x.get("publicado") or "", reverse=True):
            print(f"  {f['id']}  [{f['rol']:6s}] {f['canal']}: {f['titulo'][:70]}  ({(f.get('publicado') or '')[:10]})")
    elif args.accion == "procesar":
        ids = [f["id"] for f in candidatos(args.nicho)] if args.todos else args.ids
        for r in procesar(args.nicho, ids):
            print(f"  {r['id']} → {r['estado']} ({r['sesion']})")
    elif args.accion == "descubrir":
        for c in descubrir(args.nicho):
            print(f"  {c['canal']} ({c['apariciones']} aparición(es) en búsquedas)")


if __name__ == "__main__":
    main()
