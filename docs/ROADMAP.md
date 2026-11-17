# Clipeo v2 — Roadmap

> Estado: **v0.4 aprobada** · Fecha: 2026-11-17 · Reemplaza la v0.3.
> Base: [`DIAGNOSTICO_V1_FULL.md`](DIAGNOSTICO_V1_FULL.md) (piloto real) y el foco acordado con el operador.

---

## 0. Foco

**El objetivo del sistema es generar clips de calidad según lo definido** (perfil de cada cliente, memoria del nicho,
gancho primero, edición pensada, aprendizaje con resultados reales). Todo lo demás —infraestructura, nube,
automatización, publicación, prospección— es **secundario** y se planifica cuando haga falta.

Regla de oro: el operador sigue produciendo y publicando con el piloto (`v1_full`) mientras se mejora.

## 1. Punto de partida

El piloto real (`v1_full`) ya tiene: juez editorial con memoria del nicho medida, auditoría de cobertura, correcciones
del editor, IA vía Claude Code sin costo, orquestación por pasos, web de revisión y publicación a YouTube/TikTok.
Se **evoluciona**, no se reescribe.

## 2. Épicas

| Épica | Clave | Objetivo |
|---|---|---|
| F0 · Fundación | CLIP-5 | Repo listo: piloto real en `legacy/`, continuidad entre sesiones, portabilidad, CI |
| **Q1 · Medición de calidad** | CLIP-6 | Conjunto de evaluación y línea base: poder decir con números si un cambio mejora |
| **Q2 · Dirección editorial** | CLIP-7 | Edición pensada: plan de edición (gancho primero, cortes, encuadre) que el render ejecuta |
| **Q3 · Detección con más señales** | CLIP-8 | Encontrar más momentos buenos (audio, energía, risas, chat); auditoría en el flujo |
| **Q4 · Control visual** | CLIP-9 | Ningún clip con defectos visuales llega a la revisión |
| **Q5 · Aprendizaje continuo** | CLIP-10 | Medir clips propios publicados y actualizar la memoria con evidencia; extenderla a otros nichos |
| **Q6 · Onboarding de cliente nuevo** | CLIP-26 | Cold start: memoria inicial desde cuentas parecidas, exploración decreciente, refinamiento con métricas propias |
| Secundario · Plataforma | CLIP-11 | Engine agnóstico, Docker, nube vs. local, automatización 24/7 |
| Secundario · Publicación y clientes | CLIP-12 | Mejoras de publicación, clientes, reportes, prospección, trámites de APIs |

## 3. Sprints (1 semana nominal, demo revisada por el operador)

| Sprint | Fechas | Épica | Demo | Estado |
|---|---|---|---|---|
| **S1** | 16–17 nov | F0 + Q1 | `v1_full` en `legacy/` + evaluador | ✅ Cerrado |
| **S2** | 17 nov | Q1 | Línea base: cobertura 83%, juez precisión 0,94 / recall 0,25 | ✅ Cerrado |
| **S3** | 17–30 nov | Q1 + Q2 + Q5 | Dirección editorial (antes/después), juez con la información de producción, memoria con los datos de @nandoclips93 | Activo |
| S4+ | — | — | Por planificar según resultados | — |

**Principio (2026-11-17):** no sabemos qué quiere la gente hasta salir a la cancha. Con un cliente con historia (Fritz)
se explota la data existente; con clientes nuevos se parte de una hipótesis y se refina con sus métricas (Q6). La
evaluación offline protege contra regresiones; la verdad es la audiencia.

**Backlog priorizado:** medios como fuente (CLIP-27: 6 de los 10 mejores clips de @nandoclips93 son de TV/prensa),
transcripción y hablantes (CLIP-28), exploración controlada al publicar, Q3 detección con más señales, Q4 control
visual, Q6 onboarding.

## 4. Decisiones pendientes (secundarias)

- **Nube vs. local y automatización 24/7**: opciones evaluadas el 2026-11-17 (servidor gratuito, sin servidor por
  piezas, híbrido con trabajadores). Riesgo principal: bloqueo de descargas desde IP de nube. Se decide en la épica
  CLIP-11 cuando haya volumen o clientes que lo justifiquen. Reemplazaría ADR-015.
- **Docker** (CLIP-17) y **estructura v2** (CLIP-16): en backlog.

## 5. Gestión

- Jira: proyecto `CLIP` en `personal-clipeo.atlassian.net`. Tickets detallados solo para el sprint siguiente.
- Roles separados (ver `CLAUDE.md`): **analista** define y prioriza; **desarrollador** implementa tickets aprobados.
