"""
fuentes_medios.py — CLIP-43: busca segmentos nuevos de TV/prensa sobre la persona del nicho y deja una lista para
que el operador apruebe cuáles procesar (aprobación por video, R-01).

    python -m investigacion.fuentes_medios buscar zapatillas_peru --sobre fritz      # busca y agrega pendientes
    python -m investigacion.fuentes_medios listar zapatillas_peru                    # pendientes numerados
    python -m investigacion.fuentes_medios procesar zapatillas_peru 1 3              # corre el pipeline (--medios --colab)
    python -m investigacion.fuentes_medios descartar zapatillas_peru 2

La lista vive en investigacion/<nicho>/fuentes_medios.jsonl (solo metadatos públicos: id, título, canal, duración).
Filtra: canales propios de la persona, lo ya procesado o listado, la lista de exclusión y duraciones fuera de 1–25 min.
YouTube bloquea la nube: correr en la laptop.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from core import exclusion
from core.fuente import nombre_sobre
from investigacion import comun

LEGACY = Path(__file__).resolve().parent.parent
DURACION_MIN, DURACION_MAX = 60, 25 * 60
POR_CONSULTA = 15


def _stream_data() -> Path:
    env = os.environ.get("CLIPEO_STREAM_DATA")
    if env:
        return Path(env).resolve()
    raiz = LEGACY.parent / "stream_data"
    return raiz if raiz.exists() else LEGACY / "stream_data"


def ruta_lista(nicho: str) -> Path:
    return comun.RAIZ / "investigacion" / nicho / "fuentes_medios.jsonl"


def leer_lista(nicho: str) -> list[dict]:
    p = ruta_lista(nicho)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def guardar_lista(nicho: str, filas: list[dict]) -> None:
    p = ruta_lista(nicho)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas), encoding="utf-8")


def ids_procesados(stream_data: Path) -> set[str]:
    """Ids de YouTube ya procesados en alguna sesión (por la URL guardada en pipeline_estado.json)."""
    ids = set()
    for p in stream_data.glob("*/pipeline_estado.json"):
        try:
            url = json.loads(p.read_text(encoding="utf-8")).get("url") or ""
        except (OSError, json.JSONDecodeError):
            continue
        if "v=" in url or "youtu.be/" in url:
            ids.add(url.split("v=")[-1].split("youtu.be/")[-1].split("&")[0])
        elif "kick.com/" in url and "/videos/" in url:          # CLIP-70: VOD de Kick
            ids.add(url.rstrip("/").rsplit("/", 1)[-1])
    return ids


def consultas(persona: str, nombre_real: str | None = None) -> list[str]:
    base = [persona, f"{persona} noticias", f"{persona} entrevista"]
    return base + ([nombre_real] if nombre_real else [])


def filtrar(resultados: list[dict], persona: str, ya_vistos: set[str]) -> list[dict]:
    """Candidatos nuevos a partir de resultados de búsqueda (dicts de yt-dlp --flat-playlist). Puro."""
    palabras = {w for w in exclusion.normalizar(persona).split() if len(w) > 3}   # "tio fritz" → {"fritz"}
    salida, vistos = [], set(ya_vistos)
    for r in resultados:
        vid, canal = r.get("id"), r.get("channel") or r.get("uploader") or ""
        dur = r.get("duration") or 0
        canal_n = exclusion.normalizar(canal).replace(" ", "")
        if not vid or vid in vistos or not canal:        # sin canal no se puede descartar que sea el propio
            continue
        if any(w in canal_n for w in palabras):          # canal propio de la persona (FRITZ SPORT, FritzSport…)
            continue
        if not (DURACION_MIN <= dur <= DURACION_MAX) or exclusion.motivo(canal=canal):
            continue
        vistos.add(vid)
        salida.append({"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "titulo": r.get("title") or "",
                       "canal": canal, "duracion_s": int(dur), "sobre": persona,
                       "encontrado": datetime.now().isoformat(timespec="seconds"), "estado": "pendiente"})
    return salida


def _buscar_youtube(consulta: str, n: int) -> list[dict]:
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings", f"ytsearch{n}:{consulta}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip().startswith("{")]


def buscar(nicho: str, sobre: str, por_consulta: int = POR_CONSULTA) -> list[dict]:
    persona = nombre_sobre(sobre)
    real = None
    try:
        import yaml
        ent = yaml.safe_load((LEGACY / "contexto" / "entidades" / f"{sobre.lower()}.yaml").read_text(encoding="utf-8"))
        real = (ent.get("entidad") or {}).get("nombre_real")
    except (OSError, AttributeError):
        pass
    lista = leer_lista(nicho)
    vistos = {f["id"] for f in lista} | ids_procesados(_stream_data())
    resultados = [r for q in consultas(persona, real) for r in _buscar_youtube(q, por_consulta)]
    nuevos = filtrar(resultados, persona, vistos)
    guardar_lista(nicho, lista + nuevos)
    return nuevos


def pendientes(nicho: str) -> list[dict]:
    return [f for f in leer_lista(nicho) if f.get("estado") == "pendiente"]


def _marcar(nicho: str, ids: set[str], **campos) -> None:
    lista = leer_lista(nicho)
    for f in lista:
        if f["id"] in ids:
            f.update(campos)
    guardar_lista(nicho, lista)


def _elegir(nicho: str, numeros: list[int]) -> list[dict]:
    pend = pendientes(nicho)
    return [pend[n - 1] for n in numeros if 1 <= n <= len(pend)]


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-43: fuentes de medios para aprobar")
    sub = ap.add_subparsers(dest="accion", required=True)
    b = sub.add_parser("buscar"); b.add_argument("nicho"); b.add_argument("--sobre", required=True)
    b.add_argument("--por-consulta", type=int, default=POR_CONSULTA)
    l = sub.add_parser("listar"); l.add_argument("nicho")
    p = sub.add_parser("procesar"); p.add_argument("nicho"); p.add_argument("numeros", type=int, nargs="+")
    d = sub.add_parser("descartar"); d.add_argument("nicho"); d.add_argument("numeros", type=int, nargs="+")
    args = ap.parse_args()

    if args.accion == "buscar":
        nuevos = buscar(args.nicho, args.sobre, args.por_consulta)
        print(f"[FUENTES] {len(nuevos)} candidato(s) nuevo(s) → {ruta_lista(args.nicho)}")
        args.accion = "listar"
    if args.accion == "listar":
        pend = pendientes(args.nicho)
        print(f"[FUENTES] {len(pend)} pendiente(s) de aprobar:")
        for i, f in enumerate(pend, 1):
            print(f"  {i:2d}. [{f['canal']}] {f['titulo'][:80]}  ({f['duracion_s'] // 60}:{f['duracion_s'] % 60:02d})  {f['url']}")
        print("Procesar: python -m investigacion.fuentes_medios procesar <nicho> <n> [...] · descartar: … descartar <nicho> <n>")
    elif args.accion == "descartar":
        elegidos = _elegir(args.nicho, args.numeros)
        _marcar(args.nicho, {f["id"] for f in elegidos}, estado="descartado")
        print(f"[FUENTES] {len(elegidos)} descartado(s)")
    elif args.accion == "procesar":
        for f in _elegir(args.nicho, args.numeros):
            sesion = f"{datetime.now():%Y%m%d}_medios_{f['id']}"
            print(f"[FUENTES] Procesando «{f['titulo'][:60]}» → sesión {sesion}")
            r = subprocess.run([sys.executable, str(LEGACY / "pipeline.py"), "--video", f["url"], "--config", args.nicho,
                                "--medios", "--sobre", f["sobre"], "--colab", "--session-id", sesion],
                               cwd=str(_stream_data().parent))   # la sesión queda en el stream_data de siempre
            _marcar(args.nicho, {f["id"]}, estado="procesado" if r.returncode == 0 else "error", sesion=sesion)


if __name__ == "__main__":
    main()
