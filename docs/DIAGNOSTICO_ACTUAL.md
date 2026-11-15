# Diagnóstico del sistema actual — Clipeo (piloto v2.0)

> Fecha: 2026-11-15 · Commit revisado: `5653b66` ("base") · Alcance: todo el repositorio.
> Propósito: dejar una foto honesta de **dónde estamos** antes de rediseñar el proyecto como
> (1) engine agnóstico de orquestación + (2) sistema de clips SaaS punta a punta.

---

## 1. Resumen ejecutivo

| Aspecto | Estado | Comentario corto |
|---|---|---|
| Valor de negocio | 🟢 Validado | Ya produjo clips buenos en nichos reales (zapatillas_peru, streamers_peru). |
| Pipeline de clipeo (video → clips) | 🟢 Funcional | `pipeline.py --video` es el camino estable, con reanudación por chunks. |
| Calidad de IA (agentes 0–3) | 🟡 Buena, frágil | Prompts ricos en contexto; parseo de JSON por regex, sin reintentos ni validación de esquema. |
| Edición de video (Agente 4) | 🟡 Potente, monolítico | 1.273 líneas en un solo archivo; layouts, zoom, música, marca de agua. Assets son placeholders. |
| Captura de lives | 🟡 Parcial | Grabación standalone funciona; `--live` del orquestador está roto. |
| Publicación automática | 🔴 No existe | Se generan descripciones/hashtags, pero nadie publica. |
| Revisión humana | 🟡 Solo terminal | `--revisar` y `revisar_clips.py`; no hay UI. |
| Engine agnóstico | 🔴 No existe | Orquestación cableada a mano en `pipeline.py` (840 líneas). |
| Multi-tenant / SaaS | 🔴 No existe | Monousuario, sistema de archivos local, sin BD, sin auth, sin cola. |
| Portabilidad | 🔴 Atada a una PC Windows | Rutas `C:\Users\Garyn\...`, fuentes `C:\Windows\Fonts`, `taskkill`. |
| Tests | 🟢 Base sólida | 81 tests, 100% pasan (1,5 s), todo mockeado. Sin CI. |
| Documentación | 🟢 Muy buena | `docs/` detallado; algunas contradicciones menores (§7). |
| Continuidad entre sesiones | 🟡 Parcial | `CLAUDE.md` describe el piloto, no la visión ni el estado del rediseño. |

**Conclusión:** el piloto cumplió su objetivo — demostrar que la cadena *transcripción → detección →
refinamiento → copy → corte* produce clips publicables. El conocimiento valioso está en
**los prompts, el contexto de nichos/entidades, las reglas de edición y los aprendizajes**, no en la
estructura del código. El rediseño debe preservar ese conocimiento y reemplazar la estructura.

---

## 2. Qué hace hoy el sistema

```
Fuente (URL / archivo / live grabado)
  └─ captura/video_capture.py (yt-dlp)  ó  captura/tiktok_capture.py (live en chunks)
       └─ core/chunk_manager.py  — plan de chunks de 30 min + checkpoint (pipeline_estado.json)
            └─ transcripcion/  — WhisperX local o vía Colab (túnel HTTP), limpieza de nombres
                 └─ Agente 0  — identifica hablantes (si hay diarización)
                      └─ Agente 1 — detecta picos virales
                           └─ Agente 2 — refina/fusiona rangos
                                └─ Agente 3 — score + texto quemado + descripción/hashtags por plataforma
                                     └─ [--revisar por terminal]
                                          └─ Agente 4 — corte FFmpeg 9:16 con subtítulos
                                               └─ stream_data/<sesion>/clips/clip_NNN.mp4 + .json
```

Herramientas laterales: `revisar_clips.py` (revisión posterior), `entrenamiento/clip_manual.py`
(corte manual), `contexto/feedback.py` (feedback → reglas), `captura/verificar_lives.py`
(chequear quién está en vivo de `usuarios_lives.txt`), `ai_client/` modo manual (sin gastar API).

---

## 3. Inventario de código

| Módulo | Líneas | Rol | Observación |
|---|---:|---|---|
| `pipeline.py` | 840 | Orquestador + CLI + revisión interactiva + eventos | Hace demasiado; mezcla flujo, I/O de usuario y persistencia. |
| `edicion_video/agent4_video_cutter.py` | 1.273 | Corte, layouts, zoom, música, marca de agua, compilaciones | Módulo más grande; funciones de 100–300 líneas. |
| `captura/tiktok_capture.py` | 615 | Grabación de lives en chunks | Lógica de procesos específica de Windows. |
| `agentes/agent3_viral_scorer.py` | 469 | Scoring + copy + SEO | Núcleo del valor de copywriting. |
| `transcripcion/video_transcriber.py` | 431 | WhisperX local / Colab remoto | El servidor Colab **no está en el repo**. |
| `agentes/agent0..2` | 864 | Speakers, picos, rangos | Mismo patrón repetido en los tres. |
| `contexto/*` | 1.127 | Config v1/v2, feedback, refresh | Dos sistemas de config en paralelo. |
| `captura/` (resto) | 349 | Verificación de lives, descarga | Varios scripts de chequeo WAF/Colab. |
| `core/`, `ai_client/`, `entrenamiento/`, `revisar_clips.py` | ~700 | Utilidades | `ai_client` es la mejor abstracción del repo. |
| `tests/` | 880 | 5 archivos de test | Cubren agente 3 (SEO), agente 4, transcriber, context loader, ai_client. |
| Contexto YAML | ~2.050 | Nichos, entidades, eventos | **Activo de negocio principal.** |

Total Python ≈ 7.600 líneas. Historial git: **1 solo commit** ("base") — se perdió la trazabilidad
de cómo evolucionó el piloto.

---

## 4. Fortalezas (qué conservar)

1. **Cadena de agentes bien separada por responsabilidad.** Cada agente lee un JSON y escribe otro;
   cualquier etapa se puede re-ejecutar aislada. Es casi un engine de pasos, sin serlo formalmente.
2. **Contexto de dominio rico** (`contexto/nichos`, `entidades`, `eventos`): lore de personajes,
   señales de detección confirmadas, correcciones humanas. Es lo que hace buenos a los clips.
3. **Ciclo de aprendizaje por texto** (`feedback.py` → `aprendizajes/*_optimizado.md` → prompt del
   Agente 3). Simple, auditable, sin fine-tuning.
4. **`ai_client/` como punto de intercambio de transporte** (API real vs. modo manual). Es exactamente
   el tipo de desacople que necesita el engine.
5. **Reanudación por chunks** con checkpoint en disco: tolerante a cortes en videos largos.
6. **Reglas de edición investigadas** (`modulo_edicion_patrones_clipeo.md`, informes por entidad):
   layouts letterbox / crop / splitscreen / imagen de relleno, zoom de énfasis, duración del texto.
7. **Tests rápidos y deterministas** (81 en 1,5 s), sin red ni API.
8. **Documentación honesta**, incluyendo qué está roto y por qué.

---

## 5. Problemas encontrados

### 5.1 Arquitectura (bloquean la visión engine + SaaS)

| # | Problema | Evidencia | Impacto |
|---|---|---|---|
| A1 | Orquestación cableada, no declarativa | `pipeline.py::run_pipeline` / `_run_video_chunks` encadenan agentes con `if`; el modo `--test` duplica la cadena | No se pueden agregar fuentes/pasos sin tocar el orquestador. |
| A2 | Sistema de archivos como bus y como base de datos | `stream_data/<sesion>/...`, búsqueda de sesiones previas con `glob` | Sin multi-usuario, sin consultas, sin concurrencia, sin despliegue en la nube. |
| A3 | Ejecución síncrona, un proceso, un video a la vez | Bucle secuencial de chunks; `ManualClient` hace polling bloqueante | No escala; no hay cola de trabajos ni workers. |
| A4 | Interacción humana por `input()` en terminal | `_revisar_clips`, `revisar_clips.py`, `feedback.py` | La revisión no puede moverse a una UI/web sin reescribir. |
| A5 | Sin capa de publicación | Agente 3 genera `publicacion.tiktok/youtube_shorts`, nada lo consume | Falta la mitad final del producto. |
| A6 | Dos sistemas de configuración (v1 `config/` y v2 `contexto/`) | `config/` solo tiene `default.yaml`; v1 de zapatillas ya está en `archive/` | Complejidad sin beneficio; v1 está prácticamente muerto. |
| A7 | Captura de lives desacoplada a mano | `--live` llama a `capture_pipeline.py` inexistente; flujo real = grabar y luego `--video` por chunk | No hay ingesta automática de lives. |
| A8 | Transcripción remota depende de un Colab efímero | `COLAB_TRANSCRIBE_URL` (túnel trycloudflare), servidor no versionado | Punto único de falla, no reproducible. |

### 5.2 Calidad de código y robustez

| # | Problema | Evidencia |
|---|---|---|
| C1 | Parseo de respuestas de Claude por regex `\{.*\}` + `json.loads`, sin validación de esquema ni reintentos | agentes 0–3 |
| C2 | Patrón `_call_claude` duplicado en 4 agentes + `feedback.py` + `contexto_refresh.py` | modelo y `max_tokens` cableados en cada archivo |
| C3 | Modelo fijo `claude-sonnet-4-6` repetido en 6 lugares | no configurable por nicho ni centralizado |
| C4 | `feedback.py` y `contexto_refresh.py` no pasan por `ai_client/` | documentado en ARQUITECTURA §16 |
| C5 | `except Exception: pass` silencioso en búsqueda de sesiones previas y lectura de metadata | `pipeline.py`, agente 0, agente 3 |
| C6 | Auto-instalación de dependencias en runtime (`pip install pyyaml` dentro de `pipeline.py`) | `pipeline.py` líneas 26–31 |
| C7 | Funciones privadas (`_cut_clip`, `_prepare_font`, `_guardar_evento_*`) importadas desde otros módulos | `revisar_clips.py`, `entrenamiento/clip_manual.py` |
| C8 | `requirements.txt` sin versiones fijadas e incluye `openai-whisper` (solo lo usa `archive/`) | `requirements.txt` |
| C9 | Sin logging estructurado: todo es `print` con emojis | todo el repo |
| C10 | Sin CI, sin linter/formatter, sin type-checking | no hay `.github/`, `pyproject.toml` ni config de ruff/mypy |
| C11 | Cobertura desigual de tests: no hay tests de `pipeline.py`, agentes 0/1/2, captura, chunk_manager, feedback | `tests/` |

### 5.3 Portabilidad y operación

| # | Problema | Evidencia |
|---|---|---|
| P1 | Ruta personal cableada a ffmpeg de WinGet | `core/utils.py:15` (`C:\Users\Garyn\...`) — además expone el nombre de usuario de tu PC |
| P2 | Fuentes de Windows cableadas | `agent4_video_cutter.py:141-144` (`C:\Windows\Fonts\Impact.ttf`, etc.) |
| P3 | `taskkill` para matar procesos | `captura/tiktok_capture.py:264` |
| P4 | Assets de edición son placeholders | `edicion_video/assets/musica/*/PLACEHOLDER_*.mp3`, sin marca de agua ni efectos reales |
| P5 | Sin contenedor (Docker) ni guía de despliegue | — |
| P6 | Sin control de costos de API (tokens por sesión, presupuesto) | solo la regla informal "no gastar API" |

### 5.4 Documentación y continuidad

| # | Problema | Evidencia |
|---|---|---|
| D1 | `docs/ARQUITECTURA.md` §18 dice que `CLAUDE.md` describe la v1.1, pero el `CLAUDE.md` actual ya describe la v2.0 | contradicción menor |
| D2 | Referencias a "memorias" de Claude Code que no están en el repo (`preferencia-claude-code-reemplaza-scripts-de-api`, 13 menciones) | YAML de nichos, `contexto_refresh.py`, informes |
| D3 | Nombre del proyecto inconsistente: "Idea Millonaria" en código/docs, "clipeo" en el repo | encabezados de `pipeline.py`, `ARQUITECTURA.md`, `aprendizajes.md` |
| D4 | No hay documento de visión, roadmap ni estado del rediseño | — |
| D5 | Mezcla de artefactos de negocio (informes de investigación `.md`) dentro de `contexto/entidades/` junto a YAML que el código carga | `contexto/entidades/*_investigacion_*.md` |

### 5.5 Riesgos legales / de plataforma (a tener en cuenta en el SaaS)

- Descarga de lives/videos de terceros con `yt-dlp`, cookies y evasión de WAF (`check_live_waf.py`,
  `_tiktok_rate_state.json`): riesgo de bloqueo de cuentas/IP y de términos de servicio. En un SaaS
  hay que definir política de derechos (contenido propio/autorizado vs. terceros).
- Publicación automática requerirá APIs oficiales (TikTok Content Posting API, YouTube Data API,
  Meta Graph API) con OAuth por cliente y revisión de apps.

---

## 6. Qué se rescata para el rediseño

| Activo | Cómo migrarlo |
|---|---|
| Prompts de agentes 0–3 + lógica de fusión/merge | Pasos del engine con contrato de entrada/salida tipado. |
| `contexto/` (nichos, entidades, eventos) y `aprendizajes/` | Datos del tenant/canal en BD (o repositorio de contexto versionado). |
| `ai_client/` (proveedor intercambiable) | Generalizar a "proveedor de LLM" del engine; añadir reintentos, validación y medición de costo. |
| Reglas de layout del Agente 4 | Separar en: detección de layout, plantillas de render, composición FFmpeg. |
| `ChunkManager` (checkpointing) | Lo reemplaza el estado de ejecución del engine (pasos idempotentes y reanudables). |
| Tests existentes | Base para tests de regresión de los pasos migrados. |
| `docs/` | Base para la documentación de dominio; reescribir la parte de arquitectura. |

Lo que **no** conviene arrastrar: `pipeline.py` como orquestador, el modo `--live` actual,
la config v1 (`ConfigLoader`), `archive/`, los `input()` de terminal, las rutas de Windows.

---

## 7. Brechas frente a la visión objetivo

| Capacidad objetivo | Hoy | Brecha |
|---|---|---|
| Engine agnóstico de pasos (DAG/flujos declarativos, reintentos, estado) | Orquestación imperativa | Total |
| Ingesta automática de fuentes (VOD, lives, programación/monitoreo) | Manual por CLI; verificación de lives aparte | Alta |
| Procesamiento escalable (cola + workers + GPU para transcripción) | Un proceso local + Colab efímero | Alta |
| Revisión humana en UI (aprobar/editar/descartar, previsualizar) | Terminal | Alta |
| Publicación multi-plataforma automática + programación | No existe | Total |
| Métricas post-publicación que alimenten el aprendizaje | Feedback manual 24–48 h | Alta |
| Multi-tenant, auth, facturación | No existe | Total |
| Observabilidad (logs, costos, trazas por ejecución) | `print` | Alta |
| Continuidad para agentes (CLAUDE.md, roadmap, estado) | Parcial | Media |
| Agentes de negocio / dev / PO / finanzas | No existe | Lejana (por diseño) |

---

## 8. Recomendaciones inmediatas (antes de rediseñar)

1. **Congelar el piloto**: etiquetar el commit actual (`git tag piloto-v2.0`) para tener referencia estable.
2. **Escribir visión + arquitectura objetivo + roadmap por fases** (`docs/VISION.md`, `docs/ROADMAP.md`).
3. **Reescribir `CLAUDE.md`** para que apunte a visión, roadmap, estado actual y este diagnóstico.
4. **Decidir stack del SaaS** (lenguaje del engine, BD, cola, almacenamiento de video, frontend de revisión).
5. **Decidir política de fuentes y derechos** (contenido propio/autorizado) antes de construir ingesta.
6. Correcciones baratas si el piloto se sigue usando mientras tanto: quitar la ruta personal de
   `core/utils.py`, fijar versiones en `requirements.txt`, eliminar `--live` roto, añadir CI con pytest.

---

## 9. Verificación realizada para este informe

- Lectura de `CLAUDE.md`, `docs/ARQUITECTURA.md`, `docs/APRENDIZAJE.md` e inventario de funciones de todos los módulos.
- `python -m pytest -q` → **81 passed in 1.53s** (en Linux, con `pytest`, `requests-mock` y `anthropic` instalados; WhisperX no instalado — los tests lo mockean).
- No se ejecutó el pipeline completo (requiere video, ffmpeg con fuentes, WhisperX/Colab y API o modo manual).
