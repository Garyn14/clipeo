# API — referencia de endpoints

Base URL en desarrollo: `http://localhost:8000`. Todas las respuestas son JSON salvo el endpoint de video.

Glosario: un **paso** es una etapa del pipeline con estado propio (ver `docs/ARQUITECTURA.md` §3.0 de la raíz). Pasos de sesión: `descarga`, `plan`, `revision`, `fin`. Pasos por chunk: `transcripcion`, `agente0`, `agente1`, `agente2`, `juez`, `agente3`, `corte` (con memoria del nicho, `agente3` escribe el copy de lo que aprobó el juez). Estados: `pendiente | corriendo | ok | omitido | error | esperando`, más `interrumpido` (solo de lectura: un paso `corriendo` sin corrida viva).

## Config

### `GET /config/canales`
Lista los `canal_id` disponibles para el selector de "nueva corrida" (escanea `config/*.yaml`, `config/*/_index.yaml` y `contexto/nichos/*.yaml`, con la misma precedencia v2 > v1 que usa `pipeline.py::_load_config`).

```json
[{"canal_id": "zapatillas_peru", "descripcion": "Nicho de vendedores de zapatillas peruanos en TikTok/YouTube", "sistema": "v2"}, ...]
```

### `GET /config/env` · `PUT /config/env`
Estado / edición del set fijo de variables de `.env` (`COLAB_TRANSCRIBE_URL`, `COLAB_AUTH_TOKEN`, `AI_PROVIDER`, `ANTHROPIC_API_KEY`, `HF_TOKEN`). Los secretos se devuelven enmascarados.

## Runs (lanzar y trackear una corrida)

### `POST /runs`
Lanza `pipeline.py` como subproceso. Siempre sin `--revisar`; en modo `video` siempre con `--colab` y con un `--session-id` que genera el backend.

Body:
```json
{"modo": "video" | "test", "url_o_path": "https://... o stream_data/<session>/", "canal_id": "zapatillas_peru"}
```
Respuesta: `{"run_id": "...", "session_id": "20260930_120000"}`. 409 si esa sesión ya tiene una corrida viva (solo puede pasar en modo `test`).

### `GET /runs`
Todas las corridas registradas en `backend/runs_logs/runs.json` (sobreviven a reinicios del backend), más recientes primero.

### `GET /runs/{run_id}?lineas=40`
```json
{"run_id": "...", "estado": "corriendo" | "completado" | "fallido" | "terminado", "session_id": "...", "accion": "nueva" | "reanudar" | "reintentar agente3 (chunk_001)", "inicio": "ISO", "tail_log": "últimas N líneas"}
```
`terminado`: el proceso ya no existe pero el backend no vio su código de salida (se reinició mientras corría) — el resultado real está en los pasos de la sesión. 404 si `run_id` no existe.

## Sessions

### `GET /sessions`
Todas las carpetas de `stream_data/`, más recientes primero:
```json
{
  "session_id": "...", "url": "...", "config": "...", "modo": "automatico", "creado": "ISO",
  "estado": "corriendo" | "error" | "esperando_revision" | "finalizado" | "incompleto" | "sin_procesar",
  "paso_actual": {"chunk": "chunk_002" | null, "paso": "agente1", "estado": "error"} | null,
  "run_activo": "<run_id>" | null,
  "lead_time_s": 1234,
  "chunks_total": 3, "chunks_completados": 2, "chunks_fallidos": 1,
  "progreso": "...", "tiene_contenido_final": true, "clips_a_publicar": 4
}
```
`sin_procesar`: carpeta sin `pipeline_estado.json` (ej. una grabación de live aún no procesada). `progreso` se mantiene por compatibilidad con el frontend v1.

### `GET /sessions/{session_id}`
Incluye `video` (`{titulo, canal, duracion_s, miniatura}`, también en `GET /sessions`); en sesiones previas a ese bloque el detalle lo arma desde `metadata.json`.
Lo mismo más `pasos` (de sesión), `chunks` (cada uno con sus `pasos`) y `contenido` (`contenido_final.json`). Sesiones previas al seguimiento por pasos se muestran derivadas (chunks completados → pasos `ok`). 404 si la sesión no existe.

### `GET /sessions/{session_id}/runs`
Corridas de esa sesión, la más reciente primero (mismo formato que `GET /runs/{run_id}`).

### `GET /sessions/{session_id}/pasos/{chunk}/{paso}`
Detalle de un paso — lo que muestra el modal al hacer click en un círculo. `chunk` = `_` para pasos de sesión (ej. `/pasos/_/descarga`).
```json
{
  "session_id": "...", "chunk": "chunk_001", "paso": "agente2",
  "estado": "ok", "inicio": "ISO", "fin": "ISO", "duracion_s": 14.4, "intentos": 1, "nota": "1/5 rango(s) conservados",
  "error": {"tipo": "...", "mensaje": "...", "reintentable": true, "detalle": "<traceback>", "fecha": "ISO"} | null,
  "salidas": [{"ruta": "chunks/chunk_001/rangos.json", "existe": true, "bytes": 2048}],
  "llamadas": [{
    "n": 1,
    "request": {"modelo": "claude-sonnet-4-6", "system": "...", "mensajes": "..."},
    "response": {"texto": "...", "duracion_s": 13.1, "meta": {"proveedor": "claude_cli", "modelo": "sonnet", "duracion_api_ms": 12440, "usage": {...}}} | null,
    "error": {"tipo": "...", "mensaje": "...", "duracion_s": 600} | null
  }],
  "subpasos": [{"id": "video", "label": "Descarga del video", "estado": "corriendo", "detalle": null, "progreso": {"pct": 45.0, "bytes": 482344960, "total": 1071644672, "velocidad": 8600000, "eta_s": 70, "pista": 1, "pistas": 2}}],
  "historial": [{"tipo": "intento", "n": 1, "origen": "inicial", "resultado": "ok", "llamadas": [1, 1], "...": "..."}],
  "run_activo": false
}
```
`llamadas` sale de `trazas/<paso>/` (textos recortados a 60k caracteres): todas las de todos los intentos, y cada evento `intento` de `historial` dice qué rango de `n` le corresponde (schema completo en `docs/ESTRUCTURA_DATOS.md`). Sin run activo, un intento que quedó `corriendo` se devuelve como `interrumpido`. En el paso `juez` agrega `decisiones`: el veredicto por candidato de `chunks/<id>/juez.json` (`n, inicio, fin, publicar, linea1, linea2, tipo, en_juego, parecidos, fuerza, por_que`). 404 si el paso o el chunk no existen.

### `POST /sessions/{session_id}/reintentar`
```json
{"paso": "agente3", "chunks": ["chunk_001"]}
```
Lanza `pipeline.py ... --reintentar <paso> [--chunk ...]`: vuelve ese paso y los siguientes a pendiente, borra lo que produjeron y retoma. `chunks` vacío/omitido = todos los chunks con ese paso en error. Respuesta `{"run_id", "session_id"}`. 400 si el paso no existe o es `revision`/`fin`; 409 si hay una corrida viva sobre la sesión.

### `POST /sessions/{session_id}/reanudar`
Relanza la sesión sin resetear nada: corre los pasos pendientes/interrumpidos. Mismas respuestas que `reintentar`.

### `POST /sessions/reintentar-lote`
```json
{"items": [{"session_id": "...", "paso": "transcripcion", "chunk": "chunk_002"}, ...]}
```
Agrupa por (sesión, paso) y lanza una corrida por grupo. Devuelve `[{"session_id", "paso", "run_id"} | {"session_id", "paso", "error"}]` — dos grupos de la misma sesión no pueden correr a la vez: el segundo vuelve con error de corrida en curso.

### `POST /sessions/{session_id}/revision/finalizar`
Cierra los círculos Revisión → Fin. Exige que todos los chunks estén completos y que cada clip esté aprobado (`listo_para_publicar`) o descartado. Devuelve el detalle de la sesión. 409 con `{"detail": {"mensaje", "pendientes": ["clip_c001_02", ...]}}` si quedan clips sin decidir, o con un texto si la sesión tiene una corrida viva / chunks sin terminar.

## Errores

### `GET /errores?paso=&reintentable=&config=&desde=YYYY-MM-DD&hasta=YYYY-MM-DD`
Todos los pasos en `error` de todas las sesiones (vista "Instancias con error"):
```json
[{"session_id": "...", "config": "...", "chunk": "chunk_003" | null, "paso": "transcripcion", "tipo": "ColabError", "mensaje": "...", "reintentable": true, "fecha": "ISO", "intentos": 4, "run_activo": false}]
```

## Clips (galería + revisión)

Todos bajo `/sessions/{session_id}/clips`.

### `GET /`
Lista los clips marcados `publicar` (o previamente descartados vía esta misma API — ver nota de numeración en ARQUITECTURA.md), cada uno con:
```json
{
  "clip_id": "clip_c001_01",
  "score": 8,
  "texto_linea1": "...", "texto_linea2": "...",
  "hashtags": ["..."],
  "publicacion": {"tiktok": {...}, "youtube_shorts": {...}},
  "rango_original": {"inicio": "...", "fin": "...", "duracion_segundos": 45},
  "descartado": false,
  "tiene_video": true,
  "listo_para_publicar": false
}
```
Sesiones previas al 2026-09-30 usan `clip_id` con numeración global (`clip_001`).

### `GET /{clip_id}/video`
Sirve el `.mp4` (con soporte de range requests, para el `<video>` del navegador). 404 si no existe el archivo.

### `POST /{clip_id}/approve`
Marca `listo_para_publicar: true` en `clips/<clip_id>.json`. Sin body. 404 si el clip no existe o fue descartado (no tiene `.json`).

### `POST /{clip_id}/edit`
Re-corta con FFmpeg y registra el cambio como evento (`contexto/eventos/<YYYY-MM>/correccion_*.yaml`) — igual que la opción T/R/E de `revisar_clips.py`.
```json
{"canal_id": "zapatillas_peru", "texto_linea1": "...", "texto_linea2": "...", "inicio": "00:12:30", "fin": "00:13:15"}
```
Todos los campos opcionales salvo que al menos uno debería cambiar algo; los omitidos conservan su valor actual. 404 si el clip no existe; 500 si el re-corte con FFmpeg falla (el clip original no se pierde en ese caso — no se sobreescribe hasta que el corte nuevo sea exitoso... salvo que ya se validó `ok` antes de tocar el JSON, ver `review_actions.edit_clip`).

### `POST /{clip_id}/discard`
Borra `clips/<clip_id>.mp4` + `.json` y, si se da `razon`, registra el descarte como evento (`descarte_*.yaml`) — igual que la opción D de `revisar_clips.py`.
```json
{"canal_id": "zapatillas_peru", "razon": "chiste no aterriza sin contexto previo"}
```
`razon` es opcional (si se omite, se descarta sin dejar evento de aprendizaje, igual que en `revisar_clips.py`).

Aprobar además encola el clip para publicar (ver Publicaciones); editar o descartar lo saca de la cola si todavía no se envió.

## Publicaciones (cola de TikTok)

Prefijo `/publicaciones`. Ver `ARQUITECTURA.md` §"Publicación".

### `GET /resumen`
Por nicho: `cuenta` (sin tokens), `proximo_envio` (`{id, clip_id, titulo, sale, horario}`: cuándo sale el primero de la cola y qué horario cubre, con las reglas del motor), `proximo_envio_motivo` (por qué no hay estimación: sin cuenta / reconectar), `siguiente_libre` (cola vacía: cuándo saldría un clip aprobado ahora), `proximo_horario` (horario de la grilla, legado), `conteos` por estado, `dias_cola` (en cola ÷ horarios por día), `ultima_revision` del motor y `alertas` (`{nivel: warn|error, texto}`).

### `GET /?nicho=&estado=` · `GET /{id}`
Lista (cola primero, por orden; después historial, más reciente arriba). Las que están `en_cola` traen `sale_aprox` y `horario_estimado`. Todas traen `texto`: descripción + # para pegar en TikTok al activar el borrador (`null` si el clip no tiene copy). El detalle agrega `eventos`: cada llamada a TikTok y cada cambio de estado (`ts`, `tipo`, `mensaje`, `detalle` con `http`, `codigo`, `log_id`, `status`...). Nunca incluye tokens.

### `GET /revisiones?plataforma=&nicho=&limite=30`
Decisiones del motor ("horario de las 12:00 ya cubierto", "horario de silencio"...). Decisiones iguales seguidas se agrupan (`desde`, `hasta`, `veces`).

### `POST /{id}/mover` · `/{id}/quitar` · `/{id}/reintentar` · `/{id}/marcar-recibido`
`mover` con `{"direccion": "arriba" | "abajo"}`. `quitar`: en_cola/error → cancelado. `reintentar`: error/sin_confirmar/cancelado → al frente de la cola, intentos en 0. `marcar-recibido`: sin_confirmar → en_bandeja (verificaste en la app / YouTube Studio). 409 si la transición no aplica.

### `POST /acciones/revisar-ahora`
Lanza una revisión del motor en segundo plano (respeta horarios).

### `POST /acciones/enviar-ahora`
`{"nicho": "zapatillas_peru", "plataforma": "youtube"}`. Envía el primero de la cola de esa plataforma sin esperar horario (prueba); respeta cuenta pausada / a reconectar. Devuelve la publicación con sus eventos. 409 si no hay cuenta, cola vacía o cuenta no conectada.

### `POST /cuentas/simulada`
`{"nicho": "...", "plataforma": "..."}`. Conecta una cuenta de prueba: envíos simulados, sin red (fallas inyectables con `PUBLICACION_SIMULAR_FALLA`).

### `GET /cuentas/tiktok/autorizar?nicho=` · `POST /cuentas/tiktok/conectar`
El primero devuelve `{"url"}` para autorizar en TikTok (guarda el `state`, válido 30 min). El segundo recibe `{"nicho", "url_pegada"}`: la URL completa a la que TikTok devolvió al usuario; canjea el `code`, exige el permiso `video.upload` y deja la cuenta en modo real. 409 si faltan credenciales en Configuración.

### `GET /cuentas/youtube/autorizar?nicho=` · `GET /cuentas/youtube/callback`
El primero devuelve `{"url"}` para autorizar en Google (`access_type=offline`, `prompt=consent`; guarda el `state`, válido 30 min). Google devuelve al navegador al segundo, que valida el `state`, canjea el `code`, exige el permiso `youtube.upload`, lee el canal (`open_id` = id del canal, `nombre` = título) y redirige a `{FRONTEND_URL}/publicaciones/youtube?conexion=ok` o `?conexion=error&motivo=...`. 409 en el primero si faltan credenciales (`YOUTUBE_CLIENT_ID/SECRET`) en Configuración.

### `POST /cuentas/{id}/reanudar` · `POST /cuentas/{id}/horarios`
Reanuda una cuenta pausada. Horarios: `{"horarios": "8,12,16,20"}` (horas enteras antes de las 22).
