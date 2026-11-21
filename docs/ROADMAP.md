# Clipeo v2 — Roadmap

> Estado: **v0.5 propuesta** · Fecha: 2026-11-18 · Reemplaza la v0.4.
> Base: [`DIAGNOSTICO_V1_FULL.md`](DIAGNOSTICO_V1_FULL.md), los sprints S1–S11 y el foco acordado con el operador.
>
> **Actualización 2026-11-21:** después de esta versión se hicieron S14 (fuentes por cliente), S15 (Colab de un
> solo paso, administrar fuentes con tipo desacoplado) y S16 (objetivo del cliente en el juez, links automáticos de
> TikTok), más CLIP-70 (Kick). La Fase 1 sigue abierta (calidad y aprendizaje dependen del uso); cierre previsto
> hacia el 2026-12-03. Lo vigente está en `docs/ESTADO.md` y `docs/sprints/`.

---

## 0. Foco

**El objetivo del sistema es generar clips de calidad según lo definido** (perfil de cada cliente, memoria del nicho,
gancho primero, edición pensada, aprendizaje con resultados reales). Todo lo demás —infraestructura, nube,
automatización, prospección— es **secundario** y se planifica cuando haga falta.

Regla de oro: el operador sigue produciendo y publicando con el piloto (`v1_full`, en `legacy/`) mientras se mejora.
Se **evoluciona**, no se reescribe.

## 1. Fases

| Fase | Objetivo | Sprints | Estado |
|---|---|---|---|
| **1 · Calidad con un cliente (Fritz)** | Clips de calidad de punta a punta con un cliente real: selección, edición, publicación y aprendizaje | S1–S13 | En curso |
| 2 · Segundo cliente | Sumar un streamer nuevo sin rehacer nada (Q6: memoria inicial, reconocimiento, perfil) | S14+ | Por planificar |
| 3 · Plataforma | Engine v2, Docker, nube o 24/7 (CLIP-11, CLIP-16/17) cuando el volumen lo justifique | — | Por planificar |

### Criterios para cerrar la Fase 1

1. **Calidad:** ≥ 60% de los clips que llegan a la revisión se aprueban sin editar, medido en 2 semanas de uso real
   (hoy: 4 de 7 en la revisión del 18-11).
2. **Publicación:** aprobar = publicado en YouTube y borrador en TikTok, sin pasos técnicos. ✅ (S10, 18-11)
3. **Aprendizaje:** ≥ 30 clips publicados medidos y al menos un cambio de memoria aprobado con esa evidencia.
4. **Operación estable:** levantar todo con un comando, sin variables a mano ni carpetas sueltas; reproducible en otra
   máquina con una guía. → **S12**

## 2. Épicas

| Épica | Clave | Objetivo | Estado |
|---|---|---|---|
| F0 · Fundación | CLIP-5 | Piloto en `legacy/`, continuidad entre sesiones, portabilidad, CI | ✅ |
| Q1 · Medición de calidad | CLIP-6 | Conjunto de evaluación y línea base | ✅ (base; se mantiene) |
| Q2 · Dirección editorial | CLIP-7 | Plan de edición, encuadre 4:5 que sigue a la persona, zoom por tramos | ✅ S3, S6, S7, S9 |
| Q3 · Detección con más señales | CLIP-8 | Más momentos buenos; medios como fuente | ◐ medios ✅ (S5, S8); audio ❌ descartado con datos (S9); hablantes de TV pendiente (CLIP-28) |
| Q4 · Control visual | CLIP-9 | Ningún clip con defectos llega sin aviso a la revisión | ✅ S11 |
| Q5 · Aprendizaje continuo | CLIP-10 | Medir lo publicado y ajustar la memoria con evidencia | ◐ medición ✅ (S10); falta volumen y el primer ajuste |
| Q6 · Onboarding de cliente nuevo | CLIP-26 | Cold start de un cliente nuevo | Fase 2 |
| Secundario · Plataforma | CLIP-11 | Engine agnóstico, Docker, nube vs. local, 24/7 | Fase 3 |
| Secundario · Publicación | CLIP-12 | Publicación y SEO por plataforma | ◐ YouTube ✅, TikTok hasta la bandeja (Direct Post requiere auditoría); YouTube como espejo (decisión del operador) |

## 3. Sprints

| Sprint | Tema | Estado |
|---|---|---|
| S1–S2 | Piloto en `legacy/`, evaluador y línea base | ✅ |
| S3 | Dirección editorial y memoria con datos reales | ✅ |
| S4 | Juez calibrado, la audiencia como etiqueta, medios (PoC) | ✅ |
| S5 | Medios como fuente en producción, R-01 | ✅ |
| S6 | Edición: encuadre 9:16 → 4:5, corte 2× más rápido, diagnóstico | ✅ |
| S7 | El encuadre sigue a Fritz (SFace), primer cuadro nítido | ✅ |
| S8 | Medios a escala: búsqueda de fuentes, experimento de título | ✅ |
| S9 | Encuadre en streams; señales de audio descartadas | ✅ |
| S10 | Medir lo publicado; publicación conectada | ✅ |
| S11 | Control visual automático | ✅ |
| **S12** | **Operación estable** (criterio 4 de la Fase 1) | Propuesto |
| S13 | Hablantes de TV (CLIP-28) + medición de la Fase 1 (criterios 1 y 3) y cierre | Por planificar |

**Principio (2026-11-17):** no sabemos qué quiere la gente hasta salir a la cancha. La evaluación offline protege
contra regresiones; la verdad es la audiencia. **Principio (2026-11-18):** decidir con datos también para descartar
(CLIP-47: una idea razonable que no supera al azar no entra).

## 4. Decisiones vigentes

- Transcripción **solo en Colab**; WhisperX local no se usa.
- TikTok: el operador publica desde la app (no le molesta en esta fase). YouTube: espejo automático.
- **Nube vs. local, Docker y estructura v2:** Fase 3. Riesgo principal conocido: bloqueo de descargas desde IP de nube.

## 5. Gestión

- Jira: proyecto `CLIP` en `personal-clipeo.atlassian.net` (lo carga el operador; la cuenta de Atlassian de las
  sesiones no ve ese sitio). Tickets detallados solo para el sprint siguiente.
- Roles separados (ver `CLAUDE.md`): **analista** define y prioriza; **líder técnico** diseña y revisa;
  **desarrollador** implementa tickets aprobados.
