---
name: pipeline-manual
description: Corre el pipeline completo (pipeline.py --video) sin gastar la API real de Anthropic, con un agente de Claude Code respondiendo manualmente cada llamada que le tocaría a los Agentes 0-3, vía el protocolo de archivos de ai_client/. Usar cuando el usuario pida "probar el pipeline sin gastar la API", "modo manual", o algo similar con una URL real.
---

# Pipeline en modo manual (`AI_PROVIDER=manual`)

> **ARCHIVADA (2026-09-30).** El pipeline ya corre solo sin gastar la API: `AI_PROVIDER=claude_cli` (default) responde cada llamada con Claude Code headless — ver `docs/ARQUITECTURA.md` §16. El proveedor `manual` sigue existiendo solo para depuración. Se conserva este procedimiento como referencia histórica; no está en `.claude/skills/`, así que no se dispara.

Procedimiento para correr `pipeline.py --video <url> --config <canal_id>` de punta a punta sustituyendo las llamadas a la API real de Anthropic por respuestas que genera el propio agente de Claude Code, usando el protocolo de archivos de `ai_client/` (ver `docs/ARQUITECTURA.md` §16 para el mecanismo, `docs/COMANDOS.md` §4 para el comando de referencia).

## 1. Lanzar el pipeline

```bash
AI_PROVIDER=manual python pipeline.py --video "<url>" --config <canal_id> > /tmp/pipeline_run.log 2>&1
echo "EXIT=$?"
```

Correr en background (`run_in_background: true`). Notas:
- `AI_PROVIDER=manual` **fuerza automáticamente `--colab`** para la transcripción — no hace falta pasarlo. Requiere `COLAB_TRANSCRIBE_URL` configurada en `.env`; si no lo está, falla fuerte con un `RuntimeError` claro (no cae a WhisperX local en silencio).
- Si `pipeline.py` detecta una sesión previa con la misma URL, pregunta interactivamente `¿Continuar esa sesión? [S/n]` y se queda esperando stdin — en un proceso de background eso cuelga para siempre. Anteponer `echo "S" |` al comando desde el arranque para no tener que relanzar:
  ```bash
  echo "S" | AI_PROVIDER=manual python pipeline.py --video "<url>" --config <canal_id> > /tmp/pipeline_run.log 2>&1
  ```
- Si estás retomando una sesión donde un chunk quedó `"estado": "fallido"` en `stream_data/<session>/pipeline_estado.json` (ej. por un error de transcripción anterior), **no se reintenta solo** — `core/chunk_manager.py::get_pendientes()` solo procesa chunks en `"pendiente"`. Antes de relanzar, editar ese JSON a mano y cambiar `"estado": "fallido"` (borrando el campo `"error"`) por `"estado": "pendiente"`.

## 2. Vigilar `ai_client/_pending/`

Armar un `Monitor` (o loop de polling) que:
- Emita un evento por cada `*.request.json` nuevo en `ai_client/_pending/`.
- Emita un evento final cuando el log del pipeline muestre `EXIT=`, `Traceback`, o `PIPELINE COMPLETADO`.
- Si el usuario pidió estar atento a problemas de Colab/túnel, sumar al grep señales como `ConnectionError`, `Colab no respondi`, `WAF`, códigos `522|523|1033`, o el error específico visto antes (`sot_sequence`, típico de un notebook con el modelo mal cargado).

No hace falta releer YAMLs de contexto para responder — cada `request.json` ya trae el prompt completo (incluyendo todo el lore/reglas del nicho y la entidad) tal como se lo mandaría a la API real.

## 3. Identificar qué agente hizo la request y responder

Cada `<id>.request.json` tiene la forma exacta de los argumentos de `client.messages.create(...)`. Se puede identificar el agente de origen por la forma:

| Agente | Pistas en el JSON | Qué debe contener `response.json` |
|---|---|---|
| **Agente 0** (speaker ID) | `system` es un **string plano**; el `user content` menciona "TÍTULO", "ROSTER DE PERSONAJES" | `{"mapa": {...}, "confianza": {...}}` — mapear cada `SPEAKER_XX` a un nombre del roster solo con evidencia razonable; dejar sin identificar (confianza 0.0) si no hay certeza, nunca inventar. |
| **Agente 1** (picos) | No hay `system`; `messages[0].content` es una lista de 2 bloques de texto (prompt de detección + transcripción) | `{"picos": [{"timestamp", "razon", "confianza", "tipo", "personaje_detectado"?}, ...]}` — priorizar los tipos de momento que el prompt de nicho/entidad marca como de alto valor. |
| **Agente 2** (rangos, modo agrupado) | `system` es una **lista de bloques** con `cache_control`; el `user content` trae "Picos a refinar: N" | `{"rangos": [{"pico_timestamp", "conservar", "inicio", "fin", "duracion_segundos", "razon", "gancho"}, ...]}` — fusionar picos que cuenten la misma historia (marcar el descartado con `"conservar": false` y una razón), usar timestamps `HH:MM:SS`. |
| **Agente 3** (scoring + copy) | No hay `system`; el `user content` dice "RANGO A EVALUAR" | `{"score", "publicar", "texto_linea1", "texto_linea2", "hashtags", "razon_score", "mood", "estilo_texto", "cta_texto", "palabras_clave", "layout"}` — seguir al pie la letra las reglas de estilo/nombres canónicos/patrones de título que trae el prompt (suelen incluir reglas específicas por personaje, confirmadas por corrección editorial real). |

Escribir la respuesta en `ai_client/_pending/<id>.response.json`:
```json
{"text": "<el JSON de arriba, como STRING escapado — no un objeto anidado>"}
```

El campo `"text"` es literal lo que `resp.content[0].text` devolvería en una llamada real — por eso va como string, con el JSON interno escapado, no como objeto JSON anidado.

## 4. Cuidado con sesiones reales existentes

Si la sesión de `stream_data/` elegida para probar ya tenía datos reales de una corrida anterior (picos/rangos/contenido generados con la API real, usados como fixture), correr el pipeline en modo manual sobre ella **sobrescribe esos archivos**. Antes de reusar una sesión existente, confirmar si es descartable o si conviene copiarla aparte primero. Si se sobrescribe algo por error: `rangos.json` guarda el `pico_original` completo dentro de cada rango, así que a veces se puede reconstruir `picos.json` desde ahí sin pérdida real.

## 5. Al terminar

Reportar: clips generados (`stream_data/<session>/clips/clip_NNN.mp4` + `.json`), score y título de cada uno, y confirmar que `ai_client/_pending/` quedó vacío (sin archivos huérfanos).
