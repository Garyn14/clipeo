"""
video_transcriber.py — Transcribe audio con WhisperX + diarización de hablantes.

Uso interno:
    from transcripcion.video_transcriber import transcribe_full
    path = transcribe_full(audio_path, session_dir)

Requiere HF_TOKEN en .env para diarización de speakers.
Sin HF_TOKEN transcribe sin labels de speaker.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
import time
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

from core.utils import setup_ffmpeg_path
setup_ffmpeg_path()


def _transcribe_via_colab(audio_path: Path, timeout: int = 1800, poll_interval: int = 10) -> dict:
    """
    Envía el audio al endpoint remoto de Colab (patrón submit+poll, para evitar
    el timeout de 100s de Cloudflare) y devuelve {"segments": [...], "language": ...}
    Lanza RuntimeError con mensaje claro si algo falla — NUNCA cae a local silenciosamente.
    """
    url   = os.environ.get("COLAB_TRANSCRIBE_URL", "").strip()
    token = os.environ.get("COLAB_AUTH_TOKEN", "").strip()

    if not url:
        raise RuntimeError("COLAB_TRANSCRIBE_URL no configurada en .env — no se puede usar --colab")

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    print(f"[COLAB] Enviando audio ({size_mb:.1f} MB) a {url}...")

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    t0 = time.time()
    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                url,
                files={"audio": (audio_path.name, f)},
                headers=headers,
                timeout=120,
            )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        raise RuntimeError(
            f"Colab no respondió al envío en 120s — verifica que el notebook y el túnel estén activos"
        ) from e

    if response.status_code != 202:
        raise RuntimeError(
            f"Colab respondió con error {response.status_code}: {response.text}"
        )

    submit_data = response.json()
    job_id      = submit_data.get("job_id")
    if not job_id:
        raise RuntimeError("Colab no devolvió job_id")

    status_url = url.rsplit("/transcribe", 1)[0] + f"/status/{job_id}"
    print(f"[COLAB] Job {job_id} enviado — esperando resultado (polling cada {poll_interval}s)...")

    data = None
    while True:
        if time.time() - t0 > timeout:
            raise RuntimeError(
                f"Colab no terminó el job {job_id} en {timeout}s — timeout de polling"
            )

        time.sleep(poll_interval)

        try:
            status_response = requests.get(status_url, headers=headers, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            raise RuntimeError(
                f"Colab no respondió al consultar estado del job {job_id} — verifica el túnel"
            ) from e

        if status_response.status_code != 200:
            raise RuntimeError(
                f"Colab respondió con error {status_response.status_code} al consultar estado: {status_response.text}"
            )

        status_data = status_response.json()
        status      = status_data.get("status")

        if status == "done":
            data = status_data
            break
        elif status == "error":
            raise RuntimeError(status_data.get("error", "error desconocido en Colab"))
        elif status != "processing":
            raise RuntimeError(f"Colab devolvió un status desconocido: {status!r}")
        # status == "processing": seguir esperando

    t1 = time.time()

    t_total = t1 - t0
    t_proc  = data.get("processing_seconds")
    t_red   = t_total - t_proc if t_proc is not None else None

    print(
        f"[COLAB] Tiempo total: {t_total:.1f}s | Procesamiento GPU: "
        f"{t_proc:.1f}s | Red/subida+polling (estimado): {t_red:.1f}s"
        if t_proc is not None else
        f"[COLAB] Tiempo total: {t_total:.1f}s (notebook no reportó processing_seconds — "
        f"actualiza la celda del servidor para ver el desglose)"
    )

    return data


def transcribe_full(
    audio_path: Path,
    session_dir: Path,
    model_name: str = "base",
    language: str = "es",
) -> Path:
    """
    Transcribe audio con WhisperX.
    - Con HF_TOKEN en .env: diarización de hablantes → [MM:SS] SPEAKER_00: "texto"
    - Sin HF_TOKEN:         sin speakers             → [MM:SS] texto

    Guarda:
      - session_dir/transcripcion_raw.txt      (salida primaria)
      - session_dir/transcripcion_completa.txt (copia legacy para compatibilidad)

    Retorna Path a transcripcion_raw.txt.
    """
    try:
        import whisperx
    except ImportError as e:
        raise RuntimeError(
            f"WhisperX no está instalado: {e}\n"
            f"  pip install whisperx"
        ) from e

    hf_token     = os.environ.get("HF_TOKEN", "").strip()
    device       = "cpu"
    compute_type = "int8"   # float16 falla en CPU

    size_mb = audio_path.stat().st_size / (1024 * 1024)
    dur_min = size_mb / 1.0  # aprox 1 MB/min a ~128 kbps

    print(f"[WHISPERX] Cargando modelo '{model_name}'  (device={device}, compute={compute_type})...")
    t0    = time.time()
    model = whisperx.load_model(
        model_name, device,
        compute_type=compute_type,
        language=language,
    )
    print(f"[WHISPERX] ✅ Modelo listo  ({time.time()-t0:.1f}s)")

    print(f"[WHISPERX] Transcribiendo {size_mb:.1f} MB de audio (~{dur_min:.0f} min)...")
    audio  = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=4, language=language)
    del model

    t_transcribe = time.time() - t0
    print(f"[WHISPERX] ✅ Transcripción base en {t_transcribe:.1f}s")

    # ── Alineación de palabras ──────────────────────────────────
    try:
        print("[WHISPERX] Alineando palabras...")
        model_a, metadata = whisperx.load_align_model(
            language_code=result.get("language", language),
            device=device,
        )
        result = whisperx.align(
            result["segments"], model_a, metadata, audio, device,
            return_char_alignments=False,
        )
        del model_a
        print(f"[WHISPERX] ✅ Alineación completa")
    except Exception as e:
        print(f"[WHISPERX] ⚠ Alineación omitida: {e}")

    # ── Diarización de hablantes ────────────────────────────────
    diarized = False
    if hf_token:
        try:
            print("[WHISPERX] Diarizando hablantes (HF_TOKEN encontrado)...")
            from whisperx.diarize import DiarizationPipeline
            diarize_model    = DiarizationPipeline(
                token=hf_token, device=device,
            )
            diarize_segments = diarize_model(audio)
            result           = whisperx.assign_word_speakers(diarize_segments, result)
            diarized         = True
            print("[WHISPERX] ✅ Diarización completa")
        except Exception as e:
            print(f"[WHISPERX] ⚠ Diarización fallida: {e}")
            print("[WHISPERX]   Continuando sin labels de speaker.")
    else:
        print("[WHISPERX] ⚠ HF_TOKEN no encontrado — sin diarización de hablantes")
        print("[WHISPERX]   Agrega HF_TOKEN=hf_xxx en .env para activarla.")

    # ── Escribir transcripcion_raw.txt ──────────────────────────
    raw_path   = session_dir / "transcripcion_raw.txt"
    word_count = 0

    with open(raw_path, "w", encoding="utf-8") as f:
        for seg in result["segments"]:
            start   = seg.get("start", 0)
            minutes = int(start // 60)
            seconds = int(start % 60)
            ts      = f"[{minutes:02d}:{seconds:02d}]"
            text    = seg.get("text", "").strip()
            if not text:
                continue

            if diarized:
                speaker = seg.get("speaker", "SPEAKER_??")
                f.write(f'{ts} {speaker}: "{text}"\n')
            else:
                f.write(f"{ts} {text}\n")

            word_count += len(text.split())

    # Copia legacy — mantiene compatibilidad con modo --test
    legacy = session_dir / "transcripcion_completa.txt"
    legacy.write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")

    total = time.time() - t0
    print(f"[WHISPERX] ✅ {word_count:,} palabras en {total:.1f}s")
    print(f"[WHISPERX] Diarización: {'sí (SPEAKER_XX)' if diarized else 'no'}")
    print(f"[WHISPERX] Guardado en: {raw_path}")

    return raw_path


def transcribe_chunk(
    audio_path: Path,
    chunk_dir: Path,
    chunk_id: str,
    offset_segundos: int,
    model_name: str = "base",
    language: str = "es",
    usar_colab: bool = False,
) -> Path:
    """
    Transcribe un fragmento de audio y ajusta los timestamps con offset_segundos
    para que reflejen el tiempo real en el video original.

    Guarda:
      chunk_dir/transcripcion_raw.txt      (timestamps reales)
      chunk_dir/transcripcion_completa.txt (copia para compat. con agent2/3)

    Retorna Path a transcripcion_completa.txt.
    """
    if usar_colab:
        data     = _transcribe_via_colab(audio_path)
        segments = data.get("segments", [])

        chunk_dir.mkdir(parents=True, exist_ok=True)
        raw_path   = chunk_dir / "transcripcion_raw.txt"
        word_count = 0

        with open(raw_path, "w", encoding="utf-8") as f:
            for seg in segments:
                real_start = seg.get("start", 0) + offset_segundos
                minutes    = int(real_start // 60)
                seconds    = int(real_start % 60)
                ts         = f"[{minutes:02d}:{seconds:02d}]"
                text       = seg.get("text", "").strip()
                if not text:
                    continue

                speaker = seg.get("speaker")
                if speaker:
                    f.write(f'{ts} {speaker}: "{text}"\n')
                else:
                    f.write(f"{ts} {text}\n")

                word_count += len(text.split())

        # Copia como transcripcion_completa.txt para compatibilidad con agent2/3
        out_path = chunk_dir / "transcripcion_completa.txt"
        out_path.write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")

        print(f"[COLAB] [{chunk_id}] ✅ {word_count:,} palabras  (offset +{offset_segundos}s)")

        return out_path

    try:
        import whisperx
    except ImportError as e:
        raise RuntimeError(
            f"WhisperX no está instalado: {e}\n  pip install whisperx"
        ) from e

    hf_token     = os.environ.get("HF_TOKEN", "").strip()
    device       = "cpu"
    compute_type = "int8"

    size_mb  = audio_path.stat().st_size / (1024 * 1024)
    dur_min  = size_mb / 1.0

    print(f"[WHISPERX] [{chunk_id}] Cargando modelo '{model_name}'...")
    import time
    t0    = time.time()
    model = whisperx.load_model(
        model_name, device,
        compute_type=compute_type,
        language=language,
    )

    print(f"[WHISPERX] [{chunk_id}] Transcribiendo {size_mb:.1f} MB (~{dur_min:.0f} min)...")
    audio  = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=4, language=language)
    del model

    # Alineación
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=result.get("language", language),
            device=device,
        )
        result = whisperx.align(
            result["segments"], model_a, metadata, audio, device,
            return_char_alignments=False,
        )
        del model_a
    except Exception as e:
        print(f"[WHISPERX] [{chunk_id}] ⚠ Alineación omitida: {e}")

    # Diarización (opcional)
    diarized = False
    if hf_token:
        try:
            from whisperx.diarize import DiarizationPipeline
            diarize_model    = DiarizationPipeline(token=hf_token, device=device)
            diarize_segments = diarize_model(audio)
            result           = whisperx.assign_word_speakers(diarize_segments, result)
            diarized         = True
        except Exception as e:
            print(f"[WHISPERX] [{chunk_id}] ⚠ Diarización omitida: {e}")

    # Escribir con timestamps ajustados por offset
    chunk_dir.mkdir(parents=True, exist_ok=True)
    raw_path   = chunk_dir / "transcripcion_raw.txt"
    word_count = 0

    with open(raw_path, "w", encoding="utf-8") as f:
        for seg in result["segments"]:
            real_start = seg.get("start", 0) + offset_segundos
            minutes    = int(real_start // 60)
            seconds    = int(real_start % 60)
            ts         = f"[{minutes:02d}:{seconds:02d}]"
            text       = seg.get("text", "").strip()
            if not text:
                continue

            if diarized:
                speaker = seg.get("speaker", "SPEAKER_??")
                f.write(f'{ts} {speaker}: "{text}"\n')
            else:
                f.write(f"{ts} {text}\n")

            word_count += len(text.split())

    # Copia como transcripcion_completa.txt para compatibilidad con agent2/3
    out_path = chunk_dir / "transcripcion_completa.txt"
    out_path.write_text(raw_path.read_text(encoding="utf-8"), encoding="utf-8")

    total = time.time() - t0
    print(f"[WHISPERX] [{chunk_id}] ✅ {word_count:,} palabras en {total:.1f}s  (offset +{offset_segundos}s)")

    return out_path
