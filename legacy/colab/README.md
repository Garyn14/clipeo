# Servidor de transcripción en Colab

`transcripcion_colab.ipynb` levanta en Google Colab (GPU T4 gratuita) un servidor que transcribe con **WhisperX**
(modelo `medium`, español por defecto, tiempos por palabra) y **diariza** con pyannote. Lo publica con un túnel
temporal de Cloudflare. El pipeline lo usa vía `COLAB_TRANSCRIBE_URL` (ver `legacy/transcripcion/video_transcriber.py`).

## Antes de la primera vez: Secrets de Colab

El notebook **no lleva claves escritas**. Se leen de los Secrets de Colab (icono de llave 🔑 en la barra lateral):

| Secret | Qué es |
|---|---|
| `HF_TOKEN` | Token de Hugging Face con acceso a `pyannote/speaker-diarization-community-1` |
| `AUTH_TOKEN` (o `COLAB_AUTH_TOKEN`) | Clave que protege el servidor; debe ser igual a `COLAB_AUTH_TOKEN` del `.env`. Si falta, la celda 3 se detiene (no levanta un servidor abierto) |

Activar "Acceso del notebook" para ambos.

## Uso (CLIP-65: un solo paso)

1. Entorno de ejecución → Cambiar tipo → **GPU (T4)**.
2. Ejecutar la **única celda** (o "Ejecutar todas"). Muestra una barra por etapas — GPU → instalar → cloudflared →
   modelos → túnel — con tiempo transcurrido y estimación. No hay que reiniciar la sesión: `arrancar.py` lanza
   `servidor.py` en un proceso nuevo.
3. Al final imprime `URL_TUNEL=https://….trycloudflare.com`: copiarla a `COLAB_TRANSCRIBE_URL` en el `.env`
   (se relee en cada intento, no hace falta reiniciar el pipeline). Claude lo hace solo (`docs/CUENTAS.md`).
4. **Al terminar de procesar, finalizar la sesión** (Entorno de ejecución → Desconectar y eliminar). Una sesión
   olvidada sigue gastando el cupo diario de GPU gratuita.

El notebook de cada cuenta puede ser solo esa celda (no hace falta abrirlo desde GitHub). Volver a ejecutarla
reemplaza el servidor anterior. Si una etapa falla, la barra lo dice y muestra las últimas líneas del log
(`/content/instalacion.log`, `servidor.log`, `tunel.log`).

### Versiones

`arrancar.py` instala con `uv` y **versiones exactas** (`PAQUETES`): `whisperx==3.8.6` (trae pyannote 4, necesario
para `speaker-diarization-community-1`), `torch==2.8.0`, `torchaudio==2.8.0`, `torchvision==0.23.0`, `numpy==2.2.6`.
No se puede usar el torch que trae Colab (2.14 en 2026-11): con él solo resuelve whisperx 3.7.x + pyannote 3.x, que
falla con el torchaudio nuevo. Medido el 2026-11-19 en una sesión nueva: **listo en 2:30** (antes 6 a 20+ minutos);
transcripción de 45 s de prueba en 12 s con palabras y diarización. Para actualizar: cambiar el bloque `PAQUETES`
completo, probar en Colab y anotar aquí la medición.

## API

- `POST /transcribe` (multipart `audio`, opcional `language`) → `202 {"job_id": …}`
- `GET /status/<job_id>` → `{"status": "processing" | "done" | "error", "segments": [...], "language": …}`
- Ambos requieren `Authorization: Bearer <AUTH_TOKEN>`.

## Limitaciones conocidas

- El túnel y la sesión de Colab son **efímeros**: al reiniciarse cambia la URL (riesgo R-05 del TO-BE).
- Colab gratuito tiene cupos de GPU variables.
