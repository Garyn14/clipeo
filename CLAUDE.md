# CLAUDE.md

Guía para cualquier sesión de Claude Code (u otro agente) que trabaje en este repositorio.
**Lee esto primero, luego [`docs/ESTADO.md`](docs/ESTADO.md).** Con esos dos archivos debes saber en qué fase
estamos, qué ticket sigue y cómo trabajar.

## Qué es Clipeo (en 5 líneas)

1. Plataforma interna de **clipeo gestionado**: un operador atiende a muchos streamers clientes.
2. Produce clips verticales virales adaptados al objetivo de cada cliente, los revisa y los publica en varias plataformas.
3. Se compone de un **engine agnóstico** de orquestación (`engine/`) y un **sistema de clips** encima (`clips/`).
4. Restricción clave: **costo ≈ 0** hasta tener ingresos (IA vía Claude Code como "operador IA", transcripción gratuita, todo local en Docker).
5. **Foco actual: la calidad del clip.** Se evoluciona el piloto real (`v1_full`) según `docs/ROADMAP.md` v0.3; lo demás es secundario.

## Mapa de documentos

| Documento | Para qué |
|---|---|
| [`docs/ESTADO.md`](docs/ESTADO.md) | **Dónde estamos ahora**: sprint, ticket en curso, siguiente paso, bloqueos. |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Foco, épicas Q1–Q5 y sprints. |
| [`docs/ARQUITECTURA_OBJETIVO.md`](docs/ARQUITECTURA_OBJETIVO.md) | Arquitectura v2 y decisiones (ADR-001…015). |
| [`docs/TO_BE.md`](docs/TO_BE.md) | Visión, procesos, requisitos, riesgos (incl. R-01 contenido de terceros). |
| [`docs/DIAGNOSTICO_V1_FULL.md`](docs/DIAGNOSTICO_V1_FULL.md) | **Diagnóstico del piloto real (`v1_full`)** y brechas de calidad. |
| [`docs/DIAGNOSTICO_ACTUAL.md`](docs/DIAGNOSTICO_ACTUAL.md) | Diagnóstico inicial (sobre la base, incompleto; ver el anexo). |
| `docs/sprints/S<n>.md` | Cierre de cada sprint: qué se hizo y cómo probar la demo. |
| `docs/ARQUITECTURA.md`, `COMANDOS.md`, `ESTRUCTURA_DATOS.md`, `APRENDIZAJE.md` | Documentación **del piloto** (referencia). |

## Roles (separados)

El agente trabaja con **dos roles distintos** y debe indicar cuál ejerce (`[Analista]` / `[Desarrollador]`):

| Rol | Hace | No hace |
|---|---|---|
| **Analista** | Entiende el negocio, define requisitos y prioridades, mantiene `docs/` de análisis (TO-BE, roadmap, diagnósticos), crea y prioriza tickets con criterios de aceptación, planifica sprints. | No escribe código de producto. |
| **Desarrollador** | Implementa **solo tickets aprobados**, con tests; abre PR; actualiza `docs/ESTADO.md` al cerrar. | No cambia el alcance ni las prioridades: si un ticket no alcanza o descubre algo nuevo, lo devuelve al analista (comentario en Jira). |

El operador aprueba lo que propone el analista y revisa lo que entrega el desarrollador.

## Gestión del trabajo (Jira)

- Sitio: `personal-clipeo.atlassian.net` · Proyecto **`CLIP`** · Tablero Scrum (board 1).
- **Épicas**: CLIP-5 (F0 · Fundación), CLIP-6…10 (Q1–Q5, calidad: el foco), CLIP-11 y CLIP-12 (secundarias).
- **Sprints de 1 semana** (lunes a domingo), S1…S10. Cada sprint termina con una **demo concreta** que el
  operador revisa personalmente antes de cerrar el sprint.
- Los tickets se detallan **solo para el sprint siguiente**, al planificarlo.
- Etiquetas: `F<n>` (fase), `operador` (requiere acción del operador), `externo`, `infra`, `docs`, `calidad`.

### Flujo por ticket

1. Mover el ticket a **En curso** en Jira.
2. Rama `CLIP-<n>-<slug>` desde `main` (o apilada sobre el ticket del que depende).
3. Commits con prefijo `CLIP-<n>:`.
4. Tests y lint en verde (`pytest`, y desde CLIP-16: `ruff`, `mypy`).
5. PR a `main` con el ticket en el título; el operador revisa y aprueba.
6. Al integrar: ticket a **Finalizada** y actualizar `docs/ESTADO.md`.

### Cierre de sprint

Escribir `docs/sprints/S<n>.md` (qué se hizo, **cómo probar la demo paso a paso**, capturas o clips, pendientes),
pedir revisión al operador y, solo con su OK, cerrar el sprint en Jira.

## Estructura del repositorio

Transición en curso (ADR-008, migración *strangler*):

```
CLAUDE.md, docs/                 ← documentación (este archivo + análisis + estado)
legacy/                          ← PILOTO v2.0 congelado (tag piloto-v2.0); ver legacy/README.md
legacy/tests/                    ← tests del piloto (81, todos pasan)
```

Estructura objetivo (se crea en CLIP-16, ver ARQUITECTURA_OBJETIVO §8):
`engine/` (agnóstico) · `clips/` (dominio) · `adapters/` · `app/` (CLI + web) · `knowledge/` (YAML por cliente) ·
`assets/` · `colab/` · `legacy/` (piloto) · `tests/`.

**Regla de dependencias:** `engine/` nunca importa `clips/` ni `adapters/`.

## Cómo ejecutar

- **v2:** con Docker Compose (se crea en CLIP-17): `docker compose up`. Base SQLite local en `./data/` (ADR-015).
- **Piloto:** desde `legacy/` (ver `legacy/README.md`):
  `cd legacy && python pipeline.py --video <url_o_ruta> --config <canal_id> [--revisar]`.
  Requiere `.env` (ver `.env.example`) y FFmpeg. Para lives: `captura/tiktok_capture.py` + `--video`.
- **Tests del piloto:** `python -m pytest -q legacy/tests`.

## Reglas de trabajo

- **No gastar la API de Anthropic** salvo que el operador lo pida: los pasos de IA usan el modo operador
  (`AI_PROVIDER=manual`, skill `pipeline-manual`) o Claude Code en sesión (skill `seo-refresh`).
- **Secretos nunca en el repo ni en el chat**: van en `.env` local o se piden por el formulario seguro.
- **Portabilidad**: nada de rutas absolutas ni comandos de un solo sistema operativo.
- **Calidad del clip** se mide contra el golden set (`tests/golden/`, desde CLIP-20).
- Contenido de terceros: seguir el riesgo aceptado **R-01** de `docs/TO_BE.md` (cuentas de captación separadas,
  retiro inmediato ante solicitud, lista de exclusión).
- Mantener `docs/ESTADO.md` al día: es la memoria compartida entre sesiones.
