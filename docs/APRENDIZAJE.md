# Cómo Aprende el Sistema

Este documento explica los mecanismos de retroalimentación del pipeline: cómo el sistema incorpora resultados reales y correcciones humanas para mejorar sesiones futuras. Para el formato exacto de los archivos involucrados ver [ESTRUCTURA_DATOS.md §1](ESTRUCTURA_DATOS.md); para los comandos ver [COMANDOS.md](COMANDOS.md).

## 0. Lo primero que hay que entender: no hay entrenamiento de modelo

El sistema **no reentrena ni ajusta ningún modelo**. "Aprender" acá significa algo más simple y más verificable: **texto que se guarda en disco y se vuelve a inyectar en el prompt de una llamada futura a Claude**. Todo el aprendizaje del sistema es, en el fondo, gestión de qué texto se antepone a qué prompt y cuándo.

Esto importa porque hay **tres mecanismos distintos** que generan este tipo de retroalimentación, y **no todos se re-inyectan automáticamente**. Dos de ellos requieren que un humano revise lo guardado y lo promueva a mano a un YAML de contexto para que realmente cambie el comportamiento futuro. Confundir "se guardó un archivo" con "el sistema ya aprendió" es el error más fácil de cometer leyendo este pipeline — este documento distingue explícitamente cuál es cuál.

| Mecanismo | Dispara con | Guarda en | ¿Se re-lee solo en la próxima sesión? |
|---|---|---|---|
| **A. Feedback post-publicación** | `feedback.py` | `aprendizajes/<canal>_optimizado.md` | ✅ Sí — el Agente 3 lo carga siempre |
| **B. Corrección/descarte en revisión** | `pipeline.py --revisar` | `contexto/eventos/<mes>/correccion_*.yaml` / `descarte_*.yaml` | ❌ No — queda como bitácora |
| **C. Refresco de contexto externo** | `contexto_refresh.py` | `contexto/eventos/<mes>/refresh_*.yaml` | ❌ No — requiere curación manual |

Las secciones 1-3 desarrollan cada uno.

---

## 1. Mecanismo A — Feedback post-publicación (`feedback.py`)

Es el **único circuito cerrado automático** del sistema: lo que aprende acá se aplica solo, sin que nadie tenga que editar un YAML a mano.

### 1.1 Cuándo se usa

Después de publicar los clips de una sesión y esperar 24-48h a tener datos reales (vistas, comentarios, cómo reaccionó la audiencia), corrés:

```bash
python feedback.py --session 20260704_170532
```

### 1.2 Flujo paso a paso

1. `feedback.py` carga todos los clips de `clips/` y `clips_custom/` de esa sesión, junto a su metadata (`texto_linea1/2`, score del sistema).
2. Detecta el `canal_id` desde `pipeline_estado.json` de la sesión (o lo pide si no lo encuentra).
3. Por cada clip, pregunta si querés darle feedback. Si decís que sí, pide: tu propio score 1-10, la razón (qué viste vos que el sistema no consideró), y opcionalmente un título alternativo que hubieras preferido.
4. Con todos los feedbacks juntos, llama una vez a Claude (`_call_claude` en `feedback.py`) con un prompt que le pide **destilar** ese feedback en dos salidas:
   - un **registro completo** en lenguaje natural (para el historial),
   - una **regla resumida** (máx. 2 líneas, accionable), y
   - un booleano `es_generalizable`: si el feedback aplica solo a ese clip puntual o si es un patrón que vale la pena recordar para el nicho en general.
5. Te muestra la propuesta y pide aprobación (`[S/n]`) y, opcionalmente, la oportunidad de editar la regla resumida antes de guardarla.
6. Si aprobás, escribe:
   - **siempre** en `aprendizajes/<canal_id>.md` (append del registro completo con fecha y sesión — historial, nunca se relee),
   - **solo si `es_generalizable`** en `aprendizajes/<canal_id>_optimizado.md` (agrega la regla bajo el encabezado `## Aprendizajes de feedback`).

### 1.3 Cómo se re-inyecta

`agent3_viral_scorer.py::run_agent()` busca al arrancar `aprendizajes/<canal_id>_optimizado.md`. Si existe, lo carga entero y lo concatena al prompt de contenido como bloque cacheado (`cached_context`), bajo el encabezado `REGLAS ACTIVAS DEL NICHO:`, antes de evaluar cualquier clip. Esto pasa **en cada corrida futura** de ese canal — no hace falta tocar nada más.

### 1.4 Ejemplo real en este repo

`aprendizajes/zapatillas_peru.md` registra (2026-06-11) que un clip con título `"Fritz vs Tío Marín: 599 vs 99.90 / y encima viene con waterproof"` recibió score 9/10 del sistema y 8-9/10 del usuario, con el comentario de que el formato de "Marca A vs Marca B con precios concretos" generaba debate inmediato, y que L1 nombrando ambas referencias directamente rendía mejor que dejar el precio solo en L2.

Esa observación fue destilada en dos reglas concretas que hoy viven en `aprendizajes/zapatillas_peru_optimizado.md` bajo `## Aprendizajes de feedback`:
```
- En clips de comparación de marcas, usa precios exactos con céntimos (...) en L1 para maximizar
  credibilidad y debate; añade en L2 un feature diferencial inesperado con emoji de sorpresa...
- En comparativas de precio, L1 debe nombrar AMBAS referencias (marca/vendedor + precios)
  directamente; evitar L1 genéricos tipo 'la verdadera tecnología'...
```
Estas dos líneas se inyectan literalmente en el prompt del Agente 3 cada vez que se procesa una sesión con `--config zapatillas_peru`.

### 1.5 El manifiesto raíz — `aprendizajes.md`

En la raíz del proyecto (no dentro de la carpeta) hay un `aprendizajes.md` que no es de un canal específico: explica el propósito de la carpeta y reserva una sección de **"patrones universales confirmados en más de un nicho"** — para cuando el mismo patrón (ej. "claim verificable + rivalidad") se confirme independientemente en dos nichos distintos, promoverlo ahí. Hoy está vacío; es un espacio de trabajo manual, no algo que el código lea o escriba automáticamente.

---

## 2. Mecanismo B — Corrección y descarte durante la revisión (`--revisar`)

### 2.1 Cuándo se usa

Al correr `pipeline.py` con `--revisar`, antes de cortar cada clip con el Agente 4 se te muestra el clip candidato (score, rango, título propuesto) y podés: aprobar, editar solo el título, editar solo el rango, editar ambos, o descartar con una razón (ver COMANDOS.md y ARQUITECTURA.md §10 para el detalle de la interacción).

### 2.2 Qué se guarda

- Si corregiste título y/o rango (`T`, `R` o `E`), `pipeline.py::_guardar_evento_correccion()` escribe `contexto/eventos/<YYYY-MM>/correccion_<nicho>_<hora>.yaml` con el título original y corregido, el rango original y corregido, y una frase `aprendizaje` autogenerada tipo *"El sistema propuso el título 'X' pero el editor corrigió a 'Y' | El sistema propuso el rango A→B pero el editor corrigió a C→D"* (solo la parte que efectivamente cambió). Antes solo `T`/`E` generaban evento y únicamente para el título — `R` no guardaba nada, y `E` guardaba el rango *viejo* por un bug de orden. Ambos casos ya están corregidos.
- Si descartaste un clip con razón (`D` + texto), `_guardar_evento_descarte()` escribe `contexto/eventos/<YYYY-MM>/descarte_<nicho>_<hora>.yaml` con el texto/score descartado y la razón.

Este comportamiento es independiente de si el canal usa config v1 o v2 — los eventos siempre se guardan bajo `contexto/eventos/`, incluso para canales que resuelven vía `ConfigLoader` v1.

### 2.3 ⚠ Por qué esto NO es un circuito cerrado (todavía)

`ContextLoader.load_nicho()` sí lee todos los eventos de las entidades de un nicho al ensamblar la config (quedan disponibles en `config["eventos"]`) — pero **ningún agente (1, 2 o 3) lee esa clave hoy**. A diferencia de `aprendizajes/*_optimizado.md`, que el Agente 3 carga explícitamente, los eventos de corrección/descarte no tienen ningún código que los convierta de vuelta en texto de prompt.

En la práctica esto significa: correr `--revisar` te deja una **bitácora fechada y estructurada** de qué corrigió el editor y por qué — útil para auditoría, y como materia prima para que un humano, al notar un patrón repetido en varios eventos, lo copie a mano al bloque `deteccion_adicional` o `contenido_adicional` del YAML de la entidad correspondiente (mismo mecanismo de promoción manual que en el Mecanismo C, sección 3.3). No es, hoy, retroalimentación automática.

---

## 3. Mecanismo C — Refresco de contexto externo (`contexto_refresh.py`)

Este es **el comando para "enriquecer" el contexto** al que probablemente te referís: a diferencia de A y B (que nacen de resultados/decisiones dentro del propio pipeline), este busca información **fuera** del sistema — noticias y novedades recientes sobre un personaje — y la deja disponible como contexto candidato.

### 3.1 Cuándo se usa

Cuando querés refrescar el conocimiento sobre una entidad del Módulo Contexto v2 (`contexto/entidades/`) con hechos recientes que Claude no tendría en su prompt base — una polémica nueva, un evento viral, un cambio de negocio.

```bash
python contexto_refresh.py fritz
python contexto_refresh.py sideral --max-busquedas 8
```

### 3.2 Flujo paso a paso

1. Carga `contexto/entidades/<entidad_id>.yaml` (lore actual de la entidad) y busca en qué nicho(s) aparece listada (`contexto/nichos/*.yaml`) para dar contexto del ecosistema al prompt de búsqueda.
2. Arma un `system_prompt` describiéndole a Claude quién es la entidad y le pide investigar noticias/eventos de las **últimas 4 semanas**, usando la *tool* de búsqueda web nativa de la API (`web_search_20260209`), con un tope de búsquedas (`--max-busquedas`, default 3).
3. Claude devuelve hasta 3 hallazgos priorizados por relevancia, cada uno con `titulo`, `descripcion`, `fecha_aproximada`, `relevancia` y `fuente`.
4. Por cada hallazgo, se te muestra y se pregunta `[S/n]` si querés guardarlo.
5. Los aprobados se guardan como `contexto/eventos/<YYYY-MM>/refresh_<entidad>_<hora>.yaml` (tipo `refresh_noticia` — ver ESTRUCTURA_DATOS.md §1.2).

### 3.3 ⚠ Esto tampoco se re-inyecta solo — requiere un paso manual

Igual que el Mecanismo B, estos eventos quedan en `config["eventos"]` sin que ningún agente los lea. Para que un hallazgo de `contexto_refresh.py` realmente cambie qué detecta o cómo redacta el sistema, alguien tiene que **copiarlo a mano** al `deteccion_adicional.prompt` o `contenido_adicional` de `contexto/entidades/<entidad_id>.yaml` (o a `deteccion_adicional`/`contenido_adicional` del YAML de personaje en v1).

### 3.4 Ejemplo real de esta promoción manual, ya ocurrida en este repo

`contexto/eventos/2026-06/fritz_tecnologia_599.yaml` registra que el clip *"El Tío Fritz muestra la verdadera tecnología de 599.00 a 99.90"* alcanzó 81K vistas — el resultado más alto confirmado del sistema — con el aprendizaje de que "meme establecido + dato que lo contradice" es la fórmula más poderosa para ese nicho.

Ese hallazgo fue promovido a mano dentro de `contexto/entidades/fritz.yaml`, en dos lugares distintos:
- `deteccion_adicional.prompt`, que ahora dice explícitamente: *"El meme de 'tecnología' es el contenido MÁS VIRAL confirmado de este personaje — 81K vistas..."* como señal de alto valor para el Agente 1.
- `contenido_adicional.tono`, que documenta el "PATRÓN GANADOR CONFIRMADO FRITZ (81K vistas)" con el ejemplo textual exacto, para que el Agente 3 lo replique.

Este es el patrón a seguir cuando curás eventos de `contexto_refresh.py` (o de correcciones/descartes del Mecanismo B) manualmente: el evento vive en `contexto/eventos/` como registro fechado del hallazgo, y su versión resumida/accionable se copia al `deteccion_adicional`/`contenido_adicional` de la entidad para que efectivamente afecte prompts futuros.

---

## 4. Un cuarto concepto que NO es aprendizaje — el enriquecimiento en tiempo de ejecución

Vale aclarar esto porque el nombre del método puede confundir: `ConfigLoader.enrich_with_speakers()` (usado en config v1 tipo ecosistema) también se llama "enriquecer", pero es un mecanismo completamente distinto y **no persiste nada**. En cada chunk, cuando el Agente 0 identifica qué personajes hablaron, este método mezcla en memoria el YAML de esos personajes específicos al config del canal — para esa llamada nada más. No escribe ningún archivo, no se acumula entre sesiones, y no tiene relación con el feedback humano. Es composición de prompt por chunk, no memoria de largo plazo. La memoria de largo plazo real es la de las secciones 1-3.

---

## 5. Ciclo de vida completo, de punta a punta

```
Sesión se procesa (pipeline.py --video, opcionalmente --revisar)
        │
        ├─▶ [B] Editor corrige/descarta en vivo ──▶ contexto/eventos/*/correccion_*.yaml
        │                                            contexto/eventos/*/descarte_*.yaml
        │                                            (bitácora — requiere promoción manual)
        │
        ▼
Clips publicados (fuera del sistema, manual)
        │
        ▼
24-48h después: resultados reales (vistas, comentarios)
        │
        ▼
python feedback.py --session <id>          [A]
        │
        ├─▶ aprendizajes/<canal>.md              (historial, siempre)
        └─▶ aprendizajes/<canal>_optimizado.md   (solo si generalizable)
                    │
                    ▼
        Agente 3 lo carga automáticamente en CADA sesión futura de ese canal
                    │
                    ▼
        Clips futuros con mejor copywriting, sin tocar código ni YAML


En paralelo, cuando corresponde:

python contexto_refresh.py <entidad>         [C]
        │
        ▼
contexto/eventos/*/refresh_*.yaml   (bitácora — requiere promoción manual)
        │
        ▼
Humano revisa el evento y, si vale la pena, copia el hallazgo
a contexto/entidades/<entidad>.yaml (deteccion_adicional / contenido_adicional)
        │
        ▼
ContextLoader lo carga en CADA sesión futura de ese nicho
```

**En resumen**: hoy el sistema tiene un aprendizaje verdaderamente automático (A, vía `feedback.py`), y dos bitácoras de señales (B y C) que sirven de materia prima para que un humano actualice a mano el lore de una entidad — momento en el cual sí pasan a afectar todas las sesiones futuras de ese nicho.
