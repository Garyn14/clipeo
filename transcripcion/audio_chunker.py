"""
audio_chunker.py — Extrae fragmentos de audio de un video usando FFmpeg input seek.

Uso interno:
    from transcripcion.audio_chunker import extract_audio_chunk
    path = extract_audio_chunk(video_path, "00:30:00", "01:00:00", output_path)
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import subprocess
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from core.utils import _timestamp_to_seconds, setup_ffmpeg_path
setup_ffmpeg_path()


def extract_audio_chunk(
    video_path: Path,
    inicio_ts: str,
    fin_ts: str,
    output_path: Path,
) -> Path:
    """
    Extrae el audio entre inicio_ts y fin_ts usando input seek (rápido, keyframe).
    Guarda como MP3 en output_path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duracion = _timestamp_to_seconds(fin_ts) - _timestamp_to_seconds(inicio_ts)

    cmd = [
        "ffmpeg",
        "-ss", inicio_ts,
        "-i", str(video_path),
        "-t", str(duracion),
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "5",
        "-v", "error",
        "-y", str(output_path),
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg falló al extraer chunk de audio:\n{result.stderr[-400:]}"
        )

    return output_path
