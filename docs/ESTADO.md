# Estado del proyecto

> Memoria compartida entre sesiones. **Actualizar al cerrar cada ticket.**
> Última actualización: 2026-11-18 (S8 implementado)

## Ahora

- **Foco:** clips de calidad (ver `docs/ROADMAP.md` v0.3). Lo demás es secundario.
- **Piloto de referencia:** `v1_full`, en `legacy/` desde CLIP-23 (ver `docs/DIAGNOSTICO_V1_FULL.md`).
- **Sprint:** **S8 · Medios a escala** (`docs/sprints/S8.md`, rama `sprint/S8`): CLIP-43 (búsqueda de fuentes de
  medios para aprobar: 13 candidatos en `investigacion/zapatillas_peru/fuentes_medios.jsonl`), CLIP-44 (experimento
  de título caja vs contorno, medido con la audiencia), CLIP-45 (720p: no es bug). 423 tests. S1–S7 cerrados.
- **Siguiente para el operador:** aprobar fuentes (`python -m investigacion.fuentes_medios listar zapatillas_peru`),
  publicar con link y, con ≥ 10 clips por variante, `python -m evaluacion.experimento_titulo zapatillas_peru`.
- Modelo SFace y caras de referencia **fuera del repo**: en otra máquina, descargar SFace (`legacy/edicion_video/assets/
  modelos/README.md`) y correr `python -m edicion_video.referencia_cara fritz <videos de su canal>`.
- Backlog de publicación (secundario): TikTok entrega el borrador sin descripción ni hashtags; el operador los pega.

## Tickets del sprint

| Ticket | Tema | Estado |
|---|---|---|
| CLIP-29 | Fidelidad de la evaluación (pistas del detector + hablantes) | Hecho: casos re-exportados por el operador; línea base v2 medida |
| CLIP-30 | Memoria del nicho con datos de @nandoclips93 | Hecho: cambios 1–7 **aprobados** y aplicados en `referencias.yaml`; 10 casos etiquetados por audiencia (`evaluacion/casos/zapatillas_peru.audiencia.yaml`) |
| CLIP-31 | Dirección editorial MVP | Hecho: **demo aprobada por el operador (3/3 clips mejores)**; encendida por defecto (`DIRECCION_EDITORIAL=0` la apaga) |

Diseño técnico: `docs/sprints/S3.md`. Línea base: `docs/calidad/LINEA_BASE.md`.
En backlog: CLIP-27 (medios como fuente), CLIP-28 (transcripción/hablantes), CLIP-26 (Q6 onboarding), CLIP-16/17/22.

### Mediciones del juez (3 corridas c/u, resultados en `evaluacion/resultados/`)

| Escenario | Archivo | Etiqueta editor: precisión / recall | Etiqueta audiencia: precisión / recall / 10 publicados |
|---|---|---|---|
| A. Memoria anterior, sin dirección | `20261117_174956_zapatillas_peru.json` | 0,89 / 0,27 | 0,70 / 0,24 / 4,3 de 10 |
| B. Memoria anterior, con dirección | `20261117_184336_zapatillas_peru_direccion.json` | 0,88 / 0,31 | 0,69 / 0,27 / 4,0 de 10 |
| C1. Memoria nueva, sin dirección | `20261117_190922_zapatillas_peru.json` | — | 0,78 / 0,21 / 5,0 de 10 |
| C2. Memoria nueva, con dirección | `20261117_200040_zapatillas_peru_direccion.json` | — | 0,77 / 0,22 / 5,7 de 10 |

- Re-puntuar con etiquetas de audiencia: cargar los casos con `evaluacion.casos.cargar_nicho()` (ya aplica
  `zapatillas_peru.audiencia.yaml`) y recalcular VP/FP/VN/FN sobre `corridas[*].resultados[*].obtenido_publicar`.
- Hallazgo: 40 de 50 planes de dirección descartados en B eran más cortos que el mínimo (20 s). Decisión del
  operador: mínimo propio de la dirección = 15 s (el máximo no cambia).

## Tickets del S4

| Ticket | Tema | Estado |
|---|---|---|
| CLIP-32 | Umbral del juez | **Hecho** (commit d232ba5): `juez.umbral_fuerza: 3`, `prioridad` si fuerza ≥ 7, `python -m evaluacion.umbral` |
| CLIP-33 | Clips publicados → evaluación | **Hecho**: `evaluacion/etiquetar_audiencia.py` (link pegado > duración+fecha+título) y campo "Link del video ya publicado" en la revisión web (commit c72363e) |
| CLIP-34 | Medios como fuente (PoC) | **Hecho** con Magaly (`docs/calidad/MEDIOS_POC.md`): encuentra el momento que más rindió (fuerza 7, `medios_y_polemica`). Panorama: correr en la laptop (YouTube bloquea la nube) |

## Siguiente paso

[Analista] Planificar el S6 (abajo). Pendientes del operador que quedaron del S5:
1. Decidir la cuenta de destino de los clips de medios (`docs/sprints/S5.md` §4: misma cuenta o captación).
   Mientras no decida: misma cuenta del nicho.
2. Cargar CLIP-35 y CLIP-36 en Jira y cerrar el sprint S5 ahí (la cuenta de Atlassian de la sesión no ve
   `personal-clipeo`).

**S5 cerrado (2026-11-18):** CLIP-35, CLIP-27, CLIP-36 + fixes (umbral del juez, `fuente` en el plan, Secret del
notebook). 379 tests, CI en verde, PR Garyn14/clipeo#17 integrado. Demo con Latina Noticias: 2 clips aprobados.

**Transcripción: solo Colab** (decisión del operador; WhisperX local no se usa). Claude levanta el notebook en el
navegador integrado: celdas 1 y 2 → reiniciar sesión → celda 3 (reintentar si falla) → URL a `COLAB_TRANSCRIBE_URL`
de `D:\clipeo\.env`. Cuentas de Colab con los Secrets `HF_TOKEN` y `COLAB_AUTH_TOKEN`.

**S6 (aprobado por el operador el 2026-11-18): edición profesional (Q2 visual + Q4)**, empezando por un diagnóstico:
5 clips propios vs 5 top de otras cuentas (encuadre, subtítulos, ritmo, audio), base
`legacy/modulo_edicion_patrones_clipeo.md`. Candidatos además: el corte (FFmpeg local, 2 min 36 s para 2 clips) es
ahora el paso más lento; el transcriptor relee `legacy/.env` pero el `.env` real está en la raíz (arreglo de 1 línea).

**Hallazgo S5:** el umbral `juez.umbral_fuerza: 3` no se aplicaba en producción desde el S4 (bug del loader,
corregido). Desde el S5 llegan a la revisión más clips (todo lo de fuerza ≥ 3).

Hábito: publicar cada clip con su link pegado en la revisión; luego `etiquetar_audiencia --escribir`.

### Notas para operar en la laptop

- Panel: `CLIPEO_STREAM_DATA=/d/clipeo/stream_data python -m uvicorn app.main:app --reload --port 8000` (en
  `legacy/backend`) y `npm run dev` (en `legacy/frontend`) → http://localhost:5173.
- Los links pegados quedan en `legacy/investigacion/zapatillas_peru/publicados.jsonl` (subirlo al repo con git).
- YouTube bloquea descargas desde la nube: `medios_poc` y descargas de medios se corren en la laptop.

### Feedback de la demo (operador, 2026-11-17)

`demo_direccion` sobre la sesión `20261003_231807`: clip_c001_02 (Sorprende a Rafo) mejor (inicio y transición más
limpios; la música era de prueba y no se evalúa), clip_c001_03 (billetera) mejor, clip_c001_04 (pilla a Rafael)
"mucho mejor".

## Pendientes del operador

- Borrar la rama `prueba/ci-bloqueo` en GitHub (PR #8 cerrado → "Delete branch").
- Al volver el repo a privado: la protección de `main` deja de aplicarse en el plan Free y Actions depende de la cuota de la cuenta.


- Configurar los Secrets `HF_TOKEN` y `AUTH_TOKEN` en Colab (ver `legacy/colab/README.md`).
- Entorno local (opcional, para demos): WSL + Docker Engine en la laptop; carpeta `D:\clipeo` en Remote Control
  (hoy figura "no disponible" para sesiones en la nube; alternativa: sesión local de Claude Code).

## Decisiones recientes

| Fecha | Decisión |
|---|---|
| 2026-11-17 | Cierre S3: dirección editorial encendida por defecto (demo 3/3 mejor); memoria con datos de @nandoclips93; 10 casos etiquetados por audiencia; mínimo de 15 s para la dirección (máximo sin cambio). |
| 2026-11-17 | La verdad es la audiencia: con Fritz se explota la data existente; con clientes nuevos, hipótesis + refinamiento (épica Q6). El analista actúa como consultor. |
| 2026-11-17 | Revisión visual de @nandoclips93: 6/10 del top son recortes de TV/prensa (polémica) → backlog "medios como fuente" (CLIP-27). |
| 2026-11-17 | **Línea base:** detector cobertura 83%; juez precisión 0,94 y recall 0,25 (demasiado estricto). Prioridad sugerida: Q2 (edición) + calibrar el juez antes que Q3. |
| 2026-11-17 | **Riesgo aceptado:** repo público temporalmente para usar GitHub Actions gratis (la cuota del plan privado la consumió otro repo). Sin secretos en el historial (revisado); quedan visibles el email de commits, investigaciones sobre figuras públicas, docs de negocio y la memoria del nicho. Volver a privado más adelante. |
| 2026-11-17 | Foco del sistema: clips de calidad; infraestructura, nube, publicación y prospección pasan a secundario. |
| 2026-11-17 | `v1_full` es el piloto de referencia; se evoluciona (no se reescribe). Roadmap v0.3 con épicas Q1–Q5. |
| 2026-11-17 | Roles separados: analista (define/prioriza) y desarrollador (implementa tickets aprobados). |
| 2026-11-17 | Nube vs. local y automatización: decisión pendiente, épica secundaria CLIP-11. |
| 2026-11-16 | Gestión en Jira (`CLIP`), sprints semanales con demo revisada por el operador. |
