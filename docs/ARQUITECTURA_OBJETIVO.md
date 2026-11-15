# Clipeo v2 — Arquitectura objetivo

> Estado: **propuesta v0.1 para validación** · Fecha: 2026-11-15
> Parte de: [`DIAGNOSTICO_ACTUAL.md`](DIAGNOSTICO_ACTUAL.md) (AS-IS) → [`TO_BE.md`](TO_BE.md) (aprobado) → **este documento** → [`ROADMAP.md`](ROADMAP.md).
> Las decisiones se registran como ADR (§9); las marcadas *Propuesta* requieren OK del operador.

---

## 1. Principios de diseño

1. **Costo ≈ 0 primero** — todo corre en la PC del operador o en servicios gratuitos; nada de servicios de pago hasta tener ingresos.
2. **Engine sin dominio** — el engine no sabe qué es un clip ni un cliente; solo ejecuta pasos.
3. **Todo es un adaptador** — fuentes, plataformas de destino, proveedores de IA, transcripción y almacenamiento se enchufan detrás de interfaces.
4. **Estado en una base de datos, archivos pesados en disco** — el sistema de archivos deja de ser el bus de comunicación.
5. **Idempotente y reanudable** — cualquier paso se puede repetir sin duplicar clips ni publicaciones.
6. **Humano-en-el-bucle delegable** — la revisión es un paso más, que hoy resuelve el operador y mañana un agente.
7. **Migración incremental (strangler)** — se envuelve el piloto en el engine y se reemplaza pieza por pieza; el negocio no se detiene.
8. **Simple antes que escalable** — una sola aplicación Python, un proceso worker, SQLite. Escalar cuando haya clientes que lo paguen.

## 2. Vista general

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              INTERFACES                                  │
│   CLI `clipeo …`      Web local de revisión (FastAPI + HTMX)             │
│   Skills de Claude Code (operador IA, revisor, SEO, prospección)         │
└───────────────┬──────────────────────────────────────┬───────────────────┘
                │                                      │
┌───────────────▼──────────────────────────────────────▼───────────────────┐
│                     DOMINIO: SISTEMA DE CLIPS  (clips/)                  │
│  Clientes y objetivos · Ingesta · Producción · Revisión · Inventario     │
│  Despacho · Métricas · Aprendizaje · Prospección                         │
│  ── define FLUJOS y PASOS que el engine ejecuta ──                       │
└───────────────┬──────────────────────────────────────────────────────────┘
                │ registra flujos/pasos, encola ejecuciones
┌───────────────▼──────────────────────────────────────────────────────────┐
│                       ENGINE AGNÓSTICO  (engine/)                        │
│  Registro de pasos · Runner/worker · Estado de ejecuciones · Reintentos  │
│  Scheduler (jobs periódicos) · Artefactos · Medición de costo · Eventos  │
│  Registro de PROVEEDORES (interfaces): LLM · STT · Storage · …           │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│                         ADAPTADORES  (adapters/)                         │
│ Fuentes: YouTube · Kick · TikTok      Destinos: YT Shorts · TikTok · FB  │
│ LLM: Claude Code (operador) · Anthropic API · OpenAI-compatible (Ollama, │
│      Groq, OpenRouter, Gemini)        STT: WhisperX local · Colab remoto │
│ Storage: disco local (luego S3-compatible)     Render: FFmpeg            │
└──────────────────────────────────────────────────────────────────────────┘
        SQLite (estado)                     Disco (videos, clips, artefactos)
```

**Regla de dependencias:** `engine/` no importa nada de `clips/` ni de `adapters/`. `clips/` depende de `engine/` e interfaces; los adaptadores implementan interfaces. Se verifica con un test de arquitectura.

## 3. Engine agnóstico

### 3.1 Conceptos

| Concepto | Descripción |
|---|---|
| **Step** | Unidad de trabajo con nombre, versión, entrada y salida tipadas (Pydantic), política de reintentos y clave de idempotencia. Función pura respecto a sus entradas + proveedores inyectados. |
| **Flow** | Grafo dirigido (en la práctica, mayormente lineal con *fan-out*) de steps. Se declara en Python. |
| **Run** | Ejecución de un flow con una entrada concreta. Estados: `pendiente → en_curso → completado / fallido / en_espera`. |
| **StepRun** | Ejecución de un step dentro de un run. Guarda entrada, salida, intentos, error, duración y **costo**. |
| **Artefacto** | Archivo pesado (video, audio, transcripción) referenciado por URI en el storage, nunca embebido en la BD. |
| **En espera** | Estado para pasos que dependen de algo externo: respuesta del operador IA, revisión humana, aprobación de publicación. El run se reanuda cuando llega la señal. |
| **Fan-out** | Un step devuelve N elementos (ej. N candidatos de clip) y el flow continúa por cada uno. |
| **Schedule** | Disparo periódico de un flow (ej. ingesta cada 6 h, métricas cada 24 h, caducidad diaria). |
| **Proveedor** | Implementación inyectable de una interfaz (`LLMProvider`, `STTProvider`, `Storage`…), elegida por configuración y **por paso**. |
| **Costo** | Cada llamada a proveedor reporta su costo (tokens, segundos de GPU, S/); se agrega por step, run y clip. |

### 3.2 Ejecución

- **Cola en SQLite** (tabla de `step_runs` pendientes). Un proceso `clipeo worker` toma trabajo, lo ejecuta y persiste el resultado.
- **Reanudación**: al reiniciar, los StepRuns `en_curso` huérfanos vuelven a `pendiente`; los `completado` no se repiten (idempotencia por clave = hash de step + versión + entrada).
- **Reintentos** con backoff exponencial, configurables por step; errores clasificados en reintentables / definitivos.
- **Concurrencia**: 1 worker por defecto; N workers posibles sobre la misma BD (SQLite en modo WAL) cuando haga falta.
- **Scheduler**: el mismo proceso worker evalúa los schedules (sin cron del sistema operativo → portable Windows/Linux).

### 3.3 Interfaz mínima (ilustrativa)

```python
@step(name="detectar_momentos", version=1, retries=2)
def detectar_momentos(inp: Transcripcion, ctx: StepContext) -> list[Momento]:
    llm = ctx.provider("llm", purpose="deteccion")   # proveedor elegido por config
    resp = llm.complete(prompt=..., schema=MomentosSchema)  # salida validada
    return resp.data.momentos

produccion = Flow("produccion", steps=[descargar, transcribir, identificar_hablantes,
                                       detectar_momentos, refinar_rangos, puntuar_y_copy,
                                       renderizar, enviar_a_revision])
```

## 4. Capa de IA (proveedores LLM)

Generaliza `ai_client/` del piloto.

| Proveedor | Uso previsto | Cómo funciona |
|---|---|---|
| `claude_code` (**operador IA**) | Default MVP para pasos de juicio (detección, refinamiento, copy, revisión) | El step deja la petición en la tabla `llm_requests` y queda **en espera**. Una sesión de Claude Code ejecuta el skill `operador-ia`, procesa el lote de peticiones pendientes y escribe las respuestas; el engine reanuda los runs. Costo: suscripción existente. Encaja con el margen de 1 mes (procesamiento por lotes). |
| `anthropic` | Cuando haya ingresos | SDK oficial; costo medido por tokens. |
| `openai_compatible` | Pasos mecánicos y benchmark | Una sola implementación para Ollama (local), Groq, OpenRouter, Gemini (endpoint compatible), Together, etc. |

Comunes a todos:
- **Salida estructurada validada** con Pydantic; si no valida → reintento con el error de validación como feedback (reemplaza el parseo por regex del piloto).
- **Prompts versionados** como archivos en `clips/prompts/`, con su versión registrada en cada StepRun (permite comparar calidad por versión).
- **Contexto de cliente** (perfil editorial, entidades, aprendizajes) inyectado por el dominio, no por el proveedor.
- **Selección por paso** en config: `llm.deteccion = claude_code`, `llm.clasificacion = openai_compatible:ollama/qwen…`.

## 5. Dominio: sistema de clips

### 5.1 Modelo de datos (SQLite, migraciones con Alembic)

```
Cliente ─┬─ Objetivo (perfil editorial, KPI, cadencia=4/día, caducidad=30d, plataformas)
         ├─ Fuente* (plataforma, handle/url, activa, último chequeo)
         ├─ CuentaDestino* (plataforma, propietario: operador|cliente, tipo: cliente|captación,
         │                  modo publicación: api|asistido|manual, credencial_ref, salud/strikes)
         ├─ Conocimiento (entidades, eventos, aprendizajes)  ← migrado desde contexto/
         └─ Prospecto? (si aún no es cliente)

ContenidoFuente (fuente, url, fecha original, duración, estado de descarga, artefacto)
   └─ Clip* (rango, textos, score, copy por plataforma, artefacto render, versión de prompts,
             costo acumulado, frescura, estado)
          ├─ Revision* (decisión, editor: operador|agente, cambios, razón)
          └─ Publicacion* (cuenta destino, fecha programada/publicada, url, modo)
                 └─ Metrica* (fecha, vistas, likes, compartidos, comentarios)

Prospecto (handle, plataformas, clip gancho, mensaje, estado, historial de contacto)
Run / StepRun / LLMRequest / CostoRegistro   ← tablas del engine
```

### 5.2 Ciclo de vida del clip

```
candidato ──render──▶ en_revision ──aprobar──▶ en_inventario ──despacho──▶ programado ──▶ publicado
     │                    │  └──editar──▶ (re-render) ──▶ en_revision        │
     └──descartado◀───────┘                                                  │
                    en_inventario ──(30 días sin publicar)──▶ caducado        └──fallo──▶ en_inventario
```

### 5.3 Flujos

| Flow | Disparo | Pasos |
|---|---|---|
| `ingesta` | Schedule (ej. cada 6 h) por cliente | listar contenido nuevo de cada fuente → registrar `ContenidoFuente` → encolar `produccion` |
| `produccion` | Por cada contenido nuevo | descargar → extraer audio → transcribir → limpiar nombres → identificar hablantes → detectar momentos → refinar rangos → puntuar + copy según perfil → **fan-out por clip** → renderizar 9:16 → enviar a revisión (en espera) |
| `revision` | Señal del operador/agente | aplicar decisión → (re-render si hay edición) → inventario / descarte → registrar aprendizaje |
| `despacho` | Schedule (ej. cada hora) | por cliente y cuenta: ¿cupo del día disponible? → elegir mejor clip vigente (score × frescura) → publicar vía adaptador del modo de la cuenta |
| `metricas` | Schedule diario | leer estadísticas de publicaciones de los últimos N días → guardar `Metrica` |
| `caducidad` | Schedule diario | clips `en_inventario` con antigüedad > caducidad → `caducado` |
| `aprendizaje` | Schedule semanal / manual | métricas + revisiones → proponer reglas por cliente → aprobación del operador |
| `prospeccion` | Manual | prospecto → producir clip gancho → generar mensaje personalizado → en espera de envío manual → registrar estado |

### 5.4 Render (Agente 4 refactorizado)

Se separa el monolito de 1.273 líneas en: **análisis de la fuente** (letterbox, vertical, facecam), **plantilla de layout** (crop, letterbox, splitscreen, imagen de relleno), **capas** (texto, subtítulos animados, zoom de énfasis, marca de agua, música) y **compositor FFmpeg**. Plantillas y fuentes tipográficas en `assets/` dentro del repo (sin `C:\Windows\Fonts`).

## 6. Adaptadores

| Tipo | Interfaz | Implementaciones MVP | Notas |
|---|---|---|---|
| Fuente | `SourceAdapter.list_new(fuente, desde)`, `download(item)` | YouTube, Kick, TikTok (vía yt-dlp) | Respetar límites de frecuencia; lives = VOD/grabación, no tiempo real. |
| Destino | `Publisher.publish(clip, cuenta) -> Publicacion`, `fetch_metrics(publicacion)` | `manual` (paquete), `youtube_api`, `tiktok_inbox` (borrador → notificación) | Se reutiliza el código de publicación de la v1 que no está en el repo. FB Reels en Fase 2. |
| STT | `STTProvider.transcribe(audio) -> Transcripcion` | WhisperX local, Colab remoto (servidor versionado en el repo) | |
| Storage | `Storage.put/get/url` | Disco local | S3-compatible (R2/B2 free tier) cuando haga falta. |
| Credenciales | `SecretStore.get(ref)` | Archivo cifrado local / llavero del SO | Nunca en el repo ni en la BD en claro. |

## 7. Interfaces de usuario

| Interfaz | Uso | MVP |
|---|---|---|
| **CLI** `clipeo` | Alta de clientes/fuentes/cuentas, lanzar flows, worker, estado | Sí |
| **Web local de revisión** (FastAPI + HTMX, un solo proceso, `localhost`) | Ver clip, aprobar/editar/descartar, inventario, paquetes de publicación manual, reporte simple | Sí (mínima) |
| **Skills de Claude Code** | `operador-ia` (resolver peticiones LLM pendientes), `revisor` (futuro), `seo-refresh`, `prospeccion` | Sí |
| Panel completo / portal cliente | | Fase 2 / Fase 3 |

## 8. Estructura del repositorio

```
clipeo/
  CLAUDE.md                 ← punto de entrada para cualquier sesión (estado + mapa)
  pyproject.toml            ← dependencias fijadas, ruff, pytest, mypy
  docs/                     ← DIAGNOSTICO, TO_BE, ARQUITECTURA_OBJETIVO, ROADMAP, adr/, ESTADO.md
  engine/                   ← agnóstico: step, flow, runner, store, scheduler, providers (interfaces), costos
  clips/                    ← dominio: modelos, flows, steps, prompts/, revision, despacho, metricas, prospeccion
  adapters/                 ← sources/, publishers/, llm/, stt/, storage/, secrets/
  app/                      ← cli.py, web/ (FastAPI + HTMX)
  knowledge/                ← conocimiento por cliente (migrado desde contexto/ y aprendizajes/)
  assets/                   ← fuentes, música, marcas de agua, plantillas
  colab/                    ← servidor de transcripción versionado
  legacy/                   ← piloto v2.0 (congelado, solo referencia; se elimina al final)
  tests/                    ← unit, integración, arquitectura
  .claude/skills/           ← operador-ia, seo-refresh, prospeccion, …
```

## 9. Decisiones (ADR)

| ADR | Decisión | Alternativas consideradas | Estado |
|---|---|---|---|
| 001 | **Python 3.12+** para todo | TS/Node | Propuesta — reutiliza piloto, WhisperX, yt-dlp, FFmpeg. |
| 002 | **Engine propio mínimo** sobre SQLite, con interfaz que permita migrar a Temporal/Prefect/Hatchet si escala | Prefect, Temporal, Celery+Redis, Dagster | Propuesta — cero infraestructura extra, encaja con "en espera" del operador IA y la revisión; el engine es además objetivo del producto. |
| 003 | **SQLite (WAL) + SQLAlchemy + Alembic**; migrar a Postgres en Fase 2–3 | Postgres desde el inicio | Propuesta — costo cero, un archivo, portable. |
| 004 | **Disco local** para artefactos tras interfaz `Storage` | S3/R2 desde el inicio | Propuesta. |
| 005 | **IA por proveedor y por paso**; default `claude_code` (operador IA) en pasos de juicio | Solo API, solo open source | Propuesta — benchmark en Fase 6 del roadmap. |
| 006 | **Web local FastAPI + HTMX** para revisión | Streamlit, React SPA, solo CLI | Propuesta — previsualizar video en navegador, sin build de frontend. |
| 007 | **Ejecución en la PC del operador** (Windows) con soporte Linux; Docker opcional | VPS/nube | Propuesta — costo cero. |
| 008 | **Migración strangler**: piloto a `legacy/`, envolver agentes como steps, luego reescribir | Reescritura total | Propuesta — mantiene la producción de clips durante la migración. |
| 009 | **Publicación**: manual por defecto, `youtube_api` y `tiktok_inbox` reutilizando v1 | Control del navegador del operador | Propuesta — automatizar el navegador queda solo como respaldo. |
| 010 | **Calidad**: ruff + mypy + pytest + GitHub Actions (gratis en repos privados con cupo) | — | Propuesta. |

## 10. Requisitos no funcionales → cómo se cumplen

| RNF (TO-BE) | Mecanismo |
|---|---|
| 01 Costo ≈ 0 | ADR 002–007; medición de costo por StepRun y por clip |
| 02 IA intercambiable | Registro de proveedores por paso (§4) |
| 03 Extensible | Interfaces de adaptadores (§6); flows declarados en el dominio |
| 04 Portable | Sin rutas absolutas; assets en repo; scheduler interno; CI en Linux |
| 05 Idempotente/reanudable | Claves de idempotencia, estados persistidos, reintentos (§3.2) |
| 06 Trazable | StepRun guarda entradas/salidas, versión de prompt, costo; historial de revisiones |
| 07 Seguro | `SecretStore`; `.env` solo para configuración no sensible |
| 08 Continuidad para agentes | `CLAUDE.md` + `docs/ESTADO.md` actualizados al cerrar cada tarea |
| 09 Multi-cliente | `Cliente` como raíz del modelo de datos desde el día 1 |
