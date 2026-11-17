"""
video_capture.py — Descarga video + extrae audio desde cualquier URL soportada por yt-dlp.

Uso interno:
    from captura.video_capture import download_video
    info = download_video(url, session_dir)
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from core.utils import setup_ffmpeg_path
setup_ffmpeg_path()


class DescargaError(RuntimeError):
    """
    Fallo de yt-dlp/ffmpeg. `reintentable` lo lee el orquestador de pasos (core/pasos.py):
    un video privado/eliminado o una URL no soportada no se arreglan reintentando; un corte
    de red, un 403 temporal o un "confirm you're not a bot" sí pueden.
    """

    def __init__(self, mensaje: str, reintentable: bool = True):
        super().__init__(mensaje)
        self.reintentable = reintentable


_PISTAS_NO_REINTENTABLES = (
    "private video", "video unavailable", "video is unavailable", "this video is private",
    "has been removed", "does not exist",
    "unsupported url", "is not a valid url", "http error 404", "video is not available",
    "account has been terminated", "members-only",
)


SUBPASOS_DESCARGA = [
    ("metadata", "Información del video"),
    ("video",    "Descarga del video"),
    ("audio",    "Extracción del audio"),
    ("duracion", "Verificación"),
]

# Progreso de yt-dlp en una línea parseable (--newline lo emite como líneas sueltas)
_PROGRESS_TEMPLATE = (
    "download:[PROG] %(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
    "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|"
    "%(progress.fragment_index)s|%(progress.fragment_count)s"
)


class _SinSubpasos:
    """Reporter nulo: download_video sin seguimiento (uso por terminal, tests)."""

    @contextmanager
    def paso(self, sid: str):
        yield

    def detalle(self, sid: str, texto) -> None:
        pass

    def progreso(self, sid: str, **campos) -> None:
        pass


def _num(valor: str) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None  # "NA" cuando yt-dlp todavía no lo sabe


def _parse_progreso(linea: str) -> dict | None:
    """
    '[PROG] bytes|total|estimado|velocidad|eta|fragmento|fragmentos' → dict, o None si no es
    una línea de progreso. Con HLS no hay total real y el estimado arranca igual a lo bajado
    (daría 100% al empezar): ahí el porcentaje sale de los fragmentos.
    """
    if not linea.startswith("[PROG] "):
        return None
    partes = linea[len("[PROG] "):].split("|")
    if len(partes) != 7:
        return None
    descargado, total, estimado, velocidad, eta, frag, frags = (_num(p) for p in partes)

    pct = None
    if descargado is not None and total:
        pct = descargado / total * 100
    elif frags:
        pct = (frag or 0) / frags * 100
        total = estimado if frag else None  # el estimado recién es razonable tras el 1er fragmento
    elif descargado is not None and estimado:
        pct, total = descargado / estimado * 100, estimado
    return {
        "bytes":     descargado,
        "total":     total,
        "velocidad": velocidad,
        "eta_s":     eta,
        "pct":       round(min(pct, 100), 1) if pct is not None else None,
    }


def _error_descarga(label: str, cmd: list[str], salida: str, codigo: int, elapsed: float) -> DescargaError:
    """La primera línea dice qué pasó (el último 'ERROR:' de la herramienta); debajo, el contexto."""
    lineas  = [l for l in salida.splitlines() if l.strip()]
    errores = [l for l in lineas if l.lstrip().startswith("ERROR")]
    causa   = (errores or lineas or [f"terminó con código {codigo}"])[-1].strip()
    return DescargaError(
        f"[{label}] {causa}\n"
        f"  falló (exit {codigo}, {elapsed:.1f}s)\n"
        f"  CMD : {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}\n"
        f"  LOG : {salida[-600:]}",
        reintentable=not any(p in salida.lower() for p in _PISTAS_NO_REINTENTABLES),
    )


def _run(cmd: list[str], label: str, on_linea=None) -> subprocess.CompletedProcess:
    """
    Corre cmd mostrando su salida en el log. `on_linea(linea) -> bool`: si devuelve True la
    línea ya fue consumida (progreso) y no se imprime ni se guarda.
    """
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
        if not linea or (on_linea and on_linea(linea)):
            continue
        print(f"    [{label}] {linea}")
        lineas.append(linea)

    proceso.wait()
    salida = "\n".join(lineas)
    elapsed = time.time() - t0

    if proceso.returncode != 0:
        raise _error_descarga(label, cmd, salida, proceso.returncode, elapsed)

    print(f"    [{label}] completado en {elapsed:.1f}s")
    return subprocess.CompletedProcess(cmd, proceso.returncode, salida, "")


def _leer_metadata(url: str, meta_path: Path) -> dict:
    """yt-dlp --dump-json: valida la URL antes de descargar (un video privado falla acá, en segundos)."""
    cmd = ["yt-dlp", "--dump-json", "--no-playlist", url]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not r.stdout.strip():
        raise _error_descarga("METADATA", cmd, r.stderr or r.stdout, r.returncode, time.time() - t0)
    try:
        meta = json.loads(r.stdout.strip().splitlines()[-1])
    except json.JSONDecodeError as e:
        raise DescargaError(f"[METADATA] yt-dlp devolvió metadata ilegible: {e}") from e
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _resumen_video(meta: dict) -> dict:
    """Lo mínimo para identificar la sesión en la web (metadata.json pesa cientos de KB)."""
    return {
        "titulo":     meta.get("title") or meta.get("fulltitle") or "",
        "canal":      meta.get("uploader") or meta.get("channel") or "",
        "duracion_s": meta.get("duration"),
        "miniatura":  meta.get("thumbnail"),
    }


def _fmt_mb(b: float | None) -> str:
    return f"{b / (1024 * 1024):.0f} MB" if b else "?"


def download_video(url: str, session_dir: Path, subpasos=None, on_metadata=None) -> dict:
    """
    Lee la metadata (valida la URL), descarga el video en ≤1080p, extrae el audio completo
    como mp3 y verifica la duración. `subpasos` (core/pasos.Subpasos con SUBPASOS_DESCARGA)
    recibe el avance de cada etapa; `on_metadata(resumen)` se llama apenas se conoce el video.

    Retorna:
        {
            "video_path":        Path,
            "audio_path":        Path,
            "duracion_segundos": float,
            "titulo":            str,
            "metadata_path":     Path,
        }
    """
    sub = subpasos or _SinSubpasos()
    session_dir.mkdir(parents=True, exist_ok=True)
    audio_dir  = session_dir / "audio"
    audio_dir.mkdir(exist_ok=True)

    video_path = session_dir / "stream_completo.mp4"
    audio_path = audio_dir   / "audio_completo.mp3"
    meta_path  = session_dir / "metadata.json"

    # ── 1. Metadata (antes de descargar: falla rápido con URLs malas) ──
    with sub.paso("metadata"):
        print("[VIDEO] Leyendo información del video...")
        resumen = _resumen_video(_leer_metadata(url, meta_path))
        if resumen["titulo"]:
            print(f"[VIDEO] Título: {resumen['titulo']}")
        sub.detalle("metadata", resumen["titulo"] or None)
        if on_metadata:
            on_metadata(resumen)
    duracion_meta = float(resumen["duracion_s"] or 0)

    # ── 2. Descargar video ───────────────────────────────────
    with sub.paso("video"):
        print("[VIDEO] Descargando video...")
        pistas = {"actual": 0, "total": None, "decil": -1}

        def _linea_video(linea: str) -> bool:
            prog = _parse_progreso(linea)
            if prog is None:
                if "Downloading" in linea and "format(s):" in linea:
                    pistas["total"] = len(linea.rsplit(":", 1)[1].strip().split("+"))
                elif linea.startswith("[download] Destination:"):
                    pistas["actual"] += 1
                    pistas["decil"] = -1
                return False
            sub.progreso("video", **prog, pista=pistas["actual"] or 1, pistas=pistas["total"])
            decil = int(prog["pct"] // 10) if prog["pct"] is not None else None
            if decil is not None and decil > pistas["decil"]:
                pistas["decil"] = decil
                print(f"    [VIDEO] pista {pistas['actual'] or 1}: {prog['pct']:.0f}% "
                      f"de {_fmt_mb(prog['total'])}")
            return True

        _run([
            "yt-dlp",
            # HLS (m3u8) primero: en YouTube los formatos https/DASH exigen PO Token
            # y cortan con 403 a los ~10 MB; HLS no. Fuentes sin HLS caen al resto.
            "-f", ("bv[protocol^=m3u8][height<=1080]+ba[protocol^=m3u8]"
                   "/bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]"
                   "/best[ext=mp4][height<=1080]/best"),
            "--concurrent-fragments", "4",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "--newline",
            "--progress-template", _PROGRESS_TEMPLATE,
            "--output", str(video_path),
            url,
        ], label="VIDEO", on_linea=_linea_video)

        size_mb = video_path.stat().st_size / (1024 * 1024)
        print(f"[VIDEO] ✅ {video_path.name} — {size_mb:.1f} MB")
        sub.detalle("video", f"{size_mb:.1f} MB")

    # ── 3. Extraer audio con ffmpeg (ya tenemos el video) ────
    with sub.paso("audio"):
        print("[VIDEO] Extrayendo audio...")

        def _linea_audio(linea: str) -> bool:
            clave, _, valor = linea.partition("=")
            if not _ or " " in clave:
                return False  # no es una línea key=value de -progress
            if clave == "out_time_us" and duracion_meta:
                seg = (_num(valor) or 0) / 1_000_000
                sub.progreso("audio", pct=round(min(seg / duracion_meta * 100, 100), 1))
            return True

        _run([
            "ffmpeg",
            "-i", str(video_path),
            "-vn", "-acodec", "libmp3lame", "-q:a", "5",
            "-progress", "pipe:1", "-nostats", "-loglevel", "error",
            "-y", str(audio_path),
        ], label="AUDIO", on_linea=_linea_audio)

        audio_mb = audio_path.stat().st_size / (1024 * 1024)
        print(f"[VIDEO] ✅ {audio_path.name} — {audio_mb:.1f} MB")
        sub.detalle("audio", f"{audio_mb:.1f} MB")

    # ── 4. Duración con ffprobe (la de la metadata como respaldo) ──
    with sub.paso("duracion"):
        dur = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True, text=True,
        )
        duracion = _num((dur.stdout or "").strip()) or duracion_meta
        print(f"[VIDEO] Duración: {duracion / 60:.1f} minutos ({duracion:.0f}s)")
        sub.detalle("duracion", f"{int(duracion // 60)} min {int(duracion % 60)} s")

    return {
        "video_path":        video_path,
        "audio_path":        audio_path,
        "duracion_segundos": duracion,
        "titulo":            resumen["titulo"],
        "metadata_path":     meta_path,
    }
