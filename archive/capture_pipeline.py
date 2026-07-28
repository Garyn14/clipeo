"""
===========================================
  IDEA MILLONARIA - Pipeline v1.1
  Captura + Transcripción + Análisis en Tiempo Real
===========================================

v1.1 — dos procesos en paralelo desde el inicio:
  Proceso A: yt-dlp graba video completo en background
             → stream_data/{session}/stream_completo.mp4
  Proceso B: yt-dlp extrae audio en chunks de 5 min
             → por cada chunk: Whisper → Agent1 → Agent2 → Agent3

Resultados en tiempo real por chunk.
Al Ctrl+C: espera chunk actual, corre Agent4, muestra resumen.

Uso:
  python capture_pipeline.py <url_tiktok_live>
  Detener con Ctrl+C
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

from core.utils import setup_ffmpeg_path
setup_ffmpeg_path()

import json
import time
import subprocess
import whisper
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from agent1_peak_detector import run_agent as agent1
from agent2_range_refiner  import run_agent as agent2
from agent3_viral_scorer   import run_agent as agent3
from agent4_video_cutter   import run_agent as agent4

# ─────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────
CHUNK_DURATION = 300          # segundos por chunk de audio (5 min)
OUTPUT_DIR     = "stream_data"
WHISPER_MODEL  = "base"
LANGUAGE       = "es"
VIDEO_FORMAT   = "best[ext=mp4][height<=480]"  # 480p: suficiente para TikTok
# ─────────────────────────────────────────


def setup_dirs(session_id: str) -> dict:
    base = Path(OUTPUT_DIR) / session_id
    dirs = {
        "base":   base,
        "audio":  base / "audio",
        "chunks": base / "chunks",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def start_video_recording(url: str, dirs: dict) -> subprocess.Popen:
    """Proceso A: graba el video completo en background. Retorna el Popen."""
    output_path = dirs["base"] / "stream_completo.mp4"
    cmd = [
        "yt-dlp", "--no-playlist",
        "-f", VIDEO_FORMAT,
        "--impersonate", "chrome",
        "--output", str(output_path),
        url,
    ]
    print(f"[VIDEO] Proceso A iniciado → {output_path.name}")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def download_chunk(url: str, chunk_index: int, dirs: dict) -> Path | None:
    """Proceso B: descarga un chunk de audio de {CHUNK_DURATION}s."""
    output_path = dirs["audio"] / f"chunk_{chunk_index:03d}.mp3"
    cmd = [
        "yt-dlp",
        "--no-playlist", "--extract-audio", "--audio-format", "mp3",
        "--audio-quality", "5",
        "--downloader", "ffmpeg",
        "--downloader-args", f"ffmpeg_i:-t {CHUNK_DURATION}",
        "--impersonate", "chrome",
        "--output", str(output_path),
        url,
    ]
    print(f"[CAPTURA] Grabando chunk_{chunk_index:03d}  ({CHUNK_DURATION//60} min)...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=CHUNK_DURATION + 60)
        if result.returncode == 0 and output_path.exists():
            size_mb = output_path.stat().st_size / (1024 * 1024)
            print(f"[CAPTURA] ✅ chunk_{chunk_index:03d}.mp3 — {size_mb:.1f} MB")
            return output_path
        else:
            print(f"[CAPTURA] ❌ Error en chunk_{chunk_index:03d}:\n{result.stderr}")
            return None
    except subprocess.TimeoutExpired:
        print(f"[CAPTURA] ⚠️  Timeout en chunk_{chunk_index:03d}")
        return None


def transcribe_to_dir(
    audio_path: Path, chunk_index: int, model, chunk_dir: Path
) -> Path | None:
    """
    Transcribe con Whisper y guarda en chunk_dir/transcripcion_completa.txt.
    Los timestamps son absolutos (offset = chunk_index × CHUNK_DURATION).
    """
    if audio_path.stat().st_size < 10 * 1024:
        print(f"[WHISPER] ⚠️  chunk_{chunk_index:03d} vacío o silencioso, saltando...")
        return None

    print(f"[WHISPER] Transcribiendo chunk_{chunk_index:03d}...")
    t0 = time.time()

    try:
        result = model.transcribe(
            str(audio_path), language=LANGUAGE, verbose=False, word_timestamps=False,
        )
    except Exception as e:
        print(f"[WHISPER] ❌ Error en chunk_{chunk_index:03d}: {e}")
        return None

    time_offset = chunk_index * CHUNK_DURATION
    out_path = chunk_dir / "transcripcion_completa.txt"

    with open(out_path, "w", encoding="utf-8") as f:
        for seg in result["segments"]:
            real_start = time_offset + seg["start"]
            ts = f"[{int(real_start // 60):02d}:{int(real_start % 60):02d}]"
            f.write(f"{ts} {seg['text'].strip()}\n")

    print(f"[WHISPER] ✅ chunk_{chunk_index:03d} transcrito en {time.time() - t0:.1f}s")
    return out_path


def append_candidatos(json_path: Path, new_items: list[dict]) -> None:
    """Agrega nuevos clips candidatos a clips_candidatos.json (crea si no existe)."""
    existing = []
    if json_path.exists():
        existing = json.loads(json_path.read_text(encoding="utf-8")).get("contenido", [])
    existing.extend(new_items)
    json_path.write_text(
        json.dumps({"contenido": existing}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def process_chunk(chunk_index: int, txt_path: Path) -> list[dict]:
    """
    Corre agent1→agent2→agent3 sobre la transcripción del chunk.
    Retorna los ítems con publicar=True.
    """
    peaks = agent1(str(txt_path))
    if not peaks:
        return []

    chunk_dir = txt_path.parent
    rangos = agent2(str(chunk_dir / "picos.json"))
    if not any(r.get("conservar") for r in rangos):
        return []

    contenido = agent3(str(chunk_dir / "rangos.json"))
    return [c for c in contenido if c.get("publicar")]


def run_pipeline(url: str) -> None:
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    dirs       = setup_dirs(session_id)

    print(f"\n{'=' * 54}")
    print(f"  IDEA MILLONARIA — Pipeline v1.1")
    print(f"  Session  : {session_id}")
    print(f"  URL      : {url}")
    print(f"  Whisper  : {WHISPER_MODEL}  |  Chunks : {CHUNK_DURATION // 60} min c/u")
    print(f"{'=' * 54}\n")

    print("[WHISPER] Cargando modelo (primera vez puede tardar)...")
    model = whisper.load_model(WHISPER_MODEL)
    print(f"[WHISPER] ✅ Modelo '{WHISPER_MODEL}' listo\n")

    # ── Proceso A: video completo en background ──────────────
    video_proc = start_video_recording(url, dirs)
    print(f"[VIDEO] ✅ Proceso A activo — grabando {dirs['base'] / 'stream_completo.mp4'}\n")

    # ── Proceso B: audio chunks + análisis en tiempo real ────
    chunk_index    = 0
    all_candidatos: list[dict] = []
    candidatos_json = dirs["base"] / "clips_candidatos.json"

    try:
        while True:
            print(f"\n{'─' * 54}")
            print(f"  CHUNK {chunk_index:03d}  (minuto {chunk_index * CHUNK_DURATION // 60}–"
                  f"{(chunk_index + 1) * CHUNK_DURATION // 60})")
            print(f"{'─' * 54}\n")

            audio_path = download_chunk(url, chunk_index, dirs)

            if audio_path:
                chunk_dir = dirs["chunks"] / f"chunk_{chunk_index:03d}"
                chunk_dir.mkdir(parents=True, exist_ok=True)

                txt_path = transcribe_to_dir(audio_path, chunk_index, model, chunk_dir)

                if txt_path:
                    candidatos = process_chunk(chunk_index, txt_path)
                    all_candidatos.extend(candidatos)

                    if candidatos:
                        append_candidatos(candidatos_json, candidatos)
                        n = len(candidatos)
                        s = "s" if n != 1 else ""
                        print(f"\n[CHUNK {chunk_index:03d}] ✅ {n} clip{s} candidato{s} encontrado{s}")
                    else:
                        print(f"\n[CHUNK {chunk_index:03d}] ⚠️  Sin momentos virales")
                else:
                    print(f"\n[CHUNK {chunk_index:03d}] ⚠️  Sin audio válido")
            else:
                print(f"\n[CHUNK {chunk_index:03d}] ❌ Error al descargar audio")

            chunk_index += 1
            print(f"\n[PIPELINE] Iniciando chunk siguiente...\n")
            time.sleep(2)

    except KeyboardInterrupt:
        print(f"\n\n[PIPELINE] ⛔ Detenido por el usuario")
        print("[PIPELINE] Esperando finalización del Proceso A (video)...")

        try:
            video_proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            video_proc.terminate()
            video_proc.wait()

        video_path = dirs["base"] / "stream_completo.mp4"
        minuto     = chunk_index * CHUNK_DURATION // 60

        print(f"[PIPELINE] Stream detenido en minuto ~{minuto}")
        print(f"[PIPELINE] Total clips candidatos : {len(all_candidatos)}")

        if video_path.exists():
            size_mb = video_path.stat().st_size / (1024 * 1024)
            print(f"[PIPELINE] Video completo         : {video_path.name}  ({size_mb:.1f} MB)")

        print(f"[PIPELINE] Listo para el Agente 4\n")

        if all_candidatos and video_path.exists():
            print("[PIPELINE] Corriendo Agente 4 — cortando clips...\n")
            agent4(str(candidatos_json))
        elif not all_candidatos:
            print("[PIPELINE] Sin clips candidatos — nada para cortar.")
        else:
            print("[PIPELINE] ⚠️  stream_completo.mp4 no disponible para cortar.")


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUso: python capture_pipeline.py <url_tiktok_live>")
        print("Ejemplo: python capture_pipeline.py https://www.tiktok.com/@usuario/live\n")
        sys.exit(1)

    run_pipeline(sys.argv[1])
