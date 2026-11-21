"""
enlazar_tiktok.py — CLIP-69: enlaza solo cada video publicado en TikTok con el clip de Clipeo que lo originó.

    python -m investigacion.enlazar_tiktok zapatillas_peru [--simular]

El operador publica desde la app los borradores que Clipeo envía (estado `en_bandeja`); hasta ahora el link había que
pegarlo a mano en la revisión. Este módulo lee el PERFIL PÚBLICO de la cuenta (`publicacion.tiktok_perfil` del nicho)
con yt-dlp — solo lectura: nunca publica, edita ni borra — y empareja cada video con un borrador enviado:
  - misma duración (±1 s), y
  - publicado después de que Clipeo envió el borrador.
Si hay más de un borrador posible, no adivina: lo informa para pegarlo a mano. Registra en `publicados.jsonl` (el mismo
archivo del link pegado a mano), sin duplicar ni pisar. `medir_publicados` lo llama antes de medir.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from investigacion import comun

LEGACY = Path(__file__).resolve().parent.parent
TOLERANCIA_S = 1.0


def perfil(nicho: str) -> str | None:
    ruta = LEGACY / "contexto" / "nichos" / f"{nicho}.yaml"
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except OSError:
        return None
    return ((datos.get("publicacion") or {}).get("tiktok_perfil") or "").strip() or None


def listar_perfil(handle: str, n: int = 30) -> list[dict]:
    """Últimos videos del perfil público → [{id, url, duracion, publicado (datetime UTC)}]."""
    import yt_dlp
    usuario = handle.lstrip("@")
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": n}) as ydl:
        info = ydl.extract_info(f"https://www.tiktok.com/@{usuario}", download=False) or {}
    videos = []
    for e in info.get("entries") or []:
        if not e.get("id") or e.get("timestamp") is None:
            continue
        videos.append({"id": str(e["id"]), "url": f"https://www.tiktok.com/@{usuario}/video/{e['id']}",
                       "duracion": float(e.get("duration") or 0),
                       "publicado": datetime.fromtimestamp(e["timestamp"], tz=timezone.utc)})
    return videos


def duracion_video(ruta: str | Path) -> float | None:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _base() -> Path:
    from investigacion.medir_publicados import _base_publicacion
    return _base_publicacion()


def borradores(nicho: str, base: Path | None = None, duracion=duracion_video) -> list[dict]:
    """Borradores de TikTok que Clipeo envió (en_bandeja) → [{session_id, clip_id, enviada (datetime), duracion}]."""
    base = base or _base()
    if not base.exists():
        return []
    conn = sqlite3.connect(str(base))
    try:
        filas = conn.execute("SELECT session_id, clip_id, enviada_en, ruta_video FROM publicaciones "
                             "WHERE plataforma='tiktok' AND nicho=? AND estado='en_bandeja' AND enviada_en IS NOT NULL",
                             (nicho,)).fetchall()
    finally:
        conn.close()
    salida = []
    for sid, clip, enviada, ruta in filas:
        dur = duracion(ruta) if ruta else None
        if dur is None:
            continue
        salida.append({"session_id": sid, "clip_id": clip, "duracion": dur,
                       "enviada": datetime.fromisoformat(enviada).astimezone(timezone.utc)})
    return salida


def ya_enlazados(nicho: str) -> tuple[set[str], set[tuple]]:
    """(ids de video ya registrados, (sesión, clip) ya enlazados en TikTok)."""
    archivo = comun.carpeta_nicho(nicho) / "publicados.jsonl"
    ids, clips = set(), set()
    if archivo.exists():
        for l in archivo.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                if r.get("plataforma", "tiktok") == "tiktok":
                    ids.add(str(r.get("video_id") or r.get("url", "").rstrip("/").rsplit("/", 1)[-1]))
                    clips.add((r.get("session_id"), r.get("clip_id")))
    return ids, clips


def emparejar(videos: list[dict], pendientes: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """(enlaces [(video, borrador)], ambiguos [{video, candidatos}]). Puro: por duración y orden en el tiempo."""
    enlaces, ambiguos, usados = [], [], set()
    for v in sorted(videos, key=lambda x: x["publicado"]):
        cands = [b for b in pendientes if (b["session_id"], b["clip_id"]) not in usados
                 and abs(b["duracion"] - v["duracion"]) <= TOLERANCIA_S and b["enviada"] <= v["publicado"]]
        if len(cands) == 1:
            usados.add((cands[0]["session_id"], cands[0]["clip_id"]))
            enlaces.append((v, cands[0]))
        elif len(cands) > 1:
            ambiguos.append({"video": v, "candidatos": [f"{b['session_id']}/{b['clip_id']}" for b in cands]})
    return enlaces, ambiguos


def enlazar(nicho: str, simular: bool = False, lector=listar_perfil, base: Path | None = None,
            duracion=duracion_video) -> dict:
    handle = perfil(nicho)
    if not handle:
        return {"error": "falta publicacion.tiktok_perfil en el YAML del nicho", "enlazados": [], "ambiguos": []}
    try:
        videos = lector(handle)
    except Exception as e:  # noqa: BLE001 — TikTok puede cambiar o pedir verificación: seguir con los links a mano
        return {"error": f"no se pudo leer el perfil de TikTok ({str(e)[:120]})", "enlazados": [], "ambiguos": []}
    ids, clips = ya_enlazados(nicho)
    videos = [v for v in videos if v["id"] not in ids]
    pendientes = [b for b in borradores(nicho, base, duracion) if (b["session_id"], b["clip_id"]) not in clips]
    enlaces, ambiguos = emparejar(videos, pendientes)
    hechos = []
    for v, b in enlaces:
        registro = {"fecha": datetime.now().isoformat(timespec="seconds"), "session_id": b["session_id"],
                    "clip_id": b["clip_id"], "plataforma": "tiktok", "video_id": v["id"], "url": v["url"],
                    "origen": "automatico"}
        if not simular:
            comun.registrar_publicado(nicho, registro)
        hechos.append(registro)
    return {"error": None, "enlazados": hechos, "ambiguos": ambiguos}


def main() -> None:
    for flujo in (sys.stdout, sys.stderr):   # consola de Windows (cp1252): que una flecha o un emoji no lo tumbe
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    ap = argparse.ArgumentParser(description="CLIP-69: enlaza los videos publicados en TikTok con sus clips")
    ap.add_argument("nicho")
    ap.add_argument("--simular", action="store_true", help="muestra los enlaces sin registrarlos")
    args = ap.parse_args()
    r = enlazar(args.nicho, simular=args.simular)
    if r["error"]:
        print(f"[ENLAZAR] ⚠ {r['error']}")
        return
    for e in r["enlazados"]:
        print(f"[ENLAZAR] {e['session_id']}/{e['clip_id']} → {e['url']}" + (" (simulado)" if args.simular else ""))
    for a in r["ambiguos"]:
        print(f"[ENLAZAR] ? {a['video']['url']} coincide con {', '.join(a['candidatos'])}: pégalo a mano en la revisión")
    if not r["enlazados"] and not r["ambiguos"]:
        print("[ENLAZAR] Nada nuevo para enlazar.")


if __name__ == "__main__":
    main()
