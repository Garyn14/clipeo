"""
video_capture.py — Descarga video + extrae audio desde cualquier URL soportada por yt-dlp.

Uso interno:
    from core.video_capture import download_video
    info = download_video(url, session_dir)
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import subprocess
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from core.utils import setup_ffmpeg_path
setup_ffmpeg_path()


def _run(cmd: list[str], label: str) -> subprocess.CompletedProcess:
    t0 = time.time()
    proceso = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    lineas: list[str] = []
    for linea in proceso.stdout:
        linea = linea.rstrip("\r\n")
        if linea:
            print(f"    [{label}] {linea}")
            lineas.append(linea)

    proceso.wait()
    salida = "\n".join(lineas)
    elapsed = time.time() - t0

    if proceso.returncode != 0:
        raise RuntimeError(
            f"[{label}] falló (exit {proceso.returncode}, {elapsed:.1f}s):\n"
            f"  CMD : {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}\n"
            f"  ERR : {salida[-600:]}"
        )

    print(f"    [{label}] completado en {elapsed:.1f}s")
    return subprocess.CompletedProcess(cmd, proceso.returncode, salida, "")


def download_video(url: str, session_dir: Path) -> dict:
    """
    Descarga el video en ≤1080p y extrae el audio completo como mp3.

    Retorna:
        {
            "video_path":        Path,
            "audio_path":        Path,
            "duracion_segundos": float,
            "titulo":            str,
        }
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    audio_dir  = session_dir / "audio"
    audio_dir.mkdir(exist_ok=True)

    video_path = session_dir / "stream_completo.mp4"
    audio_path = audio_dir   / "audio_completo.mp3"

    # ── 1. Descargar video ───────────────────────────────────
    print("[VIDEO] Descargando video...")
    _run([
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--output", str(video_path),
        url,
    ], label="VIDEO")

    size_mb = video_path.stat().st_size / (1024 * 1024)
    print(f"[VIDEO] ✅ {video_path.name} — {size_mb:.1f} MB")

    # ── 2. Extraer audio con ffmpeg (ya tenemos el video) ────
    print("[VIDEO] Extrayendo audio...")
    _run([
        "ffmpeg",
        "-i", str(video_path),
        "-vn", "-acodec", "libmp3lame", "-q:a", "5",
        "-y", str(audio_path),
    ], label="AUDIO")

    audio_mb = audio_path.stat().st_size / (1024 * 1024)
    print(f"[VIDEO] ✅ {audio_path.name} — {audio_mb:.1f} MB")

    # ── 3. Duración con ffprobe ──────────────────────────────
    dur = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video_path),
        ],
        capture_output=True, text=True,
    )
    try:
        duracion = float(dur.stdout.strip())
    except (ValueError, AttributeError):
        duracion = 0.0

    minutos = duracion / 60
    print(f"[VIDEO] Duración: {minutos:.1f} minutos ({duracion:.0f}s)")

    # ── 4. Metadata completa con yt-dlp --dump-json ─────────────
    meta_path = session_dir / "metadata.json"
    meta_r = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-playlist", url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    titulo = ""
    if meta_r.returncode == 0 and meta_r.stdout.strip():
        try:
            meta_dict = json.loads(meta_r.stdout.strip())
            meta_path.write_text(
                json.dumps(meta_dict, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            titulo = meta_dict.get("title", "") or meta_dict.get("fulltitle", "")
            print(f"[VIDEO] metadata.json guardado ({len(meta_dict)} campos)")
        except json.JSONDecodeError:
            pass
    if titulo:
        print(f"[VIDEO] Título: {titulo}")

    return {
        "video_path":        video_path,
        "audio_path":        audio_path,
        "duracion_segundos": duracion,
        "titulo":            titulo,
        "metadata_path":     meta_path if meta_path.exists() else None,
    }
