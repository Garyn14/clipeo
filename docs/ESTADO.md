# Estado del proyecto

> Memoria compartida entre sesiones. **Actualizar al cerrar cada ticket.**
> Última actualización: 2026-11-17

## Ahora

- **Foco:** clips de calidad (ver `docs/ROADMAP.md` v0.3). Lo demás es secundario.
- **Piloto de referencia:** `v1_full`, en `legacy/` desde CLIP-23 (ver `docs/DIAGNOSTICO_V1_FULL.md`).
- **Sprint:** S2 · Línea base de calidad (Q1) — 17 al 29 de noviembre de 2026 (activo). S1 cerrado el 17-nov.
- **Demo del sprint:** informe con números: cobertura del detector y acierto del juez, errores típicos y prioridades.

## Tickets del sprint

| Ticket | Tema | Responsable | Estado |
|---|---|---|---|
| CLIP-24 | Evaluación de cobertura del detector (A1 → A2) + exportador ampliado + repeticiones | Desarrollador | Implementado en `sprint/S2` |
| CLIP-20 | Casos reales (export en la laptop) | **Operador** | **Listo para exportar** (rama `sprint/S2`) |
| CLIP-25 | Informe de línea base (`docs/calidad/LINEA_BASE.md`) | Desarrollador | Pendiente (depende de CLIP-20) |

Diseño técnico: `docs/sprints/S2.md`. S1 cerrado: ver `docs/sprints/S1.md`.
En backlog (secundario): CLIP-16, CLIP-17, CLIP-22.

## Siguiente paso

Export de casos reales por el operador (CLIP-20) → CLIP-25 (informe de línea base).

## Pendientes del operador

- Borrar la rama `prueba/ci-bloqueo` en GitHub (PR #8 cerrado → "Delete branch").
- Al volver el repo a privado: la protección de `main` deja de aplicarse en el plan Free y Actions depende de la cuota de la cuenta.

- CLIP-20: exportar casos reales **cuando el desarrollador avise** (después de CLIP-24), para hacerlo una sola vez.

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
