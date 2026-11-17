# Arquitectura del backend

## Qué es

Una API FastAPI que envuelve el pipeline existente (raíz del repo) para operarlo desde un frontend en vez de por consola. No reimplementa nada del pipeline — importa sus funciones directamente o lo lanza como subproceso, según el caso (ver más abajo). Lo que el pipeline expone para la web es genérico y también sirve por terminal: `--session-id`, `--reintentar`, el estado por pasos de `pipeline_estado.json` y las trazas de IA (ver `docs/ARQUITECTURA.md` §3.0 de la raíz).

La web replica el modelo de un hub de despachos: cada sesión es una instancia, cada paso del pipeline un círculo (verde ok, naranja error reintentable, rojo error no reintentable, azul corriendo, ámbar esperando revisión), click en el círculo → detalle con REQUEST/RESPONSE de Claude y "Reintentar desde este paso", y una vista "Errores" con reintento masivo. El último círculo, Revisión, abre la revisión de clips; "Finalizar revisión" cierra Fin.

## Cómo correrlo

Comparte el mismo entorno Python que el resto del repo (no tiene su propio venv) porque importa `pipeline.py` directamente, y ese módulo a su vez importa `anthropic`, `whisperx`, etc. Instalar además lo que pide `backend/requirements.txt` (`fastapi`, `uvicorn`) en ese mismo entorno.

```
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

`python -m uvicorn` (no `uvicorn` a secas) para garantizar que `backend/` quede en `sys.path` y el paquete `app` resuelva.

## Dos formas de tocar el pipeline, a propósito

- **Lectura y revisión de clips** (`config_scanner.py`, `state_reader.py`, `clip_index.py`, `review_actions.py`): import directo de `pipeline.py` / `edicion_video/agent4_video_cutter.py` / `core/utils.py` / `contexto/*`. Corre en el mismo proceso que la API — rápido, sin overhead de subproceso, y punto de reuso real de las funciones que ya usa `revisar_clips.py` (`_guardar_evento_correccion`, `_guardar_evento_descarte`, `_cut_clip`, `_find_video`, `_detect_video_info`, `_prepare_font`).
- **Lanzar una corrida** (`pipeline_runner.py`): subproceso (`subprocess.Popen`) corriendo `python -u pipeline.py --video ... --session-id <id> --colab` (nueva), o la misma línea con `--reintentar <paso> [--chunk ...]` / sin flags extra (reanudar). Una corrida completa implica Colab + Agentes 0-4, puede tardar minutos-horas y no debe bloquear el worker de la API ni compartir su ciclo de vida — si la API se reinicia, la corrida real (el pipeline) debe poder seguir sola. Por eso el subproceso:
  - va en su **propio grupo de procesos** (`CREATE_NEW_PROCESS_GROUP` en Windows): un Ctrl+C en la consola de uvicorn no le llega;
  - recibe `stdin=DEVNULL`: nunca puede quedarse esperando un `input()` de terminal (antes, retomar una URL ya procesada colgaba la corrida en el "¿Continuar esa sesión?");
  - corre sin buffer (`-u`, `PYTHONUNBUFFERED=1`): el log que muestra la web avanza en tiempo real en vez de a bloques de 8 KB.
- **Lectura de estado** (`state_reader.py`, `paso_detalle.py`): solo lectura de `pipeline_estado.json` y `trazas/`, con dos derivaciones de vista: sesiones previas a los pasos (chunks completados → pasos `ok`) y pasos `corriendo` sin corrida viva → `interrumpido` (se retoman con "Reanudar").

`app/paths.py` es el punto único que resuelve `PROJECT_ROOT`, parcha `sys.path` y fija el `cwd` del proceso a la raíz del repo — cualquier módulo nuevo que necesite `import pipeline` debe importar `app.paths` primero.

**Por qué también fija el `cwd`**: algunas funciones importadas de la raíz asumen que el proceso corre con `cwd` = raíz del repo, no solo que el módulo sea importable — ej. `_prepare_font()` (`edicion_video/agent4_video_cutter.py`) usa la ruta relativa `Path("stream_data")`, no una anclada a `PROJECT_ROOT`. Eso siempre fue cierto para `pipeline.py`/`revisar_clips.py` (se invocan desde la raíz), pero el backend arranca con `cwd=backend/`. Sin el `os.chdir(PROJECT_ROOT)` en `app/paths.py`, esas funciones terminan leyendo/escribiendo en `backend/stream_data/` en vez de la carpeta real — se detectó así durante las pruebas manuales de este v1 (apareció un `backend/stream_data/impact.ttf` espurio la primera vez que se ejerció el endpoint de editar un clip).

## Por qué "revisión post-hoc" y no pausar el pipeline en vivo

Ver `DECISIONES.md`. En corto: el backend siempre lanza el pipeline **sin** `--revisar` (auto-publica lo que el Agente 3 marcó `publicar`), y la revisión web (aprobar/editar/descartar) opera **después**, sobre los clips ya cortados — el mismo momento en el flujo que hoy cubre `revisar_clips.py`, solo que por API en vez de por `input()` de terminal.

## Numeración estable de clips (`clip_index.py`)

`revisar_clips.py` construye su lista de "clips a revisar" (`entradas`) una sola vez al arrancar y la recorre en un loop bloqueante — nunca necesita reconstruirla a mitad de camino. El backend, en cambio, resuelve cada acción (aprobar/editar/descartar) como un request HTTP independiente, y `build_clip_index()` se reconstruye desde disco en cada uno. Si numerara solo por `publicar == true`, descartar un clip corriría los números de los que le siguen en el mismo chunk — pero esos ya tienen archivo físico `clip_NNN.mp4` con el número viejo.

Por eso descartar un clip vía API no solo pone `publicar: false`: también marca `revision_descartado: true` en su entrada de `contenido_chunks/<chunk>.json`. `build_clip_index()` cuenta una entrada si tiene `publicar: true` **o** ese marcador, así que una entrada nunca pierde su posición en la numeración una vez que llegó a tener un clip cortado, así se descarte después. Editar un clip previamente descartado lo "resucita" (`publicar: true`, se borra el marcador).

**Desde 2026-09-30** el problema de fondo desapareció para sesiones nuevas: el pipeline corta cada chunk con prefijo propio (`clip_c002_01`) y guarda ese nombre como `clip_id` en la entrada, y `build_clip_index()` lo usa directo (`core/clip_ids.py::asignar_clip_ids()`). La numeración contada queda solo para sesiones viejas. Hizo falta porque con reintentos por paso, re-cortar un chunk intermedio con numeración global pisaba los clips de los chunks siguientes.

## `session_id` decidido por el backend

El backend genera el `session_id` (`YYYYMMDD_HHMMSS`, con sufijo si choca) y se lo pasa al pipeline con `--session-id`; `POST /runs` lo devuelve de inmediato. Reemplaza al mecanismo anterior de descubrirlo pollando `stream_data/` por el directorio nuevo, que fallaba al retomar una URL ya procesada (no aparece directorio nuevo) y con dos corridas lanzadas a la vez. Con `--session-id` la sesión es siempre `stream_data/<id>`, también para videos locales — así la web nunca crea la sesión junto al archivo.

## Registro de corridas persistente

Cada corrida queda en `backend/runs_logs/runs.json` (`run_id`, `pid`, `session_id`, `accion`, `cmd`, `log_path`, `inicio`, `returncode`) además de su log `<run_id>.log`. Si el backend se reinicia mientras una corrida está en curso, el subproceso sigue (grupo de procesos propio) y el backend la reconoce al volver sondeando el pid (`OpenProcess`/`GetExitCodeProcess` en Windows — `os.kill(pid, 0)` allí manda un CTRL_C_EVENT, no sirve para sondear). Lo único que se pierde es el código de salida: esa corrida se reporta `terminado` y el resultado real se lee de los pasos de la sesión.

Una sesión admite **una sola corrida viva** (`RunEnCursoError` → 409): dos procesos escribiendo el mismo `pipeline_estado.json` se pisarían. El pipeline escribe ese archivo de forma atómica (`.tmp` + `replace`) para que el backend nunca lea un JSON a medio escribir.

## Publicación (colas de TikTok y YouTube Shorts, `app/publicacion/`)

Todo clip **aprobado** en la Revisión entra a la cola de su nicho **en cada plataforma** (`review_actions._encolar_publicacion`; editar o descartar lo saca de todas las colas en las que no se envió). Cada `(plataforma, nicho)` es una cola independiente: su cuenta, sus horarios, su orden, sus pausas y errores; el motor revisa cuenta por cuenta, así que lo que pase en una no frena a la otra. Un motor dentro del backend (`motor.py`, hilo iniciado en el `lifespan` de `main.py`; `PUBLICACION_MOTOR=0` lo apaga) revisa al arrancar y cada 10 min y, si toca un horario, envía **un** clip a TikTok como **borrador a la bandeja** del usuario (Content Posting API, flujo *Upload*: sin auditoría de la app no se puede publicar directo en público). El usuario lo activa en la app. **El seguimiento termina cuando TikTok confirma `SEND_TO_USER_INBOX`**; si después se publica o no, no lo sigue este sistema. v1 envía solo el video (el endpoint de bandeja no acepta texto).

**YouTube Shorts** (youtube.py, YouTube Data API v3): cada clip sube con título, descripción y tags (publicacion.youtube_shorts del Agente 3, congelados en publicaciones.metadatos al encolar), directo como **público** (`youtube.VISIBILIDAD`). Google advierte que un proyecto no auditado queda bloqueado en privado: al terminar se lee la visibilidad real y, si no es la pedida, queda un evento de error en las trazas (el video igual cuenta como entregado). **El seguimiento termina cuando YouTube confirma uploadStatus = processed**. La cuenta se conecta por OAuth con vuelta directa al backend (/publicaciones/cuentas/youtube/callback: Google acepta http://localhost).

| Archivo | Qué hace |
|---|---|
| `db.py` | SQLite `backend/publicacion.db` (gitignored; `PUBLICACION_DB` la cambia). Tablas `cuentas`, `publicaciones`, `eventos`, `revisiones`, `oauth_estados`. |
| `horarios.py` | Regla pura: slot = último horario pasado (8/12/16/20, Lima); vigente hasta el siguiente o las 22:00; los perdidos no se recuperan; 2 h mínimas entre envíos; un clip por slot. |
| `cola.py` | Estados `en_cola → enviando → en_bandeja` (+ `error`, `sin_confirmar`, `cancelado`); cada cambio es un evento. |
| `cuentas.py` | Una cuenta por (plataforma, nicho): `conectada` / `pausada` (demasiados borradores pendientes; se reanuda sola a las 24 h) / `requiere_reconexion`. Modo `real` o `simulado`. |
| `tiktok.py` | Cliente real: init, subida por partes, sondeo de estado, OAuth (URL pegada: el redirect https no puede ser el backend local), renovación del token. |
| youtube.py | Cliente real de YouTube: subida reanudable (sesión → PUT → sondeo de processed), OAuth con callback, renovación del token. |
| 	exto.py | Texto de cada plataforma a partir del copy del Agente 3 (TikTok: para pegar; YouTube: lo que va por la API). |
| simulado.py | Mismo contrato sin red, para cualquier plataforma, para probar el panel (PUBLICACION_SIMULAR_FALLA). |
| `motor.py` | El tick: recuperar envíos huérfanos → reanudar pausas vencidas → decidir y enviar por cuenta → anotar la decisión. Revisa al arrancar y después **alineado al reloj** (xx:00, xx:10, xx:20…). |

**Hora de cada envío, exacta y predecible**: como las revisiones van en la grilla del reloj, `horarios.estimar()` simula las mismas reglas de `decidir()` y da, para cada clip en cola, la revisión en que sale y el horario que cubre. La separación de 2 h se cuenta desde la revisión en que salió el envío anterior (`habilitado_desde`), así la estimación y la decisión coinciden al minuto. El panel muestra "Próximo envío" y la columna "Sale" con eso; supone backend prendido y envíos sin error.

**Texto para pegar**: como el borrador llega sin texto, al encolar se guarda en `publicaciones.texto` la descripción de TikTok que escribió el Agente 3 (`publicacion.tiktok` del clip, con los # de su lista que falten agregados al final — `texto.py`). Queda congelado con el envío y el panel lo muestra con un botón Copiar para pegarlo al activar el borrador. Las publicaciones encoladas antes de esa columna se completan al arrancar el backend (`review_actions.completar_textos_publicacion`).

**Nunca dos veces el mismo horario ni el mismo clip**: `cola.reclamar()` es un `UPDATE` condicional y el índice único parcial `(plataforma, nicho, slot) WHERE estado IN (enviando, en_bandeja, sin_confirmar)` rechaza un segundo envío para el mismo slot, aunque corran dos procesos (uvicorn `--reload`). En el mismo proceso, un candado serializa los ticks.

**Nunca reenviar a ciegas**: el `publish_id` se guarda antes de subir y `subida_completa` se marca con el 201 de la última parte. Hasta ese 201 no existe borrador, así que cualquier falla previa es reintentable (vuelve a la cola, máx. 3 intentos). Después, solo un `FAILED` explícito de TikTok es definitivo; si no hay respuesta clara → `sin_confirmar` (acción manual). Si el proceso muere a mitad (enviando con un pid que ya no vive), el siguiente tick le pregunta a la plataforma (Publicador.recuperar) en vez de reenviar.

En YouTube el id del video recién existe al terminar la subida, así que lo que se guarda antes de subir es la **sesión de subida reanudable** (publicaciones.sesion_subida; nunca va a eventos ni al panel). Si el PUT se corta o responde 5xx, se le pregunta a la sesión (Content-Range: bytes */<size>): 200/201 = el video sí se creó (se toma el id, no se reenvía), 308/404 = no existe (vuelve a la cola), sin respuesta = sin_confirmar. La recuperación de huérfanos usa la misma consulta.
