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
| [`docs/CUENTAS.md`](docs/CUENTAS.md) | **Mapa de cuentas** y cómo Claude levanta Colab solo (sin iniciar sesión). |
| [`docs/DIAGNOSTICO_V1_FULL.md`](docs/DIAGNOSTICO_V1_FULL.md) | **Diagnóstico del piloto real (`v1_full`)** y brechas de calidad. |
| [`docs/DIAGNOSTICO_ACTUAL.md`](docs/DIAGNOSTICO_ACTUAL.md) | Diagnóstico inicial (sobre la base, incompleto; ver el anexo). |
| `docs/sprints/S<n>.md` | Cierre de cada sprint: qué se hizo y cómo probar la demo. |
| `legacy/CLAUDE.md`, `legacy/docs/` | Documentación **del piloto** `v1_full` (arquitectura, comandos, datos, aprendizaje). |

## Roles (separados)

El agente trabaja con **tres roles distintos** y debe indicar cuál ejerce en cada mensaje
(`[Analista]`, `[Líder técnico]`, `[Desarrollador]`):

| Rol | Hace | No hace |
|---|---|---|
| **Analista (consultor)** | Entiende el negocio, define requisitos y prioridades, mantiene los `docs/` de análisis (TO-BE, roadmap, diagnósticos), crea y prioriza tickets con criterios de aceptación, planifica sprints. **Actúa como consultor, no solo como ejecutor:** cuando el operador propone algo, presenta también el enfoque alternativo con sus pros y contras para ampliar el panorama, y deja que el operador decida. | No decide cómo se construye ni escribe código. |
| **Líder técnico / Arquitecto** | Decide **cómo** se construye: arquitectura y decisiones técnicas (ADR), **diseño técnico de cada sprint** antes de implementar, estándares de código y pruebas, **revisión del código** del sprint, **aprobación e integración del PR del sprint**, deuda técnica. | No cambia alcance ni prioridades (analista) ni implementa (desarrollador). |
| **Desarrollador** | Implementa los tickets del sprint según el diseño técnico, con pruebas; corrige lo que pida el líder técnico. | No cambia alcance ni diseño: si algo no cuadra, lo escala al líder técnico o al analista (comentario en Jira). |

El **operador** aprueba el plan del analista y revisa la **demo** de cada sprint antes de cerrarlo.
El PR del sprint lo revisa e integra el líder técnico.

## Gestión del trabajo (Jira)

- Sitio: `personal-clipeo.atlassian.net` · Proyecto **`CLIP`** · Tablero Scrum (board 1).
- **Épicas**: CLIP-5 (F0 · Fundación), CLIP-6…10 (Q1–Q5, calidad: el foco), CLIP-26 (Q6 · onboarding de cliente nuevo), CLIP-11 y CLIP-12 (secundarias).
- **Sprints de 1 semana** (lunes a domingo), S1…S10, cada uno con una **demo concreta**.
- Los tickets se detallan **solo para el sprint siguiente**, al planificarlo.
- Etiquetas: `F<n>`/`Q<n>` (épica), `operador` (requiere acción del operador), `externo`, `infra`, `docs`,
  `calidad`, `secundario`.

### Ciclo del sprint (se trabaja por sprint, no por ticket suelto)

1. **[Analista]** confirma los tickets del sprint y sus criterios de aceptación.
2. **[Líder técnico]** escribe el **diseño técnico** en `docs/sprints/S<n>.md` (cómo se resuelve cada ticket,
   orden, riesgos) en la rama `sprint/S<n>`.
3. **[Desarrollador]** implementa todos los tickets en `sprint/S<n>`, **un commit por ticket** con prefijo
   `CLIP-<n>:`, tests en verde; mueve cada ticket a **En curso** / **En revisión** en Jira.
4. **[Líder técnico]** revisa el sprint completo contra el diseño y los criterios de aceptación; pide correcciones
   al desarrollador si hace falta; deja su revisión escrita en el PR.
5. **[Líder técnico]** abre el **PR `sprint/S<n>` → `main`**, lo aprueba e integra cuando cumple los criterios.
   Nota: GitHub no permite aprobar formalmente un PR propio; la aprobación queda como comentario de revisión.
6. **Demo:** se completa `docs/sprints/S<n>.md` (qué se hizo, **cómo probar la demo paso a paso**, pendientes)
   y el **operador** la revisa. Con su OK: tickets a **Finalizada**, sprint cerrado en Jira, `docs/ESTADO.md`
   actualizado.

## Estructura del repositorio

Transición en curso (ADR-008, migración *strangler*):

```
CLAUDE.md, docs/                 ← documentación (este archivo + análisis + estado)
legacy/                          ← PILOTO v1_full (el que se usa hoy); ver legacy/README.md y legacy/CLAUDE.md
legacy/tests/                    ← tests del piloto (293, todos pasan)
evaluacion/                      ← evaluación de calidad (desde CLIP-20)
```

Estructura objetivo (se crea en CLIP-16, ver ARQUITECTURA_OBJETIVO §8):
`engine/` (agnóstico) · `clips/` (dominio) · `adapters/` · `app/` (CLI + web) · `knowledge/` (YAML por cliente) ·
`assets/` · `colab/` · `legacy/` (piloto) · `tests/`.

**Regla de dependencias:** `engine/` nunca importa `clips/` ni `adapters/`.

## Cómo ejecutar

- **v2:** con Docker Compose (se crea en CLIP-17): `docker compose up`. Base SQLite local en `./data/` (ADR-015).
- **Piloto:** desde `legacy/` (ver `legacy/README.md`):
  `cd legacy && python pipeline.py --video <url_o_ruta> --config <canal_id> [--revisar]`.
  Requiere `legacy/.env` (ver `.env.example`) y FFmpeg. IA por defecto: Claude Code de la máquina (`AI_PROVIDER=claude_cli`).
- **Tests:** `pip install -r requirements-test.txt` y `python -m pytest -q tests legacy/tests` (lo mismo corre el CI en cada PR).

## Reglas de trabajo

- **No gastar la API de Anthropic** salvo que el operador lo pida: los pasos de IA usan Claude Code
  (`AI_PROVIDER=claude_cli`, o `manual` para depurar) y la investigación se hace en sesión (skill `seo-refresh`).
- **Secretos nunca en el repo ni en el chat**: van en `.env` local o se piden por el formulario seguro.
- **Portabilidad**: nada de rutas absolutas ni comandos de un solo sistema operativo.
- **Calidad del clip** se mide con el conjunto de evaluación (`evaluacion/`, ver `evaluacion/README.md`) y la línea base
  `docs/calidad/LINEA_BASE.md`. La verdad final es la **respuesta de la audiencia** (métricas de clips publicados): la
  evaluación offline es una red de seguridad, no la meta.
- Contenido de terceros: seguir el riesgo aceptado **R-01** de `docs/TO_BE.md` (cuentas de captación separadas,
  retiro inmediato ante solicitud, lista de exclusión).
- Mantener `docs/ESTADO.md` al día: es la memoria compartida entre sesiones.
