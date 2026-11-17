# Servidor de transcripción en Colab

`transcripcion_colab.ipynb` levanta en Google Colab (GPU T4 gratuita) un servidor que transcribe con **WhisperX**
(modelo `medium`, español por defecto, tiempos por palabra) y **diariza** con pyannote. Lo publica con un túnel
temporal de Cloudflare. El pipeline lo usa vía `COLAB_TRANSCRIBE_URL` (ver `legacy/transcripcion/video_transcriber.py`).

## Antes de la primera vez: Secrets de Colab

El notebook **no lleva claves escritas**. Se leen de los Secrets de Colab (icono de llave 🔑 en la barra lateral):

| Secret | Qué es |
|---|---|
| `HF_TOKEN` | Token de Hugging Face con acceso a `pyannote/speaker-diarization-community-1` |
| `AUTH_TOKEN` | Clave que protege el servidor; debe ser igual a `COLAB_AUTH_TOKEN` en `legacy/.env` |

Activar "Acceso del notebook" para ambos.

## Uso

1. Entorno de ejecución → Cambiar tipo → **GPU (T4)**.
2. Ejecutar las celdas 1, 2 y 3 en orden.
3. Copiar la URL `https://….trycloudflare.com` que imprime la celda 3 a `COLAB_TRANSCRIBE_URL` en `legacy/.env`
   (se relee en cada intento, no hace falta reiniciar el pipeline).

## API

- `POST /transcribe` (multipart `audio`, opcional `language`) → `202 {"job_id": …}`
- `GET /status/<job_id>` → `{"status": "processing" | "done" | "error", "segments": [...], "language": …}`
- Ambos requieren `Authorization: Bearer <AUTH_TOKEN>`.

## Limitaciones conocidas

- El túnel y la sesión de Colab son **efímeros**: al reiniciarse cambia la URL (riesgo R-05 del TO-BE).
- Colab gratuito tiene cupos de GPU variables.
