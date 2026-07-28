# Estructura de Datos y Contextos

Este documento explica **qué contiene cada archivo** que el pipeline lee o escribe: los YAML de configuración/contexto que dirigen a los agentes, y los JSON que fluyen entre etapas dentro de una sesión. Para cómo se ejecuta cada comando ver [COMANDOS.md](COMANDOS.md); para cómo encajan los componentes entre sí ver [ARQUITECTURA.md](ARQUITECTURA.md).

---

## Parte 1 — Configuración y Contexto (qué le dice al sistema cómo pensar)

Hay **dos sistemas paralelos** que producen el mismo tipo de resultado (un dict de config en memoria), con formatos de archivo distintos. `pipeline.py` elige uno automáticamente según qué exista para el `canal_id` pedido.

### 1.1 Sistema v1 — carpeta `config/` (`ConfigLoader`)

**Archivo único** — un canal simple, sin múltiples personajes. Ejemplo: `config/default.yaml`, `config/zapatillas_peru.yaml`.

Esquema:

```yaml
meta:
  id: <string>              # identificador del canal
  descripcion: <string>
  plataforma: <string>
  activo: <bool>
  version: <string>

identificacion:              # umbrales para el Agente 0 (clasificación de speakers)
  umbral_alto: <float 0-1>    # confianza ≥ esto → nombre confirmado y usado
  umbral_bajo: <float 0-1>    # confianza ≥ esto (pero < alto) → "posible", no se usa el nombre

deteccion:                    # Agente 1
  confianza_minima: <float 0-1>   # picos por debajo de esto se descartan
  prompt: <string largo>          # system/user prompt de detección de picos

refinamiento:                 # Agente 2
  contexto_antes_segundos: <int>
  contexto_despues_segundos: <int>
  duracion_minima_segundos: <int>
  duracion_maxima_segundos: <int>
  prompt: <string largo>

contenido:                     # Agente 3
  score_minimo_publicar: <int 1-10>
  hashtags_base: [<string>, ...]
  prompt: <string largo>

contenido_restricciones:       # opcional — Agente 3 regenera si detecta estas palabras
  palabras_prohibidas: [<string>, ...]
  reemplazos_sugeridos: {<palabra>: [<sugerencia>, ...]}

publicacion:                   # informativo, no lo consume ningún agente todavía
  plataformas: [<string>, ...]
  horario: <string>
  descripcion_base: <string>
```

**Ecosistema** — varios personajes bajo un mismo canal (ej. `config/streamers_peru/`). Es una carpeta con:

- `_index.yaml`: mismo esquema de arriba, más una lista `personajes`:
  ```yaml
  personajes:
    - id: sideral
      nombres: ["Sideral", "SiDeRaL", "Jesús Luján", "BebaArmy", ...]  # alias, el [0] es el canónico
  ```
- `<personaje_id>.yaml` por cada personaje (ej. `sideral.yaml`), con su propio lore:
  ```yaml
  meta: {id, nombre, nombre_real, apodos, ecosistema, plataformas}
  lore:
    origen: <string>
    personajes_universo: [{nombre, rol, relevancia}, ...]   # personajes secundarios de SU universo
    polemicas: [{titulo, descripcion, tipo}, ...]
    vocabulario: [{termino, significado}, ...]
  deteccion_adicional:
    prompt: <string>          # se concatena al prompt de detección SOLO cuando este personaje habla
  contenido_adicional:
    hashtags: [<string>, ...] # se suman a hashtags_base sin duplicar
    tono: <string>            # se agrega como prompt_adicional_contenido
  ```

**Cómo se combina**: el `_index.yaml` se carga siempre. El YAML de un personaje solo se mezcla al detectarse que ese personaje habló en el chunk actual (vía Agente 0 → `enrich_with_speakers()`, que hace match de nombres detectados contra los `nombres` de `personajes` en `_index.yaml`). Esto evita meter en el prompt el lore de los 10 streamers del ecosistema cuando el chunk solo tiene a 2 hablando.

### 1.2 Sistema v2 — carpeta `contexto/` (`ContextLoader`)

Más granular, tres niveles de archivos que se ensamblan siempre por completo (sin lazy-loading por speaker detectado, a diferencia de v1):

**`contexto/nichos/<nicho_id>.yaml`** — la unidad que se le pasa a `--config`. Define el nicho y qué entidades pertenecen a él:

```yaml
nicho:
  id: <string>
  descripcion: <string>
  entidades: [fritz, noto, ...]     # ids que apuntan a contexto/entidades/<id>.yaml
  identificacion: {umbral_alto, umbral_bajo}

deteccion_base:        { confianza_minima, prompt }   # base del Agente 1
contenido_base:        { score_minimo_publicar, hashtags_base, prompt }   # base del Agente 3
refinamiento_base:     { contexto_antes_segundos, contexto_despues_segundos,
                          duracion_minima_segundos, duracion_maxima_segundos, prompt }   # base del Agente 2
```

**`contexto/entidades/<entidad_id>.yaml`** — lore de una entidad/personaje, referenciada desde uno o más nichos:

```yaml
entidad:
  id: <string>
  nombre: <string>
  nombre_real: <string>
  apodos: [<string>, ...]
  plataformas: [<string>, ...]
  handles: {tiktok, youtube, instagram}   # opcional

lore:
  descripcion: <string>
  personajes_universo: [{nombre, rol, relevancia}, ...]
  polemicas / polémicas: [{titulo, descripcion, tipo}, ...]
  vocabulario: [{termino, significado}, ...]
  meme_principal: {descripcion, señales_virales: [...]}   # opcional, visto en noto.yaml

deteccion_adicional:
  prompt: <string>     # se concatena SIEMPRE (no condicionado a detección de speaker) al prompt de detección del nicho

contenido_adicional:
  hashtags: [<string>, ...]
  tono: <string>        # se concatena al prompt de contenido del nicho

identificacion: {umbral_alto, umbral_bajo}   # opcional, puede sobreescribir el del nicho
```

Diferencia clave con v1: en v2 **todas** las entidades listadas en el nicho se mezclan siempre al ensamblar la config (`ContextLoader._assemble()`), sin esperar a que el Agente 0 detecte quién habla. Es apropiado para nichos pequeños (2-3 entidades) donde cargar todo el lore de entrada es barato; para ecosistemas grandes (10 streamers) esto sería costoso en tokens, por eso ese caso sigue en v1.

**`contexto/relaciones/relaciones.yaml`** — pensado para documentar relaciones *cross-nicho* entre entidades (ej. una rivalidad entre un personaje de `zapatillas_peru` y uno de otro nicho). Existe el archivo pero hoy está vacío (`relaciones: []`) y **no es leído por ningún loader ni agente** — es un punto de extensión reservado, no una funcionalidad activa.

**`contexto/eventos/<YYYY-MM>/<entidad_id>_*.yaml`** — bitácora de hechos puntuales fechados sobre una entidad. Tres orígenes posibles, mismo directorio:

1. **Automáticos del pipeline** (`pipeline.py` en modo `--revisar`): `correccion_<nicho>_<hora>.yaml` (el editor corrigió título y/o rango) o `descarte_<nicho>_<hora>.yaml` (el editor descartó un clip con razón), con esquema:
   ```yaml
   evento:
     tipo: correccion_titulo | correccion_rango | correccion_titulo_y_rango | descarte_manual
     fecha: <YYYY-MM-DD>
     nicho: <nicho_id>
     titulo_original / titulo_corregido: {linea1, linea2}   # no en descarte_manual
     rango_original / rango_corregido: {inicio, fin}         # no en descarte_manual
     clip_descartado: {linea1, linea2, score}                # solo en descarte_manual
     razon_descarte: <string>                                # solo en descarte_manual
     rango: {inicio, fin, duracion_segundos, ...}   # snapshot completo del rango propuesto por Agente 2 (contexto extra, no solo inicio/fin)
     aprendizaje: <string>   # frase auto-generada resumiendo el/los cambio(s); si hay corrección de título Y de rango, ambas frases van concatenadas con " | "
   ```
   Solo se guarda evento si algo cambió realmente respecto a lo propuesto por el Agente 3 (título) o el Agente 2 (rango) — aprobar sin editar no genera archivo.
2. **De búsqueda web** (`contexto_refresh.py`): `refresh_<entidad>_<hora>.yaml`:
   ```yaml
   evento:
     tipo: refresh_noticia
     entidad: <entidad_id>
     nicho: <nicho_id o null>
     fecha_evento: <string>       # fecha aproximada del hallazgo real
     fecha_registro: <YYYY-MM-DD> # fecha en que se guardó
     titulo / descripcion / relevancia / fuente: <string>
   ```
3. **Curados manualmente** (editados a mano, ej. `fritz_tecnologia_599.yaml`, `noto_multa_indecopi.yaml`): mismo espíritu pero sin un esquema estrictamente forzado — típicamente `entidad`, `fecha`, `titulo`, `descripcion`, `resultado_real` o `relevancia`, `aprendizaje`. Sirven para registrar a mano un resultado real de un clip publicado (vistas, si se viralizó) que informa qué priorizar a futuro.

**⚠ Nota importante**: `ContextLoader.load_nicho()` sí lee todos los eventos de todas las entidades del nicho y los deja disponibles en `config["eventos"]`, pero **ningún agente (1/2/3) lee ni inyecta hoy ese contenido en sus prompts** — a diferencia de las carpetas `entidades/` (cuyo `deteccion_adicional`/`contenido_adicional` sí se mezclan en los prompts). Los eventos existen como bitácora consultable y como insumo para curar a mano el YAML de la entidad (ej. copiar un patrón confirmado al bloque `deteccion_adicional`), no como inyección automática. El mecanismo que sí retroalimenta prompts automáticamente es el de `aprendizajes/` (ver 1.3).

### 1.3 `aprendizajes/` — reglas destiladas de feedback humano

No es config inicial sino **memoria acumulada que se retroalimenta al Agente 3** después de publicar clips y evaluarlos (`feedback.py`). Dos archivos por canal:

- **`aprendizajes/<canal_id>.md`** — historial completo, append-only, en lenguaje natural. Cada corrida de `feedback.py` agrega una sección con fecha, texto generado por el sistema vs. corrección humana, y el análisis de Claude sobre por qué funcionó o no. Es para trazabilidad/lectura humana — **no se carga en ningún prompt**.
- **`aprendizajes/<canal_id>_optimizado.md`** — solo reglas que Claude marcó como *generalizables* (no específicas de un clip puntual), en formato de lista corta bajo encabezados temáticos (`## Estilo de texto del clip`, `## Aprendizajes de feedback`, etc.). **Este sí se carga por el Agente 3** (`agent3_viral_scorer.py::run_agent()`) y se inyecta en el bloque cacheado del prompt como "REGLAS ACTIVAS DEL NICHO" — es lo que hace que el sistema mejore su copywriting con el tiempo sin tocar el YAML de config.
- **`aprendizajes.md`** (en la raíz, no dentro de la carpeta) es un manifiesto corto, no datos de un canal: explica el propósito de la carpeta y reserva un espacio para "patrones universales confirmados en más de un nicho" — hoy vacío, pendiente de los primeros datos cruzados entre nichos.

### 1.4 Cómo se relacionan los tres sistemas de "saber del dominio"

| | `config/<ecosistema>/<personaje>.yaml` (v1) | `contexto/entidades/<id>.yaml` (v2) | `aprendizajes/<canal>_optimizado.md` |
|---|---|---|---|
| Origen | Escrito a mano por el operador | Escrito a mano por el operador | Generado por Claude a partir de feedback humano |
| Cuándo se mezcla | Solo si el Agente 0 detecta que ese personaje habló | Siempre, para todas las entidades del nicho | Siempre, en cada llamada del Agente 3 |
| Qué aporta | Lore + lenguaje/hashtags específicos del personaje | Lore + lenguaje/hashtags específicos de la entidad | Reglas de estilo/formato validadas por resultados reales |
| Se actualiza con | Edición manual del YAML | Edición manual del YAML + eventos curados a mano | `feedback.py` (automático tras aprobación humana) |

### 1.5 Nota sobre `personajes` y limpieza de nombres bajo v2

`transcript_cleaner.py` (corrección fonética de nombres) y la lógica de detección/exclusión de personajes por rango del Agente 3 (`_detect_personajes_in_range`) dependen de `config.get("personajes")`. En **v1** ese campo viene poblado (lista de `{id, nombres}` desde `_index.yaml`). En **v2**, `ContextLoader._assemble()` siempre devuelve `"personajes": []` — el equivalente conceptual son las `entidades`, pero bajo una clave distinta (`config["entidades"]`) que esas dos piezas de código no leen. En la práctica esto significa que, para un nicho resuelto vía v2 (como `zapatillas_peru`, que hoy tiene tanto `config/zapatillas_peru.yaml` como `contexto/nichos/zapatillas_peru.yaml` — y v2 gana la resolución — la limpieza automática de nombres mal transcritos y el scoping de personajes por rango en el Agente 3 no se activan.

---

## Parte 2 — Datos de sesión (`stream_data/`)

Cada ejecución vive en `stream_data/<session_id>/` (formato `YYYYMMDD_HHMMSS`, o `tiktok_<usuario>_<timestamp>` si viene de `tiktok_capture.py`). El directorio es también el "bus de datos" entre etapas: cada agente lee el JSON que dejó el anterior y escribe el suyo al lado.

### 2.1 Archivos de nivel de sesión

| Archivo | Escrito por | Contiene |
|---|---|---|
| `metadata.json` | `core/video_capture.py` | Dump crudo de `yt-dlp --dump-json`: título, descripción, uploader, duración, etc. Lo consume el Agente 0 (para inferir speakers) y el Agente 3 (fallback de nombre de personaje). |
| `stream_completo.mp4` | `core/video_capture.py` | Video fuente completo descargado (≤1080p). |
| `audio/audio_completo.mp3` | `core/video_capture.py` | Audio completo extraído del video. |
| `captura_estado.json` | `tiktok_capture.py` | Solo en sesiones de captura en vivo: usuario, url, `chunk_segundos`, lista de chunks grabados con su rango de tiempo real y estado (`listo`/`parcial`). |
| `pipeline_estado.json` | `core/chunk_manager.py` | Plan de chunks de **procesamiento** (distinto del de captura): url, config, duración total, tamaño de chunk, y un dict `chunks` con `{inicio_segundos, fin_segundos, inicio_ts, fin_ts, estado: pendiente\|completado\|fallido, error?}` por chunk. Es lo que permite reanudar una sesión cortada. |
| `contenido_final.json` | `pipeline.py` | Merge de todos los `contenido_chunks/*.json` de la sesión, ordenado por `score` descendente. Mismo esquema que `contenido.json` (ver abajo). |

### 2.2 Archivos por chunk (`chunks/<chunk_id>/`)

| Archivo | Escrito por | Esquema / contenido |
|---|---|---|
| `transcripcion_raw.txt` | `core/video_transcriber.py` | Texto plano, una línea por segmento: `[MM:SS] SPEAKER_XX: "texto"` (con diarización) o `[MM:SS] texto` (sin ella). Timestamps ya ajustados al offset real dentro del video completo. |
| `transcripcion_enriquecida.txt` | `core/agent0_speaker_identifier.py` | Mismo formato, con `SPEAKER_XX` reemplazado por el nombre real donde la confianza fue alta, o marcado `SPEAKER_XX [sin identificar]:` donde no. Es la que prefieren leer los Agentes 1/2/3 cuando existe. |
| `transcripcion_completa.txt` | varios | Copia de compatibilidad de la transcripción vigente (raw o enriquecida) bajo el nombre legacy que usan los modos `--test` y la lectura por defecto de los agentes. |
| `speaker_map.json` | `core/agent0_speaker_identifier.py` | `{"SPEAKER_00": {"nombre": <string|null>, "confianza": <float>, "estado": "confirmado"\|"posible"\|"desconocido"}, ...}` |
| `picos.json` | `agent1_peak_detector.py` | `{"picos": [{"timestamp": "MM:SS", "razon": <string>, "confianza": <float 0-1>, "tipo"?: <string>}, ...]}` — ya filtrado por `confianza_minima`. |
| `rangos.json` | `agent2_range_refiner.py` | `{"rangos": [{"conservar": <bool>, "inicio": "HH:MM:SS", "fin": "HH:MM:SS", "duracion_segundos": <int>, "razon": <string>, "gancho": <string>, "pico_original": {...picos.json item}}, ...]}` — puede haber menos rangos que picos (fusión de picos solapados) o rangos con `"conservar": false` (descartados, sin campos de tiempo). |
| `contenido.json` | `agent3_viral_scorer.py` | `{"contenido": [{"score": <int 1-10>, "publicar": <bool>, "texto_linea1": <string>, "texto_linea2": <string>, "hashtags": [<string>,...], "razon_score": <string>, "rango_original": {...rangos.json item}}, ...]}` — solo incluye rangos que tenían `conservar: true`. Si `--revisar` estaba activo, este archivo se reescribe tras la revisión con los `publicar` ajustados y ediciones de texto/rango aplicadas. |

### 2.3 Archivos de nivel de sesión derivados de chunks

| Archivo | Contenido |
|---|---|
| `contenido_chunks/<chunk_id>.json` | Copia de `contenido.json` de ese chunk, guardada aparte para poder mergear todos los chunks al final sin re-leer `chunks/*/contenido.json`. |
| `audio_chunks/<chunk_id>.mp3` | Audio extraído para ese rango de tiempo (solo si no había una transcripción base previa para dividir en vez de re-extraer). |

### 2.4 Clips generados

| Archivo | Escrito por | Esquema |
|---|---|---|
| `clips/clip_NNN.mp4` | `agent4_video_cutter.py` | Video vertical 1080x1920 con subtítulo quemado (o sin él, si el subtítulo falló). Numeración continua entre chunks de la misma sesión (`clip_offset`). |
| `clips/clip_NNN.json` | `agent4_video_cutter.py` | `{"clip": <filename>, "texto_linea1", "texto_linea2", "hashtags", "score", "duracion_segundos", "listo_para_publicar": false}` — el flag queda siempre en `false`; publicarlo o no es una decisión humana posterior. |
| `clips_custom/custom_<timestamp>.mp4` + `.json` | `clip_manual.py` | Igual que arriba más `{"inicio", "fin", "config", "creado_manual": true, "fecha"}`. Separado de `clips/` para no interferir con la numeración automática. |

### 2.5 Cómo leerlo de punta a punta

El orden de lectura/escritura dentro de un chunk es siempre:

```
transcripcion_raw.txt
  → transcripcion_enriquecida.txt (+ speaker_map.json)
    → transcripcion_completa.txt (alias del anterior)
      → picos.json
        → rangos.json
          → contenido.json  (posiblemente reescrito tras --revisar)
            → contenido_chunks/<chunk_id>.json (copia)
            → clips/clip_NNN.mp4 + .json
```

y a nivel de sesión, al terminar todos los chunks: `contenido_chunks/*.json` → `contenido_final.json`.

Como cada flecha es un archivo real en disco (no estado en memoria entre procesos), cualquier etapa puede re-ejecutarse manualmente apuntando al archivo de la etapa anterior sin tocar las demás — ver COMANDOS.md §3.
