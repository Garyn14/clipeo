# Comandos del Pipeline

Referencia de todos los comandos disponibles hoy en el proyecto, con ejemplos. Para entender qué hace cada etapa internamente ver [ARQUITECTURA.md](ARQUITECTURA.md); para el formato de los archivos que estos comandos leen/escriben ver [ESTRUCTURA_DATOS.md](ESTRUCTURA_DATOS.md).

Todos los comandos se ejecutan desde la raíz del proyecto. Los que llaman a Claude usan por defecto **Claude Code headless** (`AI_PROVIDER=claude_cli`): requieren Claude Code instalado y con sesión iniciada en la máquina, no `ANTHROPIC_API_KEY` (ver §4). `HF_TOKEN` en `.env` es opcional (diarización de hablantes).

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
# (un --session-id distinto por chunk: sin él, todos los chunk_NNN.mp4 de la misma
#  grabación compartirían la carpeta de sesión y su pipeline_estado.json)
python pipeline.py --video "stream_data/tiktok_fritzsport_20260705_120000/chunk_001.mp4" \
  --session-id tiktok_fritzsport_20260705_120000_c001 --config zapatillas_peru

# Con revisión manual antes de cortar cada clip
python pipeline.py --video https://www.tiktok.com/@fritzsport/video/123456789 --config zapatillas_peru --revisar

# Sesión con id fijo, sin preguntas interactivas (es lo que usa el panel web)
python pipeline.py --video <url> --session-id 20260930_120000 --colab --config zapatillas_peru
```

- Si la URL/archivo ya fue procesado antes (misma URL registrada en algún `pipeline_estado.json`), pregunta si querés retomar esa sesión en vez de volver a descargar. Con `--session-id` no pregunta: retoma `stream_data/<id>` si existe.
- Cada etapa es un **paso** con estado propio en `pipeline_estado.json` (ver ARQUITECTURA.md §3.0). Si el proceso se corta (Ctrl+C), el paso en curso queda pendiente y la próxima ejecución retoma desde ahí — no rehace pasos ya `ok`.
- Los errores reintentables (límite de uso de Claude, Colab caído, red) se reintentan solos: 3 veces, esperando 30 s / 2 min / 5 min (`PIPELINE_ESPERAS_REINTENTO=30,120,300`). Si se agotan, o el error no es reintentable, el paso queda en `error`, el chunk en `fallido`, los demás chunks siguen y el proceso termina con código 1.

### 1.2.1 Reintentar un paso

```bash
# Re-decidir con el juez (p. ej. después de actualizar referencias.yaml) — rehace juez y corte
python pipeline.py --video <url> --session-id <id> --colab --reintentar juez

# Reintentar la transcripción de un chunk (ej. después de levantar Colab y actualizar COLAB_TRANSCRIBE_URL)
# Nota: si la corrida sigue viva, no hace falta — la URL/token de Colab se releen de .env en cada intento,
# así que el siguiente reintento automático ya usa la URL nueva. Acepta la URL con o sin /transcribe.
python pipeline.py --video <url> --session-id <id> --colab --reintentar transcripcion --chunk chunk_002

# Reintentar el Agente 3 en varios chunks
python pipeline.py --video <url> --session-id <id> --reintentar agente3 --chunk chunk_001,chunk_003

# Sin --chunk: todos los chunks donde ese paso quedó en error
python pipeline.py --video <url> --session-id <id> --colab --reintentar transcripcion
```

- Vuelve el paso y **todos los siguientes** del chunk a pendiente, borra lo que produjeron (incluidos sus clips) y retoma. Los pasos anteriores no se tocan.
- Pasos: `descarga`, `plan` (de sesión) y `transcripcion`, `agente0`, `agente1`, `agente2`, `agente3`, `corte` (por chunk). Al terminar, el mensaje final de un pipeline con errores imprime el comando exacto.
- Mismo mecanismo que el botón "Reintentar desde este paso" del panel web.
- `--config` es el `canal_id`: puede resolver a un nicho del Módulo Contexto v2 (`contexto/nichos/<id>.yaml`), a un archivo único v1 (`config/<id>.yaml`) o a un ecosistema v1 (`config/<id>/`). Ver ESTRUCTURA_DATOS.md.
- Omitiendo `--config` se usa `config/default.yaml` (prompt genérico, sin lore de personajes).

### 1.3 Reprocesar una sesión ya transcrita (modo test)

Salta descarga/transcripción y corre los agentes 1→4 directo sobre una transcripción existente. Útil para iterar sobre prompts/config sin gastar tiempo/dinero en volver a transcribir.

```bash
python pipeline.py --test stream_data/test/ --config zapatillas_peru
python pipeline.py --test stream_data/20260704_170532/ --config zapatillas_peru --revisar
```

- Requiere que exista `transcripcion_completa.txt` dentro del directorio dado.
- Procesa todo el archivo como una sola unidad: se registra como un chunk único (`chunk_001`) en `pipeline_estado.json`, para que se vea y se reintente igual que una sesión normal (`--test <dir> --reintentar agente2`).

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

**Deprecado en la práctica (2026-07-31)**: este comando gasta API real (la búsqueda web corre dentro de la llamada a Claude). Para este tipo de investigación, hoy se prefiere pedirle directo a un agente de Claude Code que investigue con su propio `WebSearch` en la sesión — sin comando de terminal, sin gastar `ANTHROPIC_API_KEY`. Mismo patrón usado por `.claude/skills/seo-refresh/SKILL.md`. El comando de abajo sigue funcionando si hiciera falta.

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

## 4. Proveedor de IA (`AI_PROVIDER`)

Los Agentes 0-3 y `contexto/feedback.py` obtienen su cliente vía `ai_client.get_client()` (ver [ARQUITECTURA.md §16](ARQUITECTURA.md)):

| `AI_PROVIDER` | Qué hace | Requiere |
|---|---|---|
| `claude_cli` (default) | Cada llamada corre `claude -p` aislado (sin herramientas, sin CLAUDE.md/memorias) con la sesión de Claude Code de la máquina | Claude Code instalado y con sesión iniciada |
| `anthropic` | API real de Anthropic | `ANTHROPIC_API_KEY` |
| `manual` | Protocolo de archivos, respuesta escrita a mano (solo depuración) | nada |

Variables opcionales de `claude_cli`: `AI_CLI_MODEL` (default `sonnet`; el id que pide cada agente se ignora), `AI_CLI_TIMEOUT` (segundos por llamada, default 600), `AI_CLI_PATH` (ruta al ejecutable si `claude` no está en `PATH`).

```bash
# Agente 1 aislado con el default (Claude Code)
python agentes/agent1_peak_detector.py stream_data/<session>/transcripcion_completa.txt zapatillas_peru

# Volver a la API para una corrida puntual
AI_PROVIDER=anthropic python pipeline.py --video <url> --config <canal_id>
```

### 4.1 Modo manual (`AI_PROVIDER=manual`, solo depuración)

Con `AI_PROVIDER=manual` en `.env` (o como variable de entorno puntual), ningún agente llama a Claude — en su lugar, cada llamada queda escrita en `ai_client/_pending/<id>.request.json` y el proceso espera a que alguien escriba `ai_client/_pending/<id>.response.json` a mano.

```bash
# Ejemplo: correr el Agente 1 aislado (§3) sin gastar la API
AI_PROVIDER=manual python agentes/agent1_peak_detector.py stream_data/<session>/transcripcion_completa.txt zapatillas_peru

# Ejemplo: corrida completa de pipeline.py sin gastar la API de Claude
AI_PROVIDER=manual python pipeline.py --video <url> --config <canal_id>
```

Con `pipeline.py` (no aplica a los agentes sueltos de arriba), `AI_PROVIDER=manual` **fuerza automáticamente `--colab`** para la transcripción — no hace falta pasarlo a mano. WhisperX local puede tardar más de una hora en un video de 20-25 min, lo cual no tiene sentido si de por sí el objetivo es iterar rápido sin gastar la API; requiere `COLAB_TRANSCRIBE_URL` configurada en `.env` (ver `.env.example`).

Esto imprime algo como:
```
[AI_CLIENT] Modo manual — request escrita: ai_client/_pending/3f9a1b2c4d5e.request.json
[AI_CLIENT] Esperando respuesta en: ai_client/_pending/3f9a1b2c4d5e.response.json (timeout 1800s)
```

Para responder: abrir el `.request.json` (trae `model`/`system`/`messages`/`max_tokens`, lo mismo que iría a la API), generar el texto que Claude habría devuelto, y escribir `ai_client/_pending/3f9a1b2c4d5e.response.json` con:
```json
{"text": "{\"picos\": [...]}"}
```
(el JSON que espera el agente que hizo la llamada, como string dentro de `"text"`). El proceso retoma apenas detecta el archivo, y borra ambos al terminar.

Sin `AI_PROVIDER` en `.env` se usa `claude_cli`.

---

## 5. Comandos que ya NO aplican (archivados)

- `python capture_pipeline.py <url>` — script v1.1 que vivía en la raíz; ahora está en `archive/capture_pipeline.py` y usa `whisper` clásico en vez de WhisperX. Es lo que describía el `CLAUDE.md` viejo. No lo ejecutes desde ahí sin adaptarlo — no está integrado con el resto del pipeline actual (agentes 0, Módulo Contexto, etc.).
- `archive/merge_contenido.py` — script puntual de una sola vez, con una ruta de sesión (`stream_data/20260612_210425`) y una lista de chunks hardcodeados dentro del archivo. No es un comando general; si necesitás mergear contenido de chunks manualmente, hoy eso ya lo hace `pipeline.py` automáticamente al final del modo `--video` (ver ARQUITECTURA.md §3.1 paso 5).


## Investigación del nicho (memoria del juez)

La memoria que usa el juez (`investigacion/<nicho>/referencias.yaml`) se construye con clips reales del nicho medidos en TikTok:

```bash
# 1. Métricas de los últimos videos de cada cuenta de investigacion/<nicho>/cuentas.yaml (solo metadata, sin descargar)
python investigacion/recolectar.py zapatillas_peru            # → videos.jsonl (pausa de 20 s entre cuentas)

# 2. Muestra para analizar a fondo: top y fondo por outlier de cada universo + éxitos de la cuenta propia
python investigacion/muestrear.py zapatillas_peru             # → muestra/<id>/{video.mp4, fotogramas.jpg, audio.mp3}

# 3. Transcribir la muestra con Colab
python investigacion/transcribir_muestra.py zapatillas_peru   # → muestra/<id>/transcripcion.txt
```

4. **Actualizar `referencias.yaml`:** en una sesión de Claude Code, pedir que lea los `fotogramas.jpg` (texto en pantalla) y las `transcripcion.txt` del top y del fondo, y actualice los tipos que funcionan, los ejemplos con sus métricas, la fórmula del título y lo que no funciona. Es curaduría, no un script.
5. **Aplicarlo a sesiones ya procesadas:** `--reintentar juez` (o "Reintentar desde este paso" en el círculo Juez).

Outlier = vistas ÷ mediana de vistas de la cuenta (`investigacion/comun.py::calcular_outliers`). Se excluyen los videos con 0 vistas (privados) y los de menos de 3 días. TikTok bloquea por IP el uso intensivo: respetar las pausas y usar `cookies.txt`.

### Auditoría de lo perdido

```bash
python -m agentes.auditoria <session_id> [--chunk chunk_001]
```

Lee la transcripción completa de cada chunk con la memoria del nicho y lista los momentos de tipos que funcionan que **no** llegaron al juez (no los detectó el A1 o los fusionó el A2). Escribe `chunks/<id>/auditoria.json`. Úsala después de cambiar la memoria o el prompt del A1, o cuando sospeches que se pierden clips. Si aparece algo, `--reintentar agente1` vuelve a buscar (el A1 no es determinista) o hay que ajustar la memoria.
