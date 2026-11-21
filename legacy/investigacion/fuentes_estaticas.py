"""
fuentes_estaticas.py — S14: fuentes estáticas por nicho (canales fijos), revisadas a mano con "Ejecutar".

    python -m investigacion.fuentes_estaticas ejecutar zapatillas_peru [--dias 1 | --ultimos 10]   # defecto: 1 día
    python -m investigacion.fuentes_estaticas listar zapatillas_peru            # candidatos de la última búsqueda
    python -m investigacion.fuentes_estaticas procesar zapatillas_peru <id> [...] | --todos
    python -m investigacion.fuentes_estaticas descubrir zapatillas_peru         # canales nuevos para agregar

Configuración: `investigacion/<nicho>/fuentes.yaml` (CLIP-60). Estado y registro (CLIP-61/62):
  - `fuentes_estado.json`: última revisión por canal;
  - `fuentes_historial.jsonl`: cada video detectado con su estado (nuevo, descartado y por qué, procesado, error);
  - `fuentes_busqueda.json` (CLIP-71): rango e ids de la última búsqueda. Los candidatos son el resultado de esa
    búsqueda (más los links pegados a mano); lo pendiente de búsquedas anteriores se muestra aparte.
Cada canal se lee con su tipo de fuente (`tipos_fuente.py`, CLIP-66): YouTube vía su feed RSS público (sin cuenta,
sin API, sin costo); "lista manual" (CLIP-67) no se revisa, se le pegan links. El módulo "Live" (vivo) va aparte. Sin cron: decisión del operador (2026-11-18).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from core import exclusion
from core.fuente import nombre_sobre
from investigacion import comun
from investigacion import tipos_fuente as tf

LEGACY = Path(__file__).resolve().parent.parent


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


# ── Lectura de canales (vía el registro de tipos de fuente, CLIP-66) ──

def channel_id(url: str) -> str | None:
    return tf.channel_id(url)


def parsear_feed(xml: str) -> list[dict]:
    """Feed RSS de un canal de YouTube → videos. Puro (se conserva por compatibilidad)."""
    return tf.parsear_feed(xml)[1]


def se_revisa(canal: dict) -> bool:
    """El canal entra en "Buscar ahora": activo y de un tipo implementado y automático."""
    try:
        tipo = tf.obtener(canal.get("plataforma"))
    except tf.FuenteError:
        return False
    return canal.get("activo", True) and tipo.implementado and tipo.automatico


def leer_canal(canal: dict) -> list[dict]:
    """Videos recientes del canal, pidiéndoselos a su tipo de fuente."""
    return tf.obtener(canal.get("plataforma")).listar(canal)


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


# ── Ejecutar (CLIP-61; CLIP-71: la lista = resultado de la búsqueda actual) ──

DIAS_POR_DEFECTO = 1
# Lo que ya pasó por el pipeline (o lo descartó el operador) nunca vuelve como candidato; lo demás ("nuevo" o
# descartado por el filtro de TV en una búsqueda anterior) se vuelve a evaluar si cae en el rango (CLIP-71).
ESTADOS_CERRADOS = ("procesado", "procesando", "error")


def _cerrado(f: dict) -> bool:
    return f.get("estado") in ESTADOS_CERRADOS or (f.get("estado") == "descartado" and f.get("por") == "operador")


def es_manual(f: dict) -> bool:
    """Link pegado a mano (CLIP-67): no depende de un canal ni de un rango."""
    return f.get("motivo") == "agregado a mano"


def _ruta_busqueda(nicho: str) -> Path:
    return comun.carpeta_nicho(nicho) / "fuentes_busqueda.json"


def ultima_busqueda(nicho: str) -> dict:
    """{fecha, dias | ultimos, ids}: los candidatos que trajo la última búsqueda ("Buscar ahora")."""
    return _leer_json(_ruta_busqueda(nicho), {})


def ejecutar(nicho: str, dias: int | None = None, ultimos: int | None = None,
             lector=leer_canal, ahora: datetime | None = None) -> dict:
    """Revisa los canales activos del nicho en el rango elegido (por defecto, el último día) y deja como candidatos
    lo publicado en ese rango que no esté procesado. Devuelve un resumen por canal."""
    config = cargar_config(nicho)
    if not config.get("activo", True):
        return {"activo": False, "canales": []}
    if not ultimos:
        dias = dias or DIAS_POR_DEFECTO
    ahora = ahora or datetime.now(timezone.utc)
    carpeta = comun.carpeta_nicho(nicho)
    estado = _leer_json(carpeta / "fuentes_estado.json", {})
    historial = leer_historial(nicho)
    actual = estado_actual(historial)
    cerrados = {i for i, f in actual.items() if _cerrado(f)} | ids_ya_procesados(_stream_data())
    palabras = palabras_relevancia(config)
    encontrados: list[str] = []
    resumen = []
    for canal in config.get("canales") or []:
        if not se_revisa(canal):
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
            desde = ahora - timedelta(days=dias)
            videos = [v for v in videos if v["publicado"] and v["publicado"] >= desde]
        nuevos = descartados = 0
        for v in videos:
            if not v["id"] or v["id"] in cerrados or v["id"] in encontrados:
                continue
            est, motivo = decidir(v, canal, palabras)
            previo = actual.get(v["id"])
            if not previo or (previo.get("estado"), previo.get("motivo")) != (est, motivo):
                fila = {"id": v["id"], "url": v.get("url") or f"https://www.youtube.com/watch?v={v['id']}",
                        "titulo": v["titulo"], "canal": canal.get("nombre"), "rol": canal.get("rol"),
                        "publicado": v["publicado"].isoformat() if v["publicado"] else None,
                        "detectado": ahora.isoformat(timespec="seconds"), "estado": est, "motivo": motivo}
                historial.append(fila)
                actual[v["id"]] = {**(previo or {}), **fila}
            if est == "nuevo":
                encontrados.append(v["id"])
            nuevos += est == "nuevo"
            descartados += est == "descartado"
        estado[clave] = ahora.isoformat(timespec="seconds")
        resumen.append({"canal": canal.get("nombre"), "nuevos": nuevos, "descartados": descartados})
    _guardar_historial(nicho, historial)
    (carpeta / "fuentes_estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    rango = {"ultimos": ultimos} if ultimos else {"dias": dias}
    _ruta_busqueda(nicho).write_text(json.dumps({"fecha": ahora.isoformat(timespec="seconds"), **rango,
                                                 "ids": encontrados}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"activo": True, "canales": resumen, **rango}


def _pendientes(nicho: str) -> tuple[list[dict], list[dict]]:
    """(candidatos, anteriores) entre los videos por procesar ("nuevo"). Candidatos: lo que trajo la última búsqueda
    de canales que siguen configurados y activos, más los links pegados a mano. Anteriores: el resto (búsquedas
    previas o canales quitados), que no se pierde: el panel lo muestra plegado."""
    config = cargar_config(nicho)
    activos = {c.get("nombre") for c in config.get("canales") or [] if c.get("activo", True)}
    ids = set(ultima_busqueda(nicho).get("ids") or [])
    candidatos_, anteriores_ = [], []
    for f in estado_actual(leer_historial(nicho)).values():
        if f.get("estado") != "nuevo":
            continue
        if es_manual(f) or (f["id"] in ids and f.get("canal") in activos):
            candidatos_.append(f)
        else:
            anteriores_.append(f)
    return candidatos_, anteriores_


def candidatos(nicho: str) -> list[dict]:
    return _pendientes(nicho)[0]


def anteriores(nicho: str) -> list[dict]:
    return _pendientes(nicho)[1]


def descartar(nicho: str, ids: list[str]) -> list[str]:
    """El operador descarta videos por procesar: quedan en el historial y no vuelven como candidatos."""
    actual = estado_actual(leer_historial(nicho))
    elegidos = [i for i in dict.fromkeys(ids) if (actual.get(i) or {}).get("estado") == "nuevo"]
    if elegidos:
        ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        historial = leer_historial(nicho) + [{"id": i, "estado": "descartado", "por": "operador",
                                              "motivo": "descartado por el operador", "detectado": ahora}
                                             for i in elegidos]
        _guardar_historial(nicho, historial)
    return elegidos


# ── Procesar ────────────────────────────────────────────────

def _lanzar_registrado(cmd: list[str], sesion: str) -> tuple[str, int]:
    """Lanza el pipeline como una corrida del backend (runs.json): el panel la ve en vivo, con su log."""
    backend = str(LEGACY / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from app.services import pipeline_runner
    return pipeline_runner.lanzar_y_esperar(cmd, sesion, "fuentes")


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
        seguro = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in vid)[:60]
        sesion = f"{datetime.now():%Y%m%d}_{'medios' if f.get('rol') == 'medios' else 'propio'}_{seguro}"
        cmd = [sys.executable, str(LEGACY / "pipeline.py"), "--video", f["url"], "--config", nicho, "--colab",
               "--session-id", sesion]
        if f.get("rol") == "medios":
            cmd += ["--medios", "--sobre", str(config.get("sobre") or "")]
        historial.append({"id": vid, "estado": "procesando", "sesion": sesion,
                          "inicio": datetime.now().isoformat(timespec="seconds")})
        _guardar_historial(nicho, historial)            # el panel lo muestra como "Procesando"
        print(f"[FUENTES] Procesando «{f['titulo'][:60]}» -> {sesion}", flush=True)
        try:
            run_id, rc = _lanzar_registrado(cmd, sesion)
        except Exception as e:  # noqa: BLE001 — p. ej. la sesión ya tiene una corrida en curso
            print(f"[FUENTES] No se pudo lanzar {sesion}: {e}", flush=True)
            rc = 1
        estado = "procesado" if rc == 0 else "error"
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
    ejemplo: dict[str, str] = {}
    for f in leer_lista(nicho):
        canal = f.get("canal") or ""
        if canal and exclusion.normalizar(canal) not in ya:
            conteo[canal] = conteo.get(canal, 0) + 1
            ejemplo.setdefault(canal, f.get("url") or "")
    # "url": un video del canal; el tipo YouTube resuelve el canal a partir de él (agregar con un clic, CLIP-66)
    return [{"canal": c, "apariciones": n, "url": ejemplo[c]} for c, n in sorted(conteo.items(), key=lambda x: -x[1])]


def main() -> None:
    # En Windows la salida redirigida a un archivo usa cp1252: sin esto un título con emoji o acentos raros
    # tumbaba el proceso antes de empezar (2026-11-19)
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
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
        cands, previos = _pendientes(args.nicho)
        print(f"\n[FUENTES] {len(cands)} candidato(s) para procesar:")
        for f in sorted(cands, key=lambda x: x.get("publicado") or "", reverse=True):
            print(f"  {f['id']}  [{f['rol']:6s}] {f['canal']}: {f['titulo'][:70]}  ({(f.get('publicado') or '')[:10]})")
        if previos:
            print(f"[FUENTES] + {len(previos)} de búsquedas anteriores sin procesar (no se muestran)")
    elif args.accion == "procesar":
        ids = [f["id"] for f in candidatos(args.nicho)] if args.todos else args.ids
        for r in procesar(args.nicho, ids):
            print(f"  {r['id']} → {r['estado']} ({r['sesion']})")
    elif args.accion == "descubrir":
        for c in descubrir(args.nicho):
            print(f"  {c['canal']} ({c['apariciones']} aparición(es) en búsquedas)")


if __name__ == "__main__":
    main()
