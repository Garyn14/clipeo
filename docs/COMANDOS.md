# Comandos del Pipeline

Referencia de todos los comandos disponibles hoy en el proyecto, con ejemplos. Para entender qué hace cada etapa internamente ver [ARQUITECTURA.md](ARQUITECTURA.md); para el formato de los archivos que estos comandos leen/escriben ver [ESTRUCTURA_DATOS.md](ESTRUCTURA_DATOS.md).

Todos los comandos se ejecutan desde la raíz del proyecto y requieren `.env` con `ANTHROPIC_API_KEY` (todos los que llaman a Claude) y opcionalmente `HF_TOKEN` (diarización de hablantes).

---

## 1. Flujo principal

### 1.1 Capturar un TikTok Live en curso

`captura/tiktok_capture.py` **solo graba** — no transcribe ni analiza. Corta el live en archivos `.mp4` de duración fija mientras esté activo.

```bash
# Grabar con el tamaño de chunk por defecto (30 min)
python captura/tiktok_capture.py --usuario @fritzsport

# Grabar en chunks de 1 minuto (pruebas rápidas)
python captura/tiktok_capture.py --usuario fritzsport --chunk 1m

# Grabar en chunks de 2 horas
python captura/tiktok_capture.py --usuario @fritzsport --chunk 2h
```

- El `@` es opcional, se normaliza igual.
- `--chunk` acepta `Ns` / `Nm` / `Nh` (ej. `90s`, `30m`, `2h`); sin unidad se interpreta como segundos.
- Verifica que el live esté activo antes de grabar; si no lo está, termina con error.
- Ctrl+C detiene la grabación de forma segura (mata el árbol de procesos yt-dlp+ffmpeg) y deja registrado el progreso en `captura_estado.json`.
- Al terminar cada chunk imprime el comando exacto de `pipeline.py --video` para procesarlo.

### 1.2 Procesar un video (el comando principal del sistema)

```bash
# Video/URL remoto, config por defecto
python pipeline.py --video https://www.tiktok.com/@fritzsport/video/123456789

# Con config de nicho/ecosistema específico
python pipeline.py --video https://www.tiktok.com/@fritzsport/video/123456789 --config zapatillas_peru
python pipeline.py --video https://kick.com/sideral --config streamers_peru

# Procesar un chunk grabado localmente por captura/tiktok_capture.py
python pipeline.py --video "stream_data/tiktok_fritzsport_20260705_120000/chunk_001.mp4" --config zapatillas_peru

# Con revisión manual antes de cortar cada clip
python pipeline.py --video https://www.tiktok.com/@fritzsport/video/123456789 --config zapatillas_peru --revisar
```

- Si la URL/archivo ya fue procesado antes (misma URL registrada en algún `pipeline_estado.json`), pregunta si querés retomar esa sesión en vez de volver a descargar.
- Si el proceso se corta (Ctrl+C o error), el chunk en curso queda pendiente y la próxima ejecución con la misma URL retoma desde ahí — no reprocesa chunks ya completados.
- `--config` es el `canal_id`: puede resolver a un nicho del Módulo Contexto v2 (`contexto/nichos/<id>.yaml`), a un archivo único v1 (`config/<id>.yaml`) o a un ecosistema v1 (`config/<id>/`). Ver ESTRUCTURA_DATOS.md.
- Omitiendo `--config` se usa `config/default.yaml` (prompt genérico, sin lore de personajes).

### 1.3 Reprocesar una sesión ya transcrita (modo test)

Salta descarga/transcripción y corre los agentes 1→4 directo sobre una transcripción existente. Útil para iterar sobre prompts/config sin gastar tiempo/dinero en volver a transcribir.

```bash
python pipeline.py --test stream_data/test/ --config zapatillas_peru
python pipeline.py --test stream_data/20260704_170532/ --config zapatillas_peru --revisar
```

- Requiere que exista `transcripcion_completa.txt` dentro del directorio dado.
- No usa `ChunkManager` — procesa todo el archivo como una sola unidad.

### 1.4 Modo live directo (⚠ actualmente no funcional)

```bash
python pipeline.py --live https://www.tiktok.com/@fritzsport/live --config zapatillas_peru
```

Este modo delega a un `capture_pipeline.py` en la raíz que **ya no existe** (fue archivado en `archive/capture_pipeline.py`). No lo uses — en su lugar combiná 1.1 + 1.2 (`captura/tiktok_capture.py` para grabar, `pipeline.py --video` para procesar cada chunk).

---

## 2. Herramientas complementarias

### 2.1 Dar feedback humano sobre clips generados

Recorre los clips de una sesión, pide tu evaluación por clip, y usa Claude para destilar ese feedback en reglas que el Agente 3 reutilizará en publicaciones futuras del mismo canal.

```bash
python contexto/feedback.py --session 20260704_170532
```

- `--session` es el nombre del directorio dentro de `stream_data/` (no la ruta completa).
- Detecta el `canal_id` automáticamente desde `pipeline_estado.json`; si no puede, lo pide por teclado.
- Es interactivo: por cada clip pregunta si querés darle feedback, tu score 1-10, la razón, y opcionalmente un título alternativo.
- Al final te muestra la propuesta de aprendizaje generada por Claude y pide aprobación antes de guardarla en `aprendizajes/<canal_id>.md` y, si es generalizable, en `aprendizajes/<canal_id>_optimizado.md`.

### 2.2 Cortar un clip manual puntual

Corta un rango de tiempo arbitrario del video de una sesión, con o sin texto quemado, sin pasar por los Agentes 1-3 ni por `contenido.json`. Útil para un momento que viste vos mismo y el sistema no detectó.

```bash
python entrenamiento/clip_manual.py \
  --video "stream_data/20260704_170532/stream_completo.mp4" \
  --inicio 00:14:22 --fin 00:15:40 \
  --linea1 "Fritz reta a Yolu en vivo" \
  --linea2 "por el número uno del Perú 🔥" \
  --config zapatillas_peru

# Sin texto (clip limpio)
python entrenamiento/clip_manual.py \
  --video "stream_data/20260704_170532/stream_completo.mp4" \
  --inicio 00:14:22 --fin 00:15:40
```

- El clip queda en `stream_data/<session>/clips_custom/`, numerado por timestamp (`custom_YYYYMMDD_HHMMSS.mp4`), junto a su `.json` de metadata con `creado_manual: true`.
- `--config` aquí solo se guarda como referencia en la metadata — no cambia el corte ni el texto (no llama a Claude).

### 2.3 Buscar noticias recientes de un personaje (refrescar contexto)

Solo aplica a entidades del Módulo Contexto v2 (`contexto/entidades/`). Usa la búsqueda web nativa de Claude para encontrar novedades recientes y, tras tu aprobación, las guarda como eventos de contexto.

```bash
python contexto/contexto_refresh.py fritz
python contexto/contexto_refresh.py sideral --max-busquedas 8
```

- El primer argumento es el `id` de la entidad (nombre del archivo en `contexto/entidades/<id>.yaml`, sin extensión).
- `--max-busquedas` limita cuántas búsquedas web puede hacer Claude en esa corrida (default 3).
- Por cada hallazgo pregunta `[S/n]` antes de guardarlo en `contexto/eventos/<YYYY-MM>/refresh_<entidad>_<hora>.yaml`.

---

## 3. Ejecución individual de agentes (debug / desarrollo)

Cada agente puede correrse aislado apuntándolo al JSON/txt que produce la etapa anterior — útil para iterar sobre un prompt sin repetir todo el pipeline. Todos aceptan opcionalmente un `canal_id` como último argumento (default: `config/default.yaml`); todos usan `ConfigLoader` (v1) cuando se invocan así, no `ContextLoader`.

```bash
# Agente 0 — identificación de hablantes (requiere transcripción con diarización)
python agentes/agent0_speaker_identifier.py stream_data/<session>/transcripcion_raw.txt stream_data/<session>/metadata.json

# Agente 1 — detección de picos
python agentes/agent1_peak_detector.py stream_data/<session>/transcripcion_completa.txt zapatillas_peru

# Agente 2 — refinamiento de rangos (lee picos.json de la misma carpeta)
python agentes/agent2_range_refiner.py stream_data/<session>/picos.json zapatillas_peru

# Agente 3 — scoring y generación de contenido (lee rangos.json de la misma carpeta)
python agentes/agent3_viral_scorer.py stream_data/<session>/rangos.json zapatillas_peru

# Agente 4 — corte de video (lee contenido.json; busca el video más grande en esa carpeta)
python edicion_video/agent4_video_cutter.py stream_data/<session>/contenido.json
```

Notas:
- El Agente 4 no recibe `canal_id` — no usa Claude ni config, solo corta con FFmpeg.
- `contexto/config_loader.py` también puede correrse directo (`python contexto/config_loader.py`) — no es un comando de flujo de trabajo, es un self-test que imprime casos de carga de config único/ecosistema/fallback.

---

## 4. Comandos que ya NO aplican (archivados)

- `python capture_pipeline.py <url>` — script v1.1 que vivía en la raíz; ahora está en `archive/capture_pipeline.py` y usa `whisper` clásico en vez de WhisperX. Es lo que describía el `CLAUDE.md` viejo. No lo ejecutes desde ahí sin adaptarlo — no está integrado con el resto del pipeline actual (agentes 0, Módulo Contexto, etc.).
- `archive/merge_contenido.py` — script puntual de una sola vez, con una ruta de sesión (`stream_data/20260612_210425`) y una lista de chunks hardcodeados dentro del archivo. No es un comando general; si necesitás mergear contenido de chunks manualmente, hoy eso ya lo hace `pipeline.py` automáticamente al final del modo `--video` (ver ARQUITECTURA.md §3.1 paso 5).
