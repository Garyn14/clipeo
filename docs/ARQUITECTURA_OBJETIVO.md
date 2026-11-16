# Clipeo v2 — Arquitectura objetivo

> Estado: **v0.3 aprobada** · Fecha: 2026-11-16
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
| 001 | **Python 3.12+** para todo | TS/Node | Aprobado — reutiliza piloto, WhisperX, yt-dlp, FFmpeg. |
| 002 | **Engine propio mínimo** sobre SQLite, con interfaz que permita migrar a Temporal/Prefect/Hatchet si escala | Prefect, Temporal, Celery+Redis, Dagster | Aprobado — cero infraestructura extra, encaja con "en espera" del operador IA y la revisión; el engine es además objetivo del producto. |
| 003 | **SQLite (WAL) + SQLAlchemy + Alembic**, **una base local por laptop** (ver ADR-015); migrar a Postgres en Fase 2–3 | Postgres desde el inicio; Postgres en la nube (free tier) | Aprobado — costo cero, un archivo, portable. |
| 004 | **Disco local** (volumen `./data` de Docker) para artefactos tras interfaz `Storage` | S3/R2 desde el inicio | Aprobado. |
| 005 | **IA por proveedor y por paso**; default `claude_code` (operador IA) en pasos de juicio | Solo API, solo open source | Aprobado — benchmark en Fase 6 del roadmap. |
| 006 | **Web local FastAPI + HTMX** para revisión | Streamlit, React SPA, solo CLI | Aprobado — previsualizar video en navegador, sin build de frontend. |
| 007 | **Ejecución en la laptop del operador dentro de Docker Compose** (Windows con Docker Desktop, o Linux) | VPS/nube; ejecución directa sin contenedor | Aprobado — costo cero; el operador cambia de laptop (ver ADR-015). |
| 008 | **Migración strangler**: piloto a `legacy/`, envolver agentes como steps, luego reescribir | Reescritura total | Aprobado — mantiene la producción de clips durante la migración. |
| 009 | **Publicación**: manual por defecto, `youtube_api` y `tiktok_inbox` (reconstruidos: el código de v1 no está disponible) | Control del navegador del operador | Aprobado — automatizar el navegador queda solo como respaldo. |
| 010 | **Calidad**: ruff + mypy + pytest + GitHub Actions (gratis en repos privados con cupo) | — | Aprobado. |

## 10. Requisitos no funcionales → cómo se cumplen

| RNF (TO-BE) | Mecanismo |
|---|---|
| 01 Costo ≈ 0 | ADR 002–007; medición de costo por StepRun y por clip |
| 02 IA intercambiable | Registro de proveedores por paso (§4) |
| 03 Extensible | Interfaces de adaptadores (§6); flows declarados en el dominio |
| 04 Portable | Docker Compose; sin rutas absolutas; assets en repo; scheduler interno; CI en Linux; ADR-015 |
| 05 Idempotente/reanudable | Claves de idempotencia, estados persistidos, reintentos (§3.2) |
| 06 Trazable | StepRun guarda entradas/salidas, versión de prompt, costo; historial de revisiones |
| 07 Seguro | `SecretStore`; `.env` solo para configuración no sensible |
| 08 Continuidad para agentes | `CLAUDE.md` + `docs/ESTADO.md` actualizados al cerrar cada tarea |
| 09 Multi-cliente | `Cliente` como raíz del modelo de datos desde el día 1 |

---

## 11. Módulos de calidad del clip (v0.2)

> Añadido tras la revisión del operador: la calidad del clip es la palanca principal del objetivo de 1M de vistas.
> Estos módulos reemplazan la cadena "Agente 1 marca un instante → Agente 4 corta" del piloto.

### 11.1 Estrategia de transcripción (sin GPU local)

La PC del operador no tiene GPU y Claude no transcribe audio, así que la transcripción se resuelve con proveedores `STTProvider` en cascada:

| Orden | Proveedor | Costo | Uso |
|---|---|---|---|
| 1 | **Groq Whisper API** | Plan gratuito con límites diarios (a verificar contra el volumen) | Principal: rápido, sin GPU. |
| 2 | **Colab / Kaggle como worker _pull_** | Gratis | El notebook **pide trabajos** a la cola (en vez de exponer un túnel efímero), transcribe con WhisperX en GPU y devuelve el resultado. Kaggle es respaldo de Colab. Notebook versionado en `colab/`. |
| 3 | **faster-whisper local en CPU** | Gratis | Último recurso: lotes nocturnos (el margen de 1 mes lo permite). |

Reglas: recortar silencios (VAD) antes de transcribir; transcribir una sola vez por contenido; diarización **opcional por cliente** (solo cuando hay varios hablantes relevantes).

### 11.2 Detección de momentos: candidatos multiseñal + selección de historia

```
transcripción ──┐
audio (energía, risas, gritos) ──┤
chat (lives, si disponible) ─────┼──▶ a. CANDIDATOS (determinista, barato) ──▶ b. SELECCIÓN DE HISTORIA (IA)
cambios de escena / caras ───────┘     ventanas con señales altas                  arcos completos:
                                                                                    contexto → tensión → remate
```

- **a. Candidatos**: cálculo sin IA que prioriza ventanas con señales altas; reduce lo que la IA tiene que leer.
- **b. Selección de historia**: la IA elige **arcos narrativos completos** (no instantes sueltos), con el libro de reglas del cliente inyectado.

### 11.3 Dirección editorial → lista de decisiones de edición (EDL)

Paso que **piensa** la edición y produce un documento estructurado (`EditDecisionList`, validado con Pydantic) que el render ejecuta sin decidir nada:

| Campo | Ejemplos |
|---|---|
| Estructura | `lineal`, **`gancho_primero`** (2–3 s del remate al inicio y luego "volvemos al principio"), `pregunta_respuesta` |
| Segmentos | Rangos de la fuente, en el orden de montaje; cortes de tiempos muertos (jump cuts) |
| Encuadre por segmento | `crop` con seguimiento de cara, `letterbox`, `splitscreen` (facecam + contenido), `imagen_relleno` |
| Capas | Texto de gancho (L1/L2), subtítulos (estilo), zoom en énfasis, marca de agua, música y efectos con su instante |
| Plataforma | Duración objetivo y variantes por plataforma |

Beneficios: el editor mejora sin tocar el render; la EDL se versiona y se etiqueta, así el ciclo de aprendizaje mide qué estructuras funcionan.

### 11.4 Control de calidad visual

Tras renderizar se extraen fotogramas clave y la IA (visión) verifica: el texto no tapa caras, el encuadre es correcto, no hay barras indeseadas, los subtítulos son legibles. Si falla → se corrige la EDL y se vuelve a renderizar (máx. N intentos) o se marca para el operador.

### 11.5 Ciclo de aprendizaje viral (analista semanal)

| Paso | Qué ocurre | Quién |
|---|---|---|
| 1. Etiquetar | Cada clip guarda sus rasgos: tipo de gancho, tema, emoción, estructura de la EDL, duración, personajes, formato, hora de publicación | Producción (automático) |
| 2. Medir | Métricas a 24 h, 72 h y 7 días, **normalizadas contra la línea base de la cuenta** | Flow `metricas` |
| 3. Analizar | **Bot analista semanal** (flow `aprendizaje`, programado): compara rasgos vs. rendimiento, con tamaño de muestra | Agente analista |
| 4. Reportar | Informe semanal: qué funcionó más, qué menos, hipótesis nuevas, reglas propuestas con evidencia (p. ej. "gancho de precio: 3× la línea base, n=8") | Agente analista |
| 5. Aprobar | El operador acepta / rechaza / edita cada regla | Operador (luego agente) |
| 6. Aplicar | Libro de reglas versionado en tres niveles (global / nicho / cliente), inyectado a selección de historia, dirección editorial y copy | Automático |
| 7. Experimentar | Variantes A/B del mismo clip (gancho, título, estructura) para probar hipótesis | Despacho |
| 8. Retirar | Reglas cuya evidencia se debilita se marcan para retiro | Agente analista |

Más una señal externa periódica: investigación de tendencias por plataforma (patrón del skill `seo-refresh`).

### 11.6 Conjunto de referencia (golden set)

Colección versionada de clips del piloto con su resultado real (incluido el de ~500K vistas) y de clips descartados. Cada cambio en detección, dirección editorial o prompts se evalúa contra este conjunto antes de integrarse (¿encuentra los mismos momentos? ¿mejor estructura?). Es el criterio objetivo para decir "mejoró".

### 11.7 Flow `produccion` actualizado

```
descargar → extraer audio → transcribir (cascada STT) → limpiar nombres → [hablantes] →
señales (audio, escena, chat) → candidatos → selección de historia (IA) → fan-out por clip →
dirección editorial / EDL (IA) → copy por plataforma (IA) → render → QA visual (IA) → revisión
```

### 11.8 Decisiones adicionales

| ADR | Decisión | Estado |
|---|---|---|
| 011 | Transcripción en cascada: Groq → Colab/Kaggle pull → CPU local | Aprobado |
| 012 | Edición basada en EDL: dirección editorial (piensa) separada de render (ejecuta) | Aprobado |
| 013 | Ciclo de aprendizaje con bot analista semanal y reglas con evidencia aprobadas por el operador | Aprobado |
| 014 | Golden set como criterio de aceptación de cambios de calidad | Aprobado |

### 11.9 Portabilidad entre laptops (ADR-015)

> Decisión del operador (2026-11-16): Docker con base de datos **local por laptop**.

| Qué | Dónde vive | Al cambiar de laptop |
|---|---|---|
| Código | GitHub | `git pull` |
| Configuración de clientes, perfiles editoriales y libro de reglas | **YAML versionado en el repo** (`knowledge/`), cargado a SQLite al iniciar | Viaja con `git pull` |
| Estado operativo (inventario, publicaciones, métricas, ejecuciones) | SQLite en `./data/` | `clipeo backup` → archivo → `clipeo restore` en la otra laptop |
| Videos fuente y clips | `./data/` (volumen de Docker) | Se regeneran o se copian si hace falta |
| Secretos | `.env` local (fuera del repo) | Se copia a mano una vez por laptop |

| ADR | Decisión | Estado |
|---|---|---|
| 015 | Docker Compose + SQLite local por laptop; conocimiento de clientes en YAML versionado; `backup`/`restore` del estado operativo | Aprobado |
