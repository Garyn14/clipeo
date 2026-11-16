# Estado del proyecto

> Memoria compartida entre sesiones. **Actualizar al cerrar cada ticket.**
> Última actualización: 2026-11-16

## Ahora

- **Sprint:** S1 · Fundación (F0) — 16 al 22 de noviembre de 2026 (activo).
- **Objetivo / demo del sprint:** en la laptop del operador, `docker compose up` y el piloto genera un clip dentro
  de Docker; CI en verde en un PR; `CLAUDE.md` nuevo y documentos en `main`.

## Tickets del sprint

| Ticket | Tema | Responsable | Estado |
|---|---|---|---|
| CLIP-13 | Documentación de análisis a `main` + ADR-015 | Claude Code | PR abierto: Garyn14/clipeo#1 |
| CLIP-15 | `CLAUDE.md` + `docs/ESTADO.md` + convención Jira | Claude Code | PR abierto: Garyn14/clipeo#2 (apilado sobre #1) |
| CLIP-14 | Congelar piloto: tag `piloto-v2.0` + `legacy/` | Claude Code | En revisión (falta crear el tag, ver bloqueos) |
| CLIP-16 | Estructura v2 + pyproject/ruff/mypy/pytest | Claude Code | Pendiente |
| CLIP-17 | Docker + docker compose | Claude Code | Pendiente |
| CLIP-19 | Portabilidad (quitar rutas Windows) | Claude Code | Pendiente |
| CLIP-18 | CI GitHub Actions | Claude Code | Pendiente |
| CLIP-20 | Golden set | **Operador** (datos) + Claude Code (formato) | Pendiente |
| CLIP-21 | Notebook de Colab versionado | **Operador** (exportar) + Claude Code | Pendiente |
| CLIP-22 | Trámites APIs (TikTok, Meta, YouTube) + cuenta Groq | **Operador** | Pendiente |

Orden previsto: 13 → 15 → 14 → 16 → 19 → 17 → 18.

## Siguiente paso

Revisión y merge de Garyn14/clipeo#1 (CLIP-13) por el operador; luego CLIP-14.

## Bloqueos / pendientes del operador

- Crear el tag `piloto-v2.0` sobre el commit `5653b66` (el entorno de Claude Code no puede subir tags):
  `git tag piloto-v2.0 5653b66 && git push origin piloto-v2.0`.
- Borrar los tickets de ejemplo CLIP-1 a CLIP-4 en Jira (el conector no permite borrar).
- CLIP-20, CLIP-21 y CLIP-22 (ver tabla).

## Decisiones recientes

| Fecha | Decisión |
|---|---|
| 2026-11-16 | Gestión en Jira (`CLIP`), sprints semanales con demo revisada por el operador. |
| 2026-11-16 | ADR-015: Docker Compose + SQLite local por laptop; conocimiento en YAML versionado; backup/restore. |
| 2026-11-15 | Arquitectura v0.2 y roadmap v0.2 aprobados (módulos de calidad del clip, F0–F7). |
| 2026-11-15 | El código de publicación de v1 no está disponible: se reconstruye en F6. |
