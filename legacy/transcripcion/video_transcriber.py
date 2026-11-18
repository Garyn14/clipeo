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

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
from dotenv import dotenv_values, load_dotenv
import requests

load_dotenv()

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"          # legacy/.env
_ENV_PATH_RAIZ = Path(__file__).resolve().parents[2] / ".env"     # .env de la raíz del repo (CLIP-39)

from core.utils import setup_ffmpeg_path
setup_ffmpeg_path()


class ColabError(RuntimeError):
    """
    Fallo de la transcripción remota. `reintentable` lo lee el orquestador de pasos
    (core/pasos.py): túnel caído, timeouts o 5xx se reintentan solos; falta de URL o
    rechazo de auth (4xx) requieren corregir .env antes.
    """

    def __init__(self, mensaje: str, reintentable: bool = True):
        super().__init__(mensaje)
        self.reintentable = reintentable


def _write_word_timings(segments: list, dest_path: Path, offset_segundos: float = 0) -> int:
    """
    Persiste los timestamps por palabra que whisperx.align() ya calcula en
    result["segments"][i]["words"] pero que el .txt de salida (a nivel de
    segmento) descarta — necesarios para subtítulos animados palabra por
    palabra en edicion_video/agent4_video_cutter.py.

    Solo incluye palabras con start/end reales (whisperx a veces deja
    palabras sin alinear, ej. números o tokens raros — se omiten en vez de
    inventar un timestamp). offset_segundos ajusta a tiempo real del video
    completo, igual que ya hacen los timestamps de segmento en transcribe_chunk.

    Retorna la cantidad de palabras escritas (0 si no hay alineación disponible
    — no es un error, algunas transcripciones no logran alinear nada).
    """
    palabras = []
    for seg in segments:
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            palabras.append({
                "word":  w.get("word", "").strip(),
                "start": round(w["start"] + offset_segundos, 3),
                "end":   round(w["end"] + offset_segundos, 3),
            })
    dest_path.write_text(json.dumps(palabras, ensure_ascii=False), encoding="utf-8")
    return len(palabras)


def _status_reintentable(status_code: int) -> bool:
    # 401/403: token incorrecto; 404: URL vieja de otro túnel... salvo 408/429, un 4xx no
    # se arregla reintentando. Cloudflare devuelve 5xx/530 cuando el túnel está caído.
    return status_code >= 500 or status_code in (408, 429)


def _normalizar_url_colab(url: str) -> str:
    # Acepta la URL del túnel tal cual la muestra Colab, con o sin /transcribe.
    url = url.strip().rstrip("/")
    if url and not url.endswith("/transcribe"):
        url += "/transcribe"
    return url


def _colab_config() -> tuple[str, str]:
    """
    (url, token) de Colab leídos de .env en CADA llamada: el túnel cambia con cada
    reinicio del notebook, y así el siguiente reintento de una corrida en curso
    toma la URL nueva sin relanzar. El archivo gana sobre os.environ (que quedó
    con el valor del arranque); sin valor en el archivo, cae a os.environ.
    Se leen legacy/.env y el .env de la raíz del repo, en ese orden (CLIP-39: en la
    laptop del operador el .env vive en la raíz).
    """
    archivos = [dotenv_values(p) for p in (_ENV_PATH, _ENV_PATH_RAIZ) if p.exists()]

    def _valor(clave: str) -> str:
        for archivo in archivos:
            if archivo.get(clave):
                return archivo[clave].strip()
        return os.environ.get(clave, "").strip()

    return _normalizar_url_colab(_valor("COLAB_TRANSCRIBE_URL")), _valor("COLAB_AUTH_TOKEN")


def _transcribe_via_colab(
    audio_path: Path, timeout: int = 1800, poll_interval: int = 10, language: str = "es",
) -> dict:
    """
    Envía el audio al endpoint remoto de Colab (patrón submit+poll, para evitar
    el timeout de 100s de Cloudflare) y devuelve {"segments": [...], "language": ...}
    Lanza RuntimeError con mensaje claro si algo falla — NUNCA cae a local silenciosamente.
    """
    url, token = _colab_config()

    if not url:
        raise ColabError(
            "COLAB_TRANSCRIBE_URL no configurada en .env — no se puede usar --colab",
            reintentable=False,
        )

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
                # Sin idioma, WhisperX lo adivina con los primeros segundos y puede
                # transcribir español como italiano (pasó en 20261002_215006)
                data={"language": language},
                headers=headers,
                timeout=120,
            )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        raise ColabError(
            f"Colab ({urlparse(url).netloc}) no respondió al envío en 120s — verifica que "
            f"el notebook y el túnel estén activos y que COLAB_TRANSCRIBE_URL sea la actual"
        ) from e

    if response.status_code != 202:
        raise ColabError(
            f"Colab respondió con error {response.status_code}: {response.text}",
            reintentable=_status_reintentable(response.status_code),
        )

    submit_data = response.json()
    job_id      = submit_data.get("job_id")
    if not job_id:
        raise ColabError("Colab no devolvió job_id")

    status_url = url.rsplit("/transcribe", 1)[0] + f"/status/{job_id}"
    print(f"[COLAB] Job {job_id} enviado — esperando resultado (polling cada {poll_interval}s)...")

    data = None
    while True:
        if time.time() - t0 > timeout:
            raise ColabError(
                f"Colab no terminó el job {job_id} en {timeout}s — timeout de polling"
            )

        time.sleep(poll_interval)

        try:
            status_response = requests.get(status_url, headers=headers, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            raise ColabError(
                f"Colab no respondió al consultar estado del job {job_id} — verifica el túnel"
            ) from e

        if status_response.status_code != 200:
            raise ColabError(
                f"Colab respondió con error {status_response.status_code} al consultar estado: {status_response.text}",
                reintentable=_status_reintentable(status_response.status_code),
            )

        status_data = status_response.json()
        status      = status_data.get("status")

        if status == "done":
            data = status_data
            detectado = (data.get("language") or "").lower()
            if detectado and detectado != language:
                # Seguir con texto en otro idioma arruina en cascada A0–A3: mejor frenar acá
                raise ColabError(
                    f"Colab transcribió en '{detectado}' en vez de '{language}' — revisa que el "
                    f"notebook use el idioma que manda el pipeline",
                    reintentable=False,
                )
            break
        elif status == "error":
            raise ColabError(status_data.get("error", "error desconocido en Colab"))
        elif status != "processing":
            raise ColabError(f"Colab devolvió un status desconocido: {status!r}")
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
      - session_dir/palabras.json               (timestamps por palabra, para
                                                   subtítulos animados en Agente 4)

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

    # Timestamps por palabra (para subtítulos animados en Agente 4)
    palabras_path  = session_dir / "palabras.json"
    n_palabras_ts  = _write_word_timings(result["segments"], palabras_path)

    total = time.time() - t0
    print(f"[WHISPERX] ✅ {word_count:,} palabras en {total:.1f}s")
    print(f"[WHISPERX] Diarización: {'sí (SPEAKER_XX)' if diarized else 'no'}")
    print(f"[WHISPERX] Timestamps por palabra: {n_palabras_ts:,} (palabras.json)")
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
        data     = _transcribe_via_colab(audio_path, language=language)
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

        # Timestamps por palabra — solo si el notebook de Colab ya los incluye
        # en la respuesta (no verificable desde este repo, ver docs/COMANDOS.md
        # o el plan de la Fase 3: el servidor remoto necesita su propio
        # whisperx.align() para devolver "words" por segmento). Si no vienen,
        # simplemente no habrá subtítulos animados para esta sesión — no falla.
        n_palabras_ts = _write_word_timings(segments, chunk_dir / "palabras.json", offset_segundos)
        if n_palabras_ts:
            print(f"[COLAB] [{chunk_id}] Timestamps por palabra: {n_palabras_ts:,} (palabras.json)")

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

    # Timestamps por palabra (para subtítulos animados en Agente 4)
    n_palabras_ts = _write_word_timings(
        result["segments"], chunk_dir / "palabras.json", offset_segundos
    )

    total = time.time() - t0
    print(f"[WHISPERX] [{chunk_id}] ✅ {word_count:,} palabras en {total:.1f}s  (offset +{offset_segundos}s)")
    print(f"[WHISPERX] [{chunk_id}] Timestamps por palabra: {n_palabras_ts:,} (palabras.json)")

    return out_path
