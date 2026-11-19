"""
servidor.py — Servidor de transcripción remota en Colab (CLIP-65).

Lo lanza `arrancar.py` en un proceso de Python NUEVO: así toma las librerías recién instaladas (numpy, whisperx)
sin reiniciar la sesión de Colab. Secrets por variables de entorno (las pasa arrancar.py desde los Secrets de Colab):
  HF_TOKEN    token de Hugging Face (diarización pyannote)
  AUTH_TOKEN  clave del servidor; debe ser igual a COLAB_AUTH_TOKEN del .env

API (sin cambios respecto del notebook anterior):
  POST /transcribe  (multipart "audio", opcional "language") → 202 {"job_id"}
  GET  /status/<id> → {"status": "processing" | "done" | "error", "segments", "language"}
Imprime la línea "SERVIDOR_LISTO" cuando acepta pedidos.
"""

import os
import tempfile
import threading
import time
import uuid

import pandas as pd
import torch
import torchaudio
import whisperx
from flask import Flask, jsonify, request
from huggingface_hub import login
from pyannote.audio import Pipeline as DiarizationPipeline

HF_TOKEN = os.environ.get("HF_TOKEN")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
if not AUTH_TOKEN:
    raise SystemExit("Falta AUTH_TOKEN: sin clave el servidor quedaría abierto a cualquiera")

MODEL_NAME = os.environ.get("MODELO_WHISPER", "medium")
IDIOMA_DEFECTO = "es"          # si el pipeline no manda idioma, se usa este (no se adivina)
PUERTO = int(os.environ.get("PUERTO", "5000"))
device = "cuda"

if HF_TOKEN:
    login(token=HF_TOKEN)

print(f"ETAPA modelo: cargando '{MODEL_NAME}' en GPU", flush=True)
model = whisperx.load_model(MODEL_NAME, device=device, compute_type="float16")

# Un modelo de alineación por idioma, cargado a demanda (español ya precargado)
align_models = {IDIOMA_DEFECTO: whisperx.load_align_model(language_code=IDIOMA_DEFECTO, device=device)}
align_lock = threading.Lock()


def _align_model(lang):
    with align_lock:
        if lang not in align_models:
            print(f"[SERVER] Cargando modelo de alineación para '{lang}'...", flush=True)
            align_models[lang] = whisperx.load_align_model(language_code=lang, device=device)
        return align_models[lang]


print("ETAPA diarizacion: cargando pyannote", flush=True)
diarize_model = DiarizationPipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1", token=HF_TOKEN
).to(torch.device(device))

app = Flask(__name__)
jobs = {}
jobs_lock = threading.Lock()


def _process_job(job_id, tmp_path, language):
    try:
        t0 = time.time()
        audio = whisperx.load_audio(tmp_path)
        # Idioma fijo: sin esto WhisperX lo adivina con los primeros segundos (y puede equivocarse)
        result = model.transcribe(audio, batch_size=16, language=language)
        idioma = result.get("language") or language   # guardarlo ANTES de align (align lo pierde)

        model_a, metadata = _align_model(idioma)
        result = whisperx.align(result["segments"], model_a, metadata, audio, device, return_char_alignments=False)

        waveform, sample_rate = torchaudio.load(tmp_path)
        raw_output = diarize_model({"waveform": waveform, "sample_rate": sample_rate})
        # pyannote 4.x devuelve un contenedor: convertirlo a DataFrame
        diarization = raw_output.speaker_diarization if hasattr(raw_output, "speaker_diarization") else raw_output
        diarize_df = pd.DataFrame(diarization.itertracks(yield_label=True), columns=["segment", "label", "speaker"])
        diarize_df["start"] = diarize_df["segment"].apply(lambda x: x.start)
        diarize_df["end"] = diarize_df["segment"].apply(lambda x: x.end)
        try:
            result = whisperx.assign_word_speakers(diarize_df, result)
            print(f"[SERVER] Job {job_id}: diarización OK ({len(diarize_df)} tracks)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[SERVER] Job {job_id}: assign_word_speakers falló: {type(e).__name__}: {e}", flush=True)

        segments_out = [
            {
                "start": float(seg.get("start", 0)),
                "text": seg.get("text", "").strip(),
                "speaker": seg.get("speaker"),
                # Tiempos por palabra: el pipeline los usa para los subtítulos animados
                "words": [
                    {"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
                    for w in seg.get("words", []) if "start" in w and "end" in w
                ],
            }
            for seg in result["segments"] if seg.get("text", "").strip()
        ]
        proc_time = round(time.time() - t0, 1)
        print(f"[SERVER] Job {job_id}: {len(segments_out)} segmentos en {proc_time}s (idioma: {idioma})", flush=True)
        with jobs_lock:
            jobs[job_id] = {"status": "done", "segments": segments_out, "language": idioma,
                            "processing_seconds": proc_time}
    except Exception as e:  # noqa: BLE001
        print(f"[SERVER] Job {job_id} falló: {e}", flush=True)
        with jobs_lock:
            jobs[job_id] = {"status": "error", "error": str(e)}
    finally:
        os.remove(tmp_path)


def _autorizado():
    return request.headers.get("Authorization") == f"Bearer {AUTH_TOKEN}"


@app.route("/transcribe", methods=["POST"])
def transcribe():
    if not _autorizado():
        return jsonify({"error": "unauthorized"}), 401
    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "falta el archivo 'audio'"}), 400
    language = (request.form.get("language") or IDIOMA_DEFECTO).strip().lower()
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"status": "processing"}
    threading.Thread(target=_process_job, args=(job_id, tmp_path, language), daemon=True).start()
    print(f"[SERVER] Job {job_id} recibido (idioma: {language})", flush=True)
    return jsonify({"job_id": job_id}), 202


@app.route("/status/<job_id>", methods=["GET"])
def status(job_id):
    if not _autorizado():
        return jsonify({"error": "unauthorized"}), 401
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "job_id no encontrado"}), 404
    return jsonify(job)


if __name__ == "__main__":
    threading.Timer(1.5, lambda: print("SERVIDOR_LISTO", flush=True)).start()
    app.run(port=PUERTO)
