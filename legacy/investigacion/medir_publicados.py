"""
medir_publicados.py — CLIP-48 (Q5): mide cómo les va a los clips que publicó Clipeo, en TikTok y YouTube Shorts.

    python -m investigacion.medir_publicados zapatillas_peru

Fuentes de lo publicado:
  - TikTok: los links pegados en la revisión (`investigacion/<nicho>/publicados.jsonl`, CLIP-33);
  - YouTube: los videos que subió el motor de publicación (`publicaciones.publish_id` en la base de publicación).
Métricas públicas con yt-dlp (sin cuenta ni API de pago). Cada medición se agrega a
`investigacion/<nicho>/metricas_publicados.jsonl` con el tipo del juez y la variante de título del clip, para que
`investigacion.aprendizaje` (CLIP-49) cruce rendimiento con criterio. Correr en la laptop.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from investigacion import comun

LEGACY = Path(__file__).resolve().parent.parent


def _stream_data() -> Path:
    env = os.environ.get("CLIPEO_STREAM_DATA")
    if env:
        return Path(env).resolve()
    raiz = LEGACY.parent / "stream_data"
    return raiz if raiz.exists() else LEGACY / "stream_data"


def _base_publicacion() -> Path:
    env = os.environ.get("PUBLICACION_DB")
    if env:
        return Path(env)
    raiz = LEGACY.parent / "backend" / "publicacion.db"      # donde viven las cuentas en la laptop del operador
    return raiz if raiz.exists() else LEGACY / "backend" / "publicacion.db"


def publicados(nicho: str, base: Path | None = None) -> list[dict]:
    """[{plataforma, clave, url}] sin repetir (el último link pegado por clip y plataforma gana)."""
    vistos: dict[tuple, dict] = {}
    archivo = comun.carpeta_nicho(nicho) / "publicados.jsonl"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                r = json.loads(linea)
                clave = f"{r['session_id']}/{r['clip_id']}"
                vistos[(r.get("plataforma", "tiktok"), clave)] = {"plataforma": r.get("plataforma", "tiktok"),
                                                                  "clave": clave, "url": r["url"]}
    base = base or _base_publicacion()
    if base.exists():
        conn = sqlite3.connect(str(base))
        try:
            for sid, clip, vid in conn.execute(
                    "SELECT session_id, clip_id, publish_id FROM publicaciones WHERE plataforma='youtube' AND nicho=? "
                    "AND estado='en_bandeja' AND publish_id IS NOT NULL", (nicho,)):
                vistos[("youtube", f"{sid}/{clip}")] = {"plataforma": "youtube", "clave": f"{sid}/{clip}",
                                                        "url": f"https://www.youtube.com/shorts/{vid}"}
        finally:
            conn.close()
    return list(vistos.values())


def _contexto_clip(clave: str, stream_data: Path) -> dict:
    """Tipo y fuerza del juez y variante de título del clip (para cruzar rendimiento con criterio)."""
    sesion, clip = clave.split("/", 1)
    salida = {}
    try:
        meta = json.loads((stream_data / sesion / "clips" / f"{clip}.json").read_text(encoding="utf-8"))
        salida["estilo_titulo"] = meta.get("estilo_titulo")
        salida["medios"] = bool(meta.get("fuente"))
    except (OSError, json.JSONDecodeError):
        pass
    try:
        for c in json.loads((stream_data / sesion / "contenido_final.json").read_text(encoding="utf-8"))["contenido"]:
            if c.get("clip_id") == clip:
                juez = c.get("juez") or {}
                salida.update(tipo=juez.get("tipo"), fuerza=juez.get("fuerza"), comercial=juez.get("comercial"),
                              titulo=" / ".join(x for x in (c.get("texto_linea1"), c.get("texto_linea2")) if x))
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return salida


def metricas(url: str) -> dict | None:
    r = subprocess.run(["yt-dlp", "--dump-json", "--skip-download", "--no-warnings", url],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    try:
        d = json.loads(r.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None
    ts = d.get("timestamp")
    edad = (datetime.now(timezone.utc).timestamp() - ts) / 86400 if ts else None
    return {"vistas": d.get("view_count"), "likes": d.get("like_count"), "comentarios": d.get("comment_count"),
            "edad_dias": round(edad, 2) if edad is not None else None}


def medir(nicho: str, stream_data: Path | None = None, base: Path | None = None) -> list[dict]:
    stream_data = stream_data or _stream_data()
    filas = []
    ahora = datetime.now().isoformat(timespec="seconds")
    for p in publicados(nicho, base):
        m = metricas(p["url"])
        if m is None:
            continue
        filas.append({"medido": ahora, **p, **m, **_contexto_clip(p["clave"], stream_data)})
    if filas:
        archivo = comun.carpeta_nicho(nicho) / "metricas_publicados.jsonl"
        with archivo.open("a", encoding="utf-8") as f:
            for fila in filas:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-48: métricas de los clips publicados (TikTok y YouTube)")
    ap.add_argument("nicho")
    args = ap.parse_args()
    filas = medir(args.nicho)
    if not filas:
        print("[MEDIR] No hay clips publicados para medir (pega los links de TikTok en la revisión).")
        return
    for plataforma in ("tiktok", "youtube"):
        grupo = [f for f in filas if f["plataforma"] == plataforma]
        if not grupo:
            continue
        vistas = [f["vistas"] or 0 for f in grupo]
        print(f"\n[MEDIR] {plataforma}: {len(grupo)} clip(s) · mediana {median(vistas):,.0f} vistas")
        for f in sorted(grupo, key=lambda x: -(x["vistas"] or 0)):
            print(f"  {f['vistas'] or 0:>9,}  {f.get('edad_dias') or 0:5.1f} d  [{f.get('tipo') or '?'}]  "
                  f"{(f.get('titulo') or f['clave'])[:60]}")
    print(f"\n[MEDIR] → {comun.carpeta_nicho(args.nicho) / 'metricas_publicados.jsonl'}")


if __name__ == "__main__":
    main()
