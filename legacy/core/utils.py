"""
utils.py — Utilidades compartidas del pipeline.

Funciones de timestamp, parsing de segmentos y setup de FFmpeg
que antes estaban duplicadas en cada agente.
"""

import os
import re
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


def _ffmpeg_bin_dir() -> str | None:
    """
    Directorio de FFmpeg a agregar al PATH, o None si basta con el del sistema.

    1. `FFMPEG_BIN_DIR` (variable de entorno o .env), si está definida.
    2. Si `ffmpeg` ya está en el PATH: None.
    3. Solo en Windows: instalación de WinGet (Gyan.FFmpeg) bajo %LOCALAPPDATA%, si existe.
    """
    explicito = os.environ.get("FFMPEG_BIN_DIR", "").strip()
    if explicito:
        return explicito
    if shutil.which("ffmpeg"):
        return None
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
        for exe in sorted(base.glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"), reverse=True):
            return str(exe.parent)
    return None


def setup_ffmpeg_path() -> None:
    """Agrega al PATH el directorio de FFmpeg si hace falta (ver _ffmpeg_bin_dir)."""
    bin_dir = _ffmpeg_bin_dir()
    if bin_dir and bin_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


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
