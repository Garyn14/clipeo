# CLAUDE.md

Guía para cualquier sesión de Claude Code (u otro agente) que trabaje en este repositorio.
**Lee esto primero, luego [`docs/ESTADO.md`](docs/ESTADO.md).** Con esos dos archivos debes saber en qué fase
estamos, qué ticket sigue y cómo trabajar.

## Qué es Clipeo (en 5 líneas)

1. Plataforma interna de **clipeo gestionado**: un operador atiende a muchos streamers clientes.
2. Produce clips verticales virales adaptados al objetivo de cada cliente, los revisa y los publica en varias plataformas.
3. Se compone de un **engine agnóstico** de orquestación (`engine/`) y un **sistema de clips** encima (`clips/`).
4. Restricción clave: **costo ≈ 0** hasta tener ingresos (IA vía Claude Code como "operador IA", transcripción gratuita, todo local en Docker).
5. **Foco actual: la calidad del clip.** Se evoluciona el piloto real (`v1_full`) según `docs/ROADMAP.md` (y lo vigente en `docs/ESTADO.md`); lo demás es secundario.

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
- **Sprints de 1 semana** (lunes a domingo), S1…S16 hasta ahora (`docs/sprints/`), cada uno con una **demo concreta**.
  Entre sprints puede haber **tickets sueltos** (p. ej. CLIP-70, CLIP-71) con el mismo ciclo: ticket → OK → PR.
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

### Operar Jira (para el agente)

- Sitio `personal-clipeo.atlassian.net` · cloudId `3c39c1aa-20fd-48fe-b90e-204f4b8d535c` · proyecto `CLIP`.
- Tipos de incidencia: **Tarea**, **Historia**, **Epic**, **Subtarea** (en español; "Task" falla).
- Transiciones: **11** Por hacer · **21** En curso · **31** In Review (→ "En revisión") · **41** Listo (→ "Finalizada").
- **Las claves deben coincidir con el repo** (commits `CLIP-<n>:`): crear los tickets de a uno y en orden. El
  2026-11-19 se resincronizaron CLIP-38…64, que faltaban en Jira.
- Ahorro de tokens: crear y mover con la operación genérica (`executeWrite` con `createJiraIssue` /
  `transitionJiraIssue`) pidiendo solo `responseFields: ["key"]`; las herramientas directas devuelven ~3k tokens por issue.
- **El conector a veces pierde el acceso a `personal-clipeo`** (queda solo otro sitio, p. ej. `capsula`) al recargarse
  la sesión: no crear nada en otro sitio; dejar el ticket escrito en `docs/ESTADO.md` y pedir al operador que reconecte.

## Estructura del repositorio

Transición en curso (ADR-008, migración *strangler*):

```
CLAUDE.md, docs/                 ← documentación (este archivo + análisis + estado)
legacy/                          ← PILOTO v1_full (el que se usa hoy); ver legacy/README.md y legacy/CLAUDE.md
legacy/tests/                    ← tests del piloto (con `tests/`: 479 en total al 2026-11-21, todos pasan)
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

## Acuerdos de trabajo con el operador

- **No iniciar ningún desarrollo sin el OK explícito del operador**, aunque el ticket ya exista. Crear el ticket y
  esperar "procede" / "dale el OK". Documentación de apoyo y diagnósticos sí se pueden hacer.
- **`main` está protegido**: todo cambio (código o docs) entra por rama + PR con CI en verde. El operador suele
  integrar o dar "intégralo"; un PR de **código** no se integra sin ese OK; los PR
  solo de documentación que él pidió (cierres, ESTADO) se integran tras el CI.
- **"¿Dónde está la pelota?"**: responder separando *lo del operador* (decisiones, demos, acciones en apps) y *lo del
  agente* (lo que puede avanzar), con una recomendación concreta.
- **Como analista, consultar**: ante una propuesta del operador, presentar alternativas con pros y contras y una
  recomendación; si una afirmación propia resulta equivocada, corregirla explícitamente.
- **Ahorro de tokens**: no vigilar procesos largos con esperas o capturas repetidas; lanzar, esperar en segundo plano
  (`sleep` en background) y revisar una sola vez. Leer logs/estado en vez de capturas cuando se pueda.
- **No detener ni reiniciar el `levantar` del operador** (su terminal); cuando un cambio de backend lo requiera, avisar
  y pedirle que lo reinicie. Antes de tocar código que usa el pipeline, comprobar que no haya pipelines corriendo.
- **Seguridad**: nunca iniciar sesión ni escribir contraseñas/tokens; nunca tocar los videos privados de TikTok del
  operador; R-01 para contenido de terceros. Datos personales (correos) solo en archivos locales ignorados por git.
- **Windows**: usar `gh` en `C:\Program Files\GitHub CLI\gh.exe` (cuerpos con `--body-file`); los scripts que
  escriben a archivo o consola deben forzar UTF-8 (`sys.stdout.reconfigure(encoding="utf-8")`): cp1252 tumba un print
  con "→" o emojis. Los heredocs largos de bash fallan con comillas: escribir el script a un archivo y ejecutarlo.
- **Navegador integrado**: bloquea `window.confirm`/`alert` (devuelven falso sin mostrar nada): usar confirmaciones
  dentro de la página. Las cookies se conservan con "Conservar cookies → Compartidas".
- Responder en español, indicando el rol (`[Analista]`, `[Líder técnico]`, `[Desarrollador]`).

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
