"""
negocio.py — S17: reporte de negocio por cliente (CLIP-73 lector de cuentas, CLIP-74 reporte por mes).

    python -m investigacion.negocio actualizar zapatillas_peru        # lee todas las cuentas y guarda una foto
    python -m investigacion.negocio reporte zapatillas_peru [--mes 2026-11]

CLIP-73: lee TODOS los videos de cada cuenta de publicación del cliente (TikTok: `publicacion.tiktok_perfil`;
YouTube: `publicacion.youtube_canal` del YAML del nicho) con yt-dlp — solo lectura, sin cuenta ni costo —, marca los que
publicó Clipeo (con su tipo y origen) y guarda una **foto fechada** en `data/negocio/<nicho>/` (fuera del repo: es
público y estas son cifras de negocio del cliente).

CLIP-74: `reporte(nicho, mes)` calcula, sobre la última foto y sin volver a leer las cuentas, el resumen del mes vs el
anterior, por cuenta, top/bottom, desgloses, producción y evolución. "Vistas del mes" = vistas acumuladas, a la fecha de
la foto, de los videos publicados ese mes. Seguidores: CLIP-75 (cada cuenta tendrá `seguidores` sin cambiar el resto).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import yaml

from investigacion import comun

LEGACY = Path(__file__).resolve().parent.parent
MESES_EVOLUCION = 6
TOP = 5


# ── Rutas ───────────────────────────────────────────────────

def carpeta_datos(nicho: str) -> Path:
    from core.config_local import ruta
    return ruta("CLIPEO_NEGOCIO", LEGACY.parent / "data" / "negocio") / nicho


def _base_publicacion() -> Path:
    from investigacion.medir_publicados import _base_publicacion
    return _base_publicacion()


def _config_nicho(nicho: str) -> dict:
    ruta = LEGACY / "contexto" / "nichos" / f"{nicho}.yaml"
    try:
        return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


# ── Clientes y cuentas ──────────────────────────────────────

def nombre_cliente(nicho: str) -> str:
    ruta = comun.carpeta_nicho(nicho) / "fuentes.yaml"
    try:
        nombre = (yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("cliente")
    except OSError:
        nombre = None
    return nombre or nicho.replace("_", " ").title()


def clientes(base: Path | None = None) -> list[str]:
    """Nichos con cuentas de publicación: en el YAML del nicho o en la base de publicación."""
    nichos = {p.stem for p in (LEGACY / "contexto" / "nichos").glob("*.yaml")
              if (_config_nicho(p.stem).get("publicacion") or {}).get("tiktok_perfil")
              or (_config_nicho(p.stem).get("publicacion") or {}).get("youtube_canal")}
    base = base or _base_publicacion()
    if base.exists():
        conn = sqlite3.connect(str(base))
        try:
            nichos |= {n for (n,) in conn.execute("SELECT DISTINCT nicho FROM cuentas")}
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return sorted(nichos)


def _canal_youtube(valor: str) -> str:
    valor = valor.strip()
    if re.fullmatch(r"UC[\w-]{22}", valor):
        return f"https://www.youtube.com/channel/{valor}"
    return valor.rstrip("/")


def cuentas(nicho: str, base: Path | None = None) -> tuple[list[dict], list[str]]:
    """([{plataforma, cuenta, url}], avisos). YouTube sin `youtube_canal`: se deduce de un Short publicado."""
    pub = _config_nicho(nicho).get("publicacion") or {}
    salida, avisos = [], []
    handle = (pub.get("tiktok_perfil") or "").strip().lstrip("@")
    if handle:
        salida.append({"plataforma": "tiktok", "cuenta": f"@{handle}", "url": f"https://www.tiktok.com/@{handle}"})
    canal = (pub.get("youtube_canal") or "").strip()
    if not canal:
        canal = _deducir_canal_youtube(nicho, base) or ""
        if canal:
            avisos.append(f"YouTube: canal deducido de un Short publicado ({canal}); fíjalo en "
                          f"publicacion.youtube_canal del YAML del nicho")
    if canal:
        salida.append({"plataforma": "youtube", "cuenta": canal, "url": _canal_youtube(canal)})
    if not salida:
        avisos.append("el nicho no tiene cuentas configuradas (publicacion.tiktok_perfil / youtube_canal)")
    return salida, avisos


def _deducir_canal_youtube(nicho: str, base: Path | None = None) -> str | None:
    base = base or _base_publicacion()
    if not base.exists():
        return None
    conn = sqlite3.connect(str(base))
    try:
        fila = conn.execute("SELECT publish_id FROM publicaciones WHERE plataforma='youtube' AND nicho=? AND "
                            "publish_id IS NOT NULL ORDER BY id DESC LIMIT 1", (nicho,)).fetchone()
    except sqlite3.Error:
        fila = None
    finally:
        conn.close()
    if not fila:
        return None
    try:
        return _yt_dlp_json(["--skip-download", f"https://www.youtube.com/shorts/{fila[0]}"]).get("channel_id")
    except RuntimeError:
        return None


# ── Lectura con yt-dlp (CLIP-73) ────────────────────────────

def _yt_dlp_json(args: list[str], timeout: int = 900) -> dict:
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-J", "--no-warnings", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    i = r.stdout.find("{")
    if r.returncode != 0 or i < 0:
        error = (r.stderr.strip().splitlines() or ["sin salida"])[-1]
        raise RuntimeError(error[:200])
    return json.loads(r.stdout[i:])


def _fecha(e: dict) -> str | None:
    if e.get("timestamp"):
        return datetime.fromtimestamp(e["timestamp"], timezone.utc).isoformat(timespec="seconds")
    d = e.get("upload_date")
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}T00:00:00+00:00" if d and len(d) == 8 else None


def fila_video(e: dict, plataforma: str, cuenta: str) -> dict:
    """Entrada de yt-dlp → fila normalizada. Puro."""
    url = e.get("webpage_url") or e.get("url") or ""
    if plataforma == "youtube" and e.get("id"):
        url = f"https://www.youtube.com/shorts/{e['id']}" if (e.get("duration") or 999) <= 180 else \
            f"https://www.youtube.com/watch?v={e['id']}"
    return {"plataforma": plataforma, "cuenta": cuenta, "id": str(e.get("id") or ""), "url": url,
            "titulo": (e.get("title") or e.get("description") or "").strip(), "publicado": _fecha(e),
            "duracion_s": e.get("duration"), "vistas": e.get("view_count") or 0, "likes": e.get("like_count"),
            "comentarios": e.get("comment_count"), "compartidos": e.get("repost_count")}


def leer_cuenta(cuenta: dict) -> list[dict]:
    """Todos los videos de una cuenta (sin descargar nada)."""
    if cuenta["plataforma"] == "tiktok":
        datos = _yt_dlp_json(["--flat-playlist", cuenta["url"]])
        entradas = datos.get("entries") or []
    else:
        entradas = []
        for pestaña in ("shorts", "videos"):
            try:
                entradas += _yt_dlp_json([f"{cuenta['url']}/{pestaña}"]).get("entries") or []
            except RuntimeError as e:
                if "does not have a" not in str(e) and "This channel does not have" not in str(e):
                    raise
    vistos, filas = set(), []
    for e in entradas:
        if e and e.get("id") and e["id"] not in vistos:
            vistos.add(e["id"])
            filas.append(fila_video(e, cuenta["plataforma"], cuenta["cuenta"]))
    return filas


# ── Marca de Clipeo ─────────────────────────────────────────

def _id_de_url(url: str) -> str:
    m = re.search(r"/video/(\d+)|/shorts/([\w-]{6,})|[?&]v=([\w-]{6,})", url or "")
    return next((g for g in m.groups() if g), "") if m else ""


def _contexto_publicados(nicho: str, base: Path | None = None) -> dict[tuple[str, str], dict]:
    """(plataforma, id del video) → {clave, tipo, origen} de lo que publicó Clipeo."""
    from investigacion import fuentes_estaticas as fe
    from investigacion import medir_publicados as mp
    from investigacion import tipos_fuente as tf
    ultimas: dict[str, dict] = {}
    archivo = comun.carpeta_nicho(nicho) / "metricas_publicados.jsonl"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                r = json.loads(linea)
                ultimas[r["clave"]] = r
    por_sesion = {f.get("sesion"): f for f in fe.estado_actual(fe.leer_historial(nicho)).values() if f.get("sesion")}
    stream_data = None
    salida = {}
    for p in mp.publicados(nicho, base):
        contexto = ultimas.get(p["clave"])
        if contexto is None:
            stream_data = stream_data or mp._stream_data()
            contexto = mp._contexto_clip(p["clave"], stream_data)
        fuente = por_sesion.get(p["clave"].split("/", 1)[0])
        if fuente and tf.plataforma_de(fuente.get("url")) == "Kick":
            origen = "Kick"
        elif (fuente and fuente.get("rol") == "medios") or contexto.get("medios"):
            origen = "TV / medios"
        else:
            origen = "Propio"
        salida[(p["plataforma"], _id_de_url(p["url"]))] = {"clave": p["clave"], "tipo": contexto.get("tipo"),
                                                           "origen": origen, "titulo_clip": contexto.get("titulo")}
    return salida


def marcar_clipeo(videos: list[dict], publicados: dict[tuple[str, str], dict]) -> list[dict]:
    """Agrega clipeo/clave/tipo/origen a cada video. Puro."""
    salida = []
    for v in videos:
        info = publicados.get((v["plataforma"], v["id"]))
        salida.append({**v, "clipeo": bool(info),
                       **({k: info.get(k) for k in ("clave", "tipo", "origen", "titulo_clip")} if info else {})})
    return salida


# ── Foto (CLIP-73) ──────────────────────────────────────────

def actualizar(nicho: str, lector=leer_cuenta, base: Path | None = None, ahora: datetime | None = None) -> dict:
    """Lee todas las cuentas del cliente y guarda la foto. Una cuenta caída no frena a las demás."""
    ahora = ahora or datetime.now(timezone.utc)
    lista, avisos = cuentas(nicho, base)
    try:
        publicados = _contexto_publicados(nicho, base)
    except Exception as e:  # noqa: BLE001 — sin marca de Clipeo el reporte sigue sirviendo
        publicados, avisos = {}, avisos + [f"no se pudo cruzar con lo publicado por Clipeo ({str(e)[:120]})"]
    foto = {"fecha": ahora.isoformat(timespec="seconds"), "nicho": nicho, "avisos": avisos, "cuentas": []}
    for c in lista:
        try:
            videos = marcar_clipeo(lector(c), publicados)
            foto["cuentas"].append({**c, "videos": videos})
        except Exception as e:  # noqa: BLE001
            foto["cuentas"].append({**c, "error": str(e)[:200], "videos": []})
    carpeta = carpeta_datos(nicho)
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{ahora:%Y%m%d_%H%M%S}.json").write_text(json.dumps(foto, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    return foto


def ultima_foto(nicho: str) -> dict | None:
    carpeta = carpeta_datos(nicho)
    fotos = sorted(carpeta.glob("*.json")) if carpeta.exists() else []
    for ruta in reversed(fotos):
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


# ── Reporte (CLIP-74) ───────────────────────────────────────

def _mes(iso: str | None) -> str | None:
    return iso[:7] if iso else None


def mes_anterior(mes: str) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


def _interacciones(v: dict) -> int:
    return sum(v.get(k) or 0 for k in ("likes", "comentarios", "compartidos"))


def resumen(videos: list[dict]) -> dict:
    """Cifras de un grupo de videos. Puro."""
    vistas = sum(v.get("vistas") or 0 for v in videos)
    inter = sum(_interacciones(v) for v in videos)
    return {"videos": len(videos), "vistas": vistas, "interacciones": inter,
            "tasa_interaccion": round(inter / vistas, 4) if vistas else None,
            "mediana_vistas": median([v.get("vistas") or 0 for v in videos]) if videos else None}


def variacion(actual: float | None, anterior: float | None) -> float | None:
    if actual is None or not anterior:
        return None
    return round((actual - anterior) / anterior, 4)


def _con_variacion(actual: dict, anterior: dict) -> dict:
    return {**actual, "anterior": anterior,
            "variacion": {k: variacion(actual[k], anterior[k]) for k in ("videos", "vistas", "interacciones",
                                                                       "mediana_vistas")}}


def _corto(v: dict) -> dict:
    # En TikTok la descripción suele ser solo hashtags: para los clips de Clipeo se muestra el título del juez
    return {**{k: v.get(k) for k in ("plataforma", "url", "publicado", "vistas", "likes", "comentarios",
                                     "compartidos", "clipeo", "origen", "tipo")},
            "titulo": v.get("titulo_clip") or v.get("titulo")}


def _agrupar(videos: list[dict], clave) -> list[dict]:
    grupos: dict[str, list[dict]] = {}
    for v in videos:
        grupos.setdefault(clave(v), []).append(v)
    return sorted(({"grupo": g, **resumen(vs)} for g, vs in grupos.items()), key=lambda x: -x["vistas"])


def produccion(nicho: str, mes: str, base: Path | None = None) -> dict:
    """Clips revisados y aprobados en la revisión, y enviados por plataforma, en el mes."""
    revisados = aprobados = 0
    archivo = comun.carpeta_nicho(nicho) / "correcciones.jsonl"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            r = json.loads(linea)
            if (r.get("fecha") or "")[:7] == mes:
                revisados += 1
                aprobados += r.get("accion") in ("aprobado", "editado")
    enviados: dict[str, int] = {}
    base = base or _base_publicacion()
    if base.exists():
        conn = sqlite3.connect(str(base))
        try:
            for plat, n in conn.execute("SELECT plataforma, COUNT(*) FROM publicaciones WHERE nicho=? AND "
                                        "estado='en_bandeja' AND substr(enviada_en,1,7)=? GROUP BY plataforma",
                                        (nicho, mes)):
                enviados[plat] = n
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return {"revisados": revisados, "aprobados": aprobados, "enviados": enviados}


def meses_disponibles(foto: dict) -> list[str]:
    return sorted({m for c in foto.get("cuentas") or [] for v in c.get("videos") or []
                   if (m := _mes(v.get("publicado")))}, reverse=True)


def reporte(nicho: str, mes: str | None = None, foto: dict | None = None, base: Path | None = None,
            con_produccion: bool = True) -> dict:
    """Minidashboard del cliente para `mes` (AAAA-MM; por defecto el de la foto), sobre la última foto."""
    foto = foto if foto is not None else ultima_foto(nicho)
    if not foto:
        return {"nicho": nicho, "cliente": nombre_cliente(nicho), "foto": None}
    mes = mes or foto["fecha"][:7]
    previo = mes_anterior(mes)
    todos = [v for c in foto.get("cuentas") or [] for v in c.get("videos") or []]
    del_mes = [v for v in todos if _mes(v.get("publicado")) == mes]
    del_previo = [v for v in todos if _mes(v.get("publicado")) == previo]
    ordenados = sorted(del_mes, key=lambda v: -(v.get("vistas") or 0))
    por_cuenta = []
    for c in foto.get("cuentas") or []:
        vm = [v for v in c.get("videos") or [] if _mes(v.get("publicado")) == mes]
        vp = [v for v in c.get("videos") or [] if _mes(v.get("publicado")) == previo]
        por_cuenta.append({"plataforma": c["plataforma"], "cuenta": c["cuenta"], "url": c["url"],
                           "error": c.get("error"), "total_videos": len(c.get("videos") or []),
                           **_con_variacion(resumen(vm), resumen(vp))})
    meses = [mes]
    while len(meses) < MESES_EVOLUCION:
        meses.insert(0, mes_anterior(meses[0]))
    return {
        "nicho": nicho, "cliente": nombre_cliente(nicho), "foto": foto["fecha"], "mes": mes, "mes_anterior": previo,
        "meses": meses_disponibles(foto), "avisos": foto.get("avisos") or [],
        "resumen": _con_variacion(resumen(del_mes), resumen(del_previo)),
        "por_cuenta": por_cuenta,
        "top": [_corto(v) for v in ordenados[:TOP]],
        "bottom": [_corto(v) for v in ordenados[-TOP:][::-1]] if len(ordenados) > TOP else [],
        "por_origen": _agrupar(del_mes, lambda v: v.get("origen") or "No es de Clipeo"),
        "por_tipo": _agrupar([v for v in del_mes if v.get("clipeo")], lambda v: v.get("tipo") or "sin tipo"),
        "clipeo_vs_resto": _agrupar(del_mes, lambda v: "Clipeo" if v.get("clipeo") else "Resto de la cuenta"),
        "produccion": produccion(nicho, mes, base) if con_produccion else None,
        "evolucion": [{"mes": m, **resumen([v for v in todos if _mes(v.get("publicado")) == m])} for m in meses],
        "seguidores": None,   # CLIP-75
    }


def global_(mes: str | None = None, base: Path | None = None) -> list[dict]:
    """Una fila por cliente con el resumen del mes (de su última foto; no lee cuentas)."""
    filas = []
    for nicho in clientes(base):
        foto = ultima_foto(nicho)
        if not foto:
            filas.append({"nicho": nicho, "cliente": nombre_cliente(nicho), "foto": None})
            continue
        r = reporte(nicho, mes, foto=foto, base=base, con_produccion=False)
        filas.append({"nicho": nicho, "cliente": r["cliente"], "foto": r["foto"], "mes": r["mes"],
                      "resumen": r["resumen"], "cuentas": len(foto.get("cuentas") or [])})
    return filas


# ── CLI ─────────────────────────────────────────────────────

def _imprimir(r: dict) -> None:
    if not r.get("foto"):
        print(f"[NEGOCIO] {r['cliente']}: sin datos; corre `actualizar` primero")
        return
    s = r["resumen"]
    print(f"[NEGOCIO] {r['cliente']} · {r['mes']} (datos al {r['foto'][:16]})")
    print(f"  {s['videos']} videos · {s['vistas']:,} vistas · {s['interacciones']:,} interacciones · "
          f"mediana {s['mediana_vistas'] or 0:,.0f}")
    for c in r["por_cuenta"]:
        print(f"  {c['plataforma']:8s} {c['cuenta']}: " + (f"⚠ {c['error']}" if c.get("error") else
                                                           f"{c['videos']} videos · {c['vistas']:,} vistas"))
    for v in r["top"]:
        print(f"    {v['vistas'] or 0:>9,}  {'[Clipeo] ' if v['clipeo'] else ''}{(v['titulo'] or '')[:60]}")


def main() -> None:
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="S17: reporte de negocio por cliente")
    ap.add_argument("accion", choices=["actualizar", "reporte"])
    ap.add_argument("nicho")
    ap.add_argument("--mes", help="AAAA-MM (por defecto, el mes de la foto)")
    args = ap.parse_args()
    if args.accion == "actualizar":
        foto = actualizar(args.nicho)
        for c in foto["cuentas"]:
            print(f"[NEGOCIO] {c['plataforma']} {c['cuenta']}: " +
                  (f"⚠ {c['error']}" if c.get("error") else f"{len(c['videos'])} videos"))
        for a in foto["avisos"]:
            print(f"[NEGOCIO] aviso: {a}")
    _imprimir(reporte(args.nicho, args.mes))


if __name__ == "__main__":
    main()
