# Arquitectura del Pipeline — Idea Millonaria

> Este documento describe la arquitectura **actual** del sistema, tal como existe en el código hoy. No cubre uso, instalación ni código — solo estructura, componentes, flujo de datos y decisiones de diseño. Para comandos ver [COMANDOS.md](COMANDOS.md); para esquemas de archivos ver [ESTRUCTURA_DATOS.md](ESTRUCTURA_DATOS.md); para cómo aprende el sistema con el tiempo ver [APRENDIZAJE.md](APRENDIZAJE.md).

## 1. Propósito y forma general

El sistema toma video (TikTok Live u otra fuente soportada por `yt-dlp`), lo transcribe, y usa una cadena de **4 agentes basados en Claude** para detectar momentos potencialmente virales, refinar sus límites exactos, puntuarlos y generarles título/hashtags, y finalmente cortarlos como clips verticales (9:16) con subtítulos quemados listos para publicar en TikTok/Shorts/Reels.

Es un pipeline **secuencial por etapas**, orquestado por un script central (`pipeline.py`), donde cada etapa lee el/los archivo(s) JSON que produjo la etapa anterior y escribe su propio JSON de salida. No hay cola de mensajes ni base de datos: **el sistema de archivos de la sesión (`stream_data/<session_id>/`) es el bus de comunicación entre etapas**.

Hay una segunda capa transversal — el **Módulo de Contexto** — que inyecta lore/conocimiento de dominio (personajes, historial de eventos, aprendizajes de feedback) en los prompts de los agentes, para que la detección y el copywriting sean específicos de cada nicho/canal en vez de genéricos.

## 2. Componentes principales

```
┌─────────────────────────────────────────────────────────────────────┐
│                          pipeline.py (orquestador)                  │
│   Resuelve modo (--live / --video / --test) y config (--config)     │
└───────────────┬───────────────────────────────────┬─────────────────┘
                │                                    │
     ┌──────────▼──────────┐              ┌──────────▼──────────┐
     │  Capa de Config      │              │  Capa de Captura     │
     │  ConfigLoader (v1)   │              │  video_capture.py    │
     │  ContextLoader (v2)  │              │  chunk_manager.py    │
     └──────────┬───────────┘              │  audio_chunker.py    │
                │                          └──────────┬───────────┘
                │                                     │
                ▼                                     ▼
        config dict (dict plano)          audio/video en disco por chunk
                │                                     │
                └──────────────┬──────────────────────┘
                               ▼
                 ┌─────────────────────────────┐
                 │  video_transcriber.py        │  (WhisperX + diarización)
                 └──────────────┬───────────────┘
                                ▼
                 ┌─────────────────────────────┐
                 │  transcript_cleaner.py       │  (corrección de nombres)
                 └──────────────┬───────────────┘
                                ▼
                 ┌─────────────────────────────┐
                 │  Agente 0 — Speaker ID       │  (Claude + metadata)
                 └──────────────┬───────────────┘
                                ▼
   ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌────────────┐
   │  Agente 1  │──▶│  Agente 2  │──▶│  Agente 3  │──▶│  Agente 4  │
   │  Picos     │   │  Rangos    │   │  Scoring + │   │  Corte de  │
   │  virales   │   │  refinados │   │  contenido │   │  video     │
   └────────────┘   └────────────┘   └────────────┘   └────────────┘
                                ▲
                                │ enriquece prompts
                 ┌─────────────────────────────┐
                 │  Módulo Contexto (v2)        │
                 │  nichos / entidades / eventos│
                 └─────────────────────────────┘
                                ▲
                                │ retroalimenta
                 ┌─────────────────────────────┐
                 │  feedback.py                 │  (feedback humano → aprendizajes)
                 └─────────────────────────────┘
```

## 3. El orquestador — `pipeline.py`

Es el punto de entrada único del flujo normal. Recibe un modo mutuamente excluyente:

- **`--live <url>`**: pensado para capturar y procesar un TikTok Live en tiempo real, delegando a un script externo (`capture_pipeline.py`) que correría dos procesos en paralelo (video completo + audio en chunks de 5 min transcritos sobre la marcha). **Este script ya no existe en la raíz del proyecto** (fue movido a `archive/capture_pipeline.py`, una versión v1.1 basada en `whisper` clásico, no en WhisperX). Esto significa que el modo `--live` de `pipeline.py`, tal como está hoy, es una ruta orquestadora **huérfana**: intenta lanzar un subproceso que no existe.
- **`--video <url o ruta local>`**: el modo activo y mantenido. Descarga (o reutiliza) el video completo, lo divide en chunks de tiempo (por defecto 30 min) y procesa cada chunk secuencialmente a través de transcripción + los 4 agentes, cortando clips inmediatamente al terminar cada chunk. Soporta reanudación tras interrupción.
- **`--test <directorio>`**: asume que ya existe una `transcripcion_completa.txt` en el directorio dado (sesión pregrabada/preexistente) y corre directamente los agentes 1→4 sobre ella, sin pasos de captura/transcripción.

Antes de ejecutar cualquier modo, `pipeline.py` resuelve la configuración del canal/nicho a través de `_load_config()`, que decide dinámicamente entre dos sistemas de configuración (ver sección 4).

### 3.1 Flujo interno del modo `--video` (el camino principal)

1. **Resolución de input**: determina si la URL es un archivo local ya descargado o una URL remota. Si es remota, busca primero en `stream_data/*/pipeline_estado.json` una sesión previa con la misma URL, para ofrecer reanudarla en vez de re-descargar.
2. **Descarga** (si no hay sesión previa): usa `core/video_capture.py` para bajar el video completo (≤1080p) y su audio, además de metadata completa (`yt-dlp --dump-json`) que se usará después por el Agente 0.
3. **Planificación por chunks**: `core/chunk_manager.py` divide la duración total del video en bloques de tamaño fijo (30 min por defecto) y persiste el plan + estado de avance en `pipeline_estado.json`, permitiendo reanudar procesamiento chunk por chunk tras un corte o error.
4. **Por cada chunk pendiente**:
   - Extrae el audio del rango correspondiente (`core/audio_chunker.py`, usando *input seek* de FFmpeg para velocidad) o reutiliza una transcripción base ya existente, dividiéndola por rango de tiempo en vez de re-transcribir.
   - Transcribe con WhisperX (`core/video_transcriber.py`), ajustando timestamps al offset real del chunk dentro del video completo.
   - Si el config del canal define `personajes`, limpia errores de transcripción de nombres propios (`core/transcript_cleaner.py`).
   - Si hay diarización de hablantes (`SPEAKER_XX`) y hay `metadata.json`, corre el **Agente 0** para mapear speakers genéricos a nombres reales, y si el ecosistema lo requiere, re-enriquece el config en caliente con el lore del personaje detectado (solo aplica al sistema de config v1 tipo "ecosistema").
   - Corre **Agente 1** (detección de picos) sobre la transcripción del chunk.
   - Si hay picos, corre **Agente 2** (refinamiento de rangos) sobre ellos.
   - Si hay rangos conservados, corre **Agente 3** (scoring + generación de título/hashtags).
   - Si `--revisar` está activo, entra en un bucle de aprobación manual por terminal antes de continuar (ver sección 8).
   - Corre **Agente 4** (corte de video) inmediatamente sobre los clips marcados `publicar` de ese chunk — no espera a que terminen todos los chunks. Esto permite ver clips generados progresivamente durante una sesión larga.
   - Marca el chunk como completado (o fallido, con el error persistido) en el estado del `ChunkManager`.
5. **Consolidación final**: al terminar todos los chunks, mergea los `contenido.json` de cada chunk en un único `contenido_final.json` a nivel de sesión, ordenado por score descendente.

### 3.2 Modo `--test`

Salta directamente a Agente 1 → 2 → 3 → 4 sobre una transcripción ya existente en el directorio dado. No hay chunking, descarga ni Agente 0. Es el modo usado para iterar rápido sobre prompts/config sin re-transcribir.

## 4. Capa de configuración — dos sistemas coexistentes

El sistema soporta **dos arquitecturas de configuración en paralelo**, seleccionadas automáticamente según qué archivos existan para el `canal_id` pedido:

### 4.1 `ConfigLoader` (v1) — `core/config_loader.py`

Config por archivo YAML plano bajo `config/`. Soporta dos variantes:
- **Archivo único**: `config/<canal_id>.yaml` — todo el prompt y reglas en un solo archivo (ej. `config/zapatillas_peru.yaml`).
- **Ecosistema**: una carpeta `config/<ecosistema_id>/` con un `_index.yaml` (prompt base + lista de `personajes` con sus alias) más un YAML por personaje (`config/<ecosistema_id>/<personaje_id>.yaml` con su lore, prompt adicional y hashtags propios).

En el modo ecosistema, la config se **enriquece dinámicamente en tiempo de ejecución**: cuando el Agente 0 identifica qué personajes están hablando en un chunk, `enrich_with_speakers()` busca coincidencias por alias, carga el YAML del personaje detectado y concatena su lore/prompt adicional al prompt de detección, y sus hashtags a los hashtags base — evitando cargar contexto de personajes que no aparecen en ese fragmento.

### 4.2 `ContextLoader` (v2) — `core/context_loader.py` + carpeta `contexto/`

Sistema más granular, basado en tres niveles de archivos YAML:
- `contexto/nichos/<nicho_id>.yaml`: define el nicho, su lista de `entidades` (personajes) y los prompts base de detección/refinamiento/contenido.
- `contexto/entidades/<entidad_id>.yaml`: lore de cada personaje (historia, universo de personajes secundarios, vocabulario, señales de detección específicas confirmadas por resultados reales).
- `contexto/eventos/<YYYY-MM>/<entidad_id>_*.yaml`: eventos puntuales — correcciones de título, descartes manuales, o noticias externas encontradas por `contexto_refresh.py` — que documentan aprendizajes reales por fecha.

A diferencia de v1, en `ContextLoader` **todo el contexto se ensambla por adelantado** en `load_nicho()` (todas las entidades del nicho se cargan siempre, no de forma perezosa según quién habla), y expone la misma interfaz pública (`get()`, `loaded_file`, `get_ecosystem_type()`, `enrich_with_speakers()`) que `ConfigLoader`, por lo que el resto del pipeline es agnóstico a cuál de los dos sistemas está activo.

### 4.3 Selección automática

`pipeline.py::_load_config()` decide así: si existe `contexto/nichos/<canal_id>.yaml`, usa `ContextLoader` (v2); si no, cae a `ConfigLoader` (v1) buscando `config/<canal_id>.yaml` o `config/<canal_id>/`, y si tampoco existe, usa `config/default.yaml` como fallback genérico.

En ambos casos, el resultado es un **dict plano en memoria** con las claves `meta`, `identificacion`, `deteccion`, `refinamiento`, `contenido`, `contenido_restricciones` (opcional), `personajes`/`entidades`, que es lo que consumen los agentes — ellos no saben ni les importa qué loader lo produjo.

## 5. Capa de captura

- **`tiktok_capture.py`**: script de grabación standalone, independiente del pipeline de procesamiento. Graba un TikTok Live activo en chunks de duración configurable usando `yt-dlp` (con `--no-live-from-start`, obligatorio porque TikTok Live no soporta DVR), matando el árbol de procesos completo (yt-dlp + ffmpeg hijo) al cortar cada chunk o al recibir Ctrl+C, para evitar procesos huérfanos escribiendo sin límite. Registra el progreso en `captura_estado.json`. Los chunks grabados se procesan después manualmente con `pipeline.py --video <chunk.mp4>`.
- **`core/video_capture.py`**: usado por el modo `--video` de `pipeline.py` para descargar un video completo (no un live) de una URL, extraer su audio completo y guardar la metadata JSON del video (título, descripción, uploader) que alimenta al Agente 0.
- **`core/chunk_manager.py`**: gestiona el plan de chunks temporales de una sesión de video ya descargado (no de captura en vivo) y el checkpointing de qué chunk está pendiente/completado/fallido, persistido en `pipeline_estado.json`.
- **`core/audio_chunker.py`**: extrae con FFmpeg (input seek) el segmento de audio correspondiente a un chunk de tiempo específico del video completo.

## 6. Capa de transcripción

`core/video_transcriber.py` usa **WhisperX** (no el Whisper original mencionado en la documentación antigua del proyecto) para transcribir con alineación de palabras y, si hay `HF_TOKEN` configurado, diarización de hablantes vía `pyannote` (a través de WhisperX). Sin diarización, la transcripción no distingue quién habla.

Expone dos funciones equivalentes: `transcribe_full()` (transcribe un audio completo de una sola vez) y `transcribe_chunk()` (igual, pero ajusta los timestamps sumando el offset del chunk dentro del video completo, para que los timestamps en el `.txt` reflejen el tiempo real del stream, no el tiempo relativo del chunk). El pipeline en modo `--video` usa la segunda.

La salida es un archivo de texto plano con líneas `[MM:SS] SPEAKER_XX: "texto"` (con diarización) o `[MM:SS] texto` (sin ella) — este formato de texto con timestamp es el "protocolo" que consumen todos los agentes downstream vía `core/utils.py::_parse_segments()`.

## 7. Corrección de nombres — `core/transcript_cleaner.py`

Capa de limpieza determinística (sin LLM) que corre justo después de transcribir, solo si el config del canal define `personajes`. Genera variantes fonéticas plausibles del nombre canónico de cada personaje (confusión S/C inicial, vocales duplicadas/añadidas/quitadas, inserciones vocálicas) para capturar errores típicos de Whisper al transcribir nombres propios poco comunes (ej. "Sideral" mal transcrito como "Cideral" o "Sidereal"), y las reemplaza por la forma canónica antes de que la transcripción llegue a los agentes.

## 8. Agente 0 — Identificación de hablantes (`core/agent0_speaker_identifier.py`)

No es parte de la cadena numerada 1-4; corre entre la transcripción y el Agente 1, y solo si la transcripción tiene diarización (`SPEAKER_XX`). Envía a Claude los primeros ~3 minutos de transcripción junto con la metadata del video (título, descripción) y le pide inferir quién es cada `SPEAKER_XX` por contexto (presentaciones explícitas, patrones de rol pregunta/respuesta).

Clasifica cada speaker en tres estados según umbrales de confianza configurables (`umbral_alto`, `umbral_bajo`): **confirmado** (se reemplaza el label por el nombre real en el texto), **posible** (se marca `[sin identificar]` pero no se usa el nombre), **desconocido** (se marca `[sin identificar]`). Si Claude no logra identificar a nadie con confianza, hay un *fallback* que usa el `uploader` de la metadata del video para asignar el nombre del canal al speaker que más habla.

Produce `transcripcion_enriquecida.txt` (la transcripción con nombres resueltos y marcas de incertidumbre) y `speaker_map.json` (el mapeo detallado). Esta transcripción enriquecida —no la raw— es la que prefieren leer los Agentes 1/2/3 cuando existe.

## 9. La cadena de 4 agentes

Cada agente es un módulo independiente, invocable tanto como función (`run_agent()`) desde `pipeline.py` como standalone por CLI. Todos reciben el `config` dict ya resuelto — ninguno carga configuración por sí mismo salvo cuando se ejecutan standalone.

### Agente 1 — Detector de picos virales (`agent1_peak_detector.py`)
Lee la transcripción completa del chunk y la envía a Claude junto con el prompt de detección del config (usando *prompt caching* para el prompt de nicho, que es grande y se reutiliza). Si la transcripción excede ~10.000 palabras, la divide en ventanas de 10 minutos con 1 minuto de solapamiento para evitar perder contexto en los bordes, y luego fusiona picos duplicados detectados en ventanas distintas (tolerancia de 30s). Filtra los picos resultantes por `confianza_minima` del config. Salida: `picos.json`.

### Agente 2 — Refinador de rangos (`agent2_range_refiner.py`)
Para cada pico, extrae una ventana de contexto (±N segundos configurable) alrededor del timestamp marcado. Envía **todos los picos del chunk en una sola llamada agrupada** a Claude (no una llamada por pico), pidiéndole que determine el rango exacto de inicio/fin de cada clip, decida si conservarlo o descartarlo, y — señal importante de diseño — que **fusione picos que se solapen o cuenten la misma historia** en un único rango. Esto significa que el número de rangos de salida puede ser menor al número de picos de entrada. Salida: `rangos.json`.

### Agente 3 — Scorer viral y generador de contenido (`agent3_viral_scorer.py`)
Para cada rango conservado, extrae el texto exacto del clip y llama a Claude para: puntuarlo 1-10, generar dos líneas de texto para quemar en el video (`texto_linea1`/`texto_linea2`) y proponer hashtags. Detecta qué personajes conocidos del config aparecen específicamente en ese rango (±30s de margen) para poder mencionarlos por nombre en el copy sin "contaminar" con personajes que solo aparecen en otros momentos del mismo chunk. Si el config define `palabras_prohibidas`, verifica el texto generado y **regenera automáticamente** con una instrucción adicional si las detecta. Vuelve a pasar el texto generado por el limpiador de nombres canónicos. Aplica `score_minimo_publicar` del config para decidir el flag `publicar`. También inyecta, si existen, los "aprendizajes optimizados" del canal (`aprendizajes/<canal_id>_optimizado.md`, generados por `feedback.py`) como reglas activas adicionales en el prompt cacheado. Salida: `contenido.json`.

### Agente 4 — Cortador de video (`agent4_video_cutter.py`)
El único agente que **no usa Claude ni recibe `config`** — es puramente técnico/determinístico. Lee los clips marcados `publicar`, localiza el video fuente, y para cada uno corta con FFmpeg (input seek) el rango exacto, escala/rellena a 1080x1920 (formato vertical 9:16), y quema las dos líneas de texto como subtítulo con una lógica de layout que se adapta según si el video fuente es panorámico (produce barras negras arriba/abajo, "letterbox" — el texto se ancla justo encima del video) o ya es vertical (texto centrado semitransparente, visible solo los primeros 4 segundos). Ajusta tamaño de fuente dinámicamente según el largo del texto para no desbordar. Tiene *fallback*: si el corte con subtítulo falla (ej. fuente no disponible), reintenta sin texto para no perder el clip. Genera un `.json` de metadata por clip junto al `.mp4`, con un flag `listo_para_publicar` que queda en `false` para revisión humana posterior.

## 10. Modo de revisión manual (`--revisar`)

Flag opcional del pipeline que, tras el Agente 3 y antes del Agente 4, entra en un bucle interactivo por terminal (`pipeline.py::_revisar_clips`) mostrando cada clip candidato (score, rango, título propuesto) y pidiendo una acción: aprobar, editar solo el título, editar solo el rango, editar ambos, o descartar con una razón. Las correcciones de título y los descartes con razón se persisten como **eventos** en `contexto/eventos/<YYYY-MM>/` (mismo formato que usa el Módulo Contexto v2), quedando disponibles como aprendizaje para sesiones futuras aunque el canal use el sistema de config v1.

## 11. Ciclo de feedback y aprendizaje — `feedback.py`

Herramienta separada, ejecutada después de publicar clips, que recorre los clips generados de una sesión (`clips/` y `clips_custom/`), pide al usuario evaluación humana (score propio, razón, título alternativo) por clip, y envía ese feedback agregado a Claude para que lo destile en dos artefactos complementarios:
- **Historial completo** (`aprendizajes/<canal_id>.md`): registro append-only de cada sesión de feedback, para trazabilidad.
- **Reglas optimizadas** (`aprendizajes/<canal_id>_optimizado.md`): solo si Claude determina que el feedback es *generalizable* (no específico de un único clip), añade una regla corta y accionable a este archivo, que el Agente 3 carga e inyecta en su prompt cacheado en sesiones futuras.

Este es solo uno de tres mecanismos de retroalimentación del sistema (los otros son los eventos de `--revisar` y de `contexto_refresh.py`) — ver **[APRENDIZAJE.md](APRENDIZAJE.md)** para el detalle completo de cuáles se re-inyectan automáticamente y cuáles requieren curación manual.

Este es el mecanismo principal por el que el sistema "aprende" de errores de copywriting sin reentrenar nada — es retroalimentación textual inyectada en el prompt, no fine-tuning.

## 12. Refresco de contexto externo — `contexto_refresh.py`

Herramienta independiente (no forma parte del pipeline de procesamiento) que usa la *tool* de búsqueda web nativa de la API de Claude para buscar noticias recientes sobre una entidad/personaje definida en `contexto/entidades/`, mostrarlas al usuario y, tras aprobación manual una por una, guardarlas como eventos en `contexto/eventos/<YYYY-MM>/refresh_<entidad>_*.yaml` — el mismo mecanismo de eventos que alimenta al `ContextLoader` en la siguiente ejecución del pipeline para ese nicho.

## 13. Herramienta de corte manual — `clip_manual.py`

Bypass directo del Agente 4 para cortar un clip puntual (rango de tiempo + texto arbitrario) sin pasar por Agentes 1-3 ni por `contenido.json`. Reutiliza directamente las funciones internas de corte/tipografía/detección de letterbox de `agent4_video_cutter.py`. Guarda el resultado en `clips_custom/` dentro de la sesión, con su propio `.json` de metadata marcado `creado_manual: true`.

## 14. Persistencia y estructura de una sesión

Cada ejecución (ya sea `--video` o una captura de `tiktok_capture.py`) crea un directorio bajo `stream_data/<session_id>/` (timestamp o `tiktok_<usuario>_<timestamp>`). Dentro, según el modo y la etapa alcanzada, puede contener:

- `metadata.json` — metadata cruda de `yt-dlp --dump-json` (título, descripción, uploader).
- `stream_completo.mp4` / `audio/audio_completo.mp3` — video y audio fuente descargados.
- `pipeline_estado.json` — plan de chunks y su estado (`pendiente`/`completado`/`fallido`), producido y actualizado por `ChunkManager`; es lo que permite **reanudar** una sesión interrumpida sin reprocesar chunks ya hechos.
- `chunks/<chunk_id>/` — por chunk: `transcripcion_raw.txt`, `transcripcion_enriquecida.txt`, `transcripcion_completa.txt` (copia de compatibilidad), `speaker_map.json`, `picos.json`, `rangos.json`, `contenido.json`.
- `audio_chunks/<chunk_id>.mp3` — audio extraído por chunk (solo si no había transcripción base para dividir).
- `contenido_chunks/<chunk_id>.json` — resumen de contenido por chunk, ya post-revisión manual si aplicó.
- `contenido_final.json` — merge de todos los `contenido_chunks/*.json` al terminar la sesión, ordenado por score.
- `clips/clip_NNN.mp4` + `clip_NNN.json` — clips finales cortados por el Agente 4, numerados de forma continua entre chunks (vía `clip_offset`).
- `clips_custom/` — clips generados manualmente con `clip_manual.py`.

Este diseño basado en archivos (sin base de datos) hace que **cualquier etapa sea inspeccionable y reproducible manualmente** — se puede re-correr un agente individual por CLI apuntándolo al JSON intermedio de la etapa anterior, sin tocar el resto del pipeline.

## 15. Utilidades compartidas — `core/utils.py`

Funciones puras compartidas por todos los módulos para evitar duplicación: conversión de timestamps (`MM:SS`/`HH:MM:SS` ↔ segundos), parseo de líneas de transcripción con timestamp (`_parse_segments`), e inyección del path de FFmpeg en `PATH` (necesario porque el binario está en una ubicación no estándar de WinGet en esta máquina, no en el `PATH` del sistema).

## 16. Notas sobre el estado real de la arquitectura

- El **modo `--live` de `pipeline.py` está roto/huérfano**: depende de un `capture_pipeline.py` en la raíz que ya no existe (fue archivado en `archive/capture_pipeline.py`, versión v1.1 con `whisper` clásico en vez de WhisperX). El camino soportado actualmente para contenido en vivo es: `tiktok_capture.py` (graba chunks del live a disco) → `pipeline.py --video <chunk.mp4>` (procesa cada chunk grabado como si fuera un video normal).
- El `CLAUDE.md` en la raíz del repositorio describe exclusivamente esa arquitectura v1.1 archivada (un único script `capture_pipeline.py`, Whisper clásico, sin agentes 0/2/3/4 separados, sin Módulo de Contexto) — **no refleja el pipeline v2.0 actual** documentado aquí.
- Coexisten dos sistemas de configuración con la misma interfaz pública (`ConfigLoader` v1 y `ContextLoader` v2); la selección es automática y transparente para el resto del código, pero implica que hay dos formatos YAML distintos y no intercambiables mantenidos en paralelo (`config/` vs `contexto/`).
