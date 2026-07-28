"""
utils.py — Utilidades compartidas del pipeline.

Funciones de timestamp, parsing de segmentos y setup de FFmpeg
que antes estaban duplicadas en cada agente.
"""

import os
import re

from dotenv import load_dotenv
load_dotenv()

_FFMPEG_BIN = (
    r"C:\Users\Garyn\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    r"\ffmpeg-8.1.1-full_build\bin"
)


def setup_ffmpeg_path() -> None:
    """Inyecta el directorio de FFmpeg en PATH si aún no está."""
    if _FFMPEG_BIN not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _FFMPEG_BIN + os.pathsep + os.environ.get("PATH", "")


def _timestamp_to_seconds(ts: str) -> int:
    """Convierte MM:SS o HH:MM:SS a segundos enteros."""
    parts = ts.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        pass
    return 0


def _seconds_to_timestamp(secs: int) -> str:
    """Convierte segundos a HH:MM:SS."""
    return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


def _parse_segments(text: str) -> list[tuple[int, str]]:
    """
    Extrae (segundos, línea) de cada línea con timestamp [MM:SS] o [HH:MM:SS].
    """
    segments = []
    for line in text.splitlines():
        m = re.match(r"\[(\d+):(\d+)(?::(\d+))?\]", line)
        if m:
            if m.group(3) is not None:
                secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            else:
                secs = int(m.group(1)) * 60 + int(m.group(2))
            segments.append((secs, line.strip()))
    return segments
