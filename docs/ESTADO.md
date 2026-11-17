# Estado del proyecto

> Memoria compartida entre sesiones. **Actualizar al cerrar cada ticket.**
> Última actualización: 2026-11-17

## Ahora

- **Foco:** clips de calidad (ver `docs/ROADMAP.md` v0.3). Lo demás es secundario.
- **Piloto de referencia:** `v1_full`, en `legacy/` desde CLIP-23 (ver `docs/DIAGNOSTICO_V1_FULL.md`).
- **Sprint:** S1 · Base del piloto real + evaluación — 16 al 22 de noviembre de 2026 (activo).
- **Demo del sprint:** `v1_full` funcionando desde `legacy/` con sus tests en verde, y un comando que evalúa casos
  de referencia construidos con los datos de investigación.

## Tickets del sprint

| Ticket | Tema | Responsable | Estado |
|---|---|---|---|
| CLIP-13 | Documentación de análisis a `main` | Desarrollador | Finalizada |
| CLIP-14 | Congelar piloto (`legacy/`, tag `piloto-v2.0`) | Desarrollador | Finalizada |
| CLIP-15 | `CLAUDE.md` + `docs/ESTADO.md` + convención Jira | Desarrollador | Finalizada |
| CLIP-23 | Reemplazar `legacy/` por `v1_full` | Desarrollador | Integrado en `main` (demo pendiente) |
| CLIP-20 | Conjunto de evaluación con datos de investigación (Q1) | Desarrollador + **operador** (exportar casos) | Integrado; falta el export del operador |
| CLIP-19 | Portabilidad (quitar rutas de Windows) | Desarrollador | Integrado en `main` (demo pendiente) |
| CLIP-18 | CI con los tests de `legacy/` | Desarrollador | Integrado; **bloqueado** hasta resolver la facturación de GitHub Actions |
| CLIP-21 | Notebook de Colab versionado | Desarrollador | Integrado en `main` (demo pendiente) |

Orden previsto: 23 → 20 → 19 → 18. En backlog (secundario): CLIP-16, CLIP-17, CLIP-22.

## Siguiente paso

Demo del S1 por el operador (`docs/sprints/S1.md` §7). Luego planificar S2 (línea base de calidad).

## Pendientes del operador

- GitHub: resolver la facturación de Actions (Settings → Billing & plans) y activar la protección de `main`.

- CLIP-20: en la laptop, `python -m evaluacion.exportar_casos zapatillas_peru` y subir `evaluacion/casos/zapatillas_peru.yaml` (ver `evaluacion/README.md`).

- Configurar los Secrets `HF_TOKEN` y `AUTH_TOKEN` en Colab (ver `legacy/colab/README.md`).
- Entorno local (opcional, para demos): WSL + Docker Engine en la laptop; carpeta `D:\clipeo` en Remote Control
  (hoy figura "no disponible" para sesiones en la nube; alternativa: sesión local de Claude Code).

## Decisiones recientes

| Fecha | Decisión |
|---|---|
| 2026-11-17 | **Riesgo aceptado:** repo público temporalmente para usar GitHub Actions gratis (la cuota del plan privado la consumió otro repo). Sin secretos en el historial (revisado); quedan visibles el email de commits, investigaciones sobre figuras públicas, docs de negocio y la memoria del nicho. Volver a privado más adelante. |
| 2026-11-17 | Foco del sistema: clips de calidad; infraestructura, nube, publicación y prospección pasan a secundario. |
| 2026-11-17 | `v1_full` es el piloto de referencia; se evoluciona (no se reescribe). Roadmap v0.3 con épicas Q1–Q5. |
| 2026-11-17 | Roles separados: analista (define/prioriza) y desarrollador (implementa tickets aprobados). |
| 2026-11-17 | Nube vs. local y automatización: decisión pendiente, épica secundaria CLIP-11. |
| 2026-11-16 | Gestión en Jira (`CLIP`), sprints semanales con demo revisada por el operador. |
