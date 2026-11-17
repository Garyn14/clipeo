# Clipeo v2 — Roadmap

> Estado: **v0.3 aprobada** · Fecha: 2026-11-17 · Reemplaza la v0.2 (F0–F7).
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
| Secundario · Plataforma | CLIP-11 | Engine agnóstico, Docker, nube vs. local, automatización 24/7 |
| Secundario · Publicación y clientes | CLIP-12 | Mejoras de publicación, clientes, reportes, prospección, trámites de APIs |

## 3. Sprints (1 semana, demo revisada por el operador)

| Sprint | Fechas | Épica | Demo |
|---|---|---|---|
| **S1** | 16–22 nov | F0 + Q1 | `v1_full` funcionando desde `legacy/` con sus tests en verde y un comando que evalúa casos de referencia |
| **S2** | 23–29 nov | Q1 | Informe de línea base: cobertura del detector y acierto del juez, con números |
| **S3** | 30 nov–6 dic | Q2 | Mismos clips antes y después, lado a lado |
| **S4** | 7–13 dic | Q3 | Más momentos buenos que la línea base, medido |
| **S5** | 14–20 dic | Q4 | Defectos visuales detectados y corregidos solos |
| **S6** | 21–27 dic | Q5 | Primer informe del analista semanal con reglas propuestas; memoria de `streamers_peru` |
| S7–S10 | 28 dic–24 ene | — | Por planificar según resultados (más calidad o temas secundarios) |

Cada mejora de Q2–Q5 se acepta solo si **mejora o no empeora** la línea base de Q1.

## 4. Decisiones pendientes (secundarias)

- **Nube vs. local y automatización 24/7**: opciones evaluadas el 2026-11-17 (servidor gratuito, sin servidor por
  piezas, híbrido con trabajadores). Riesgo principal: bloqueo de descargas desde IP de nube. Se decide en la épica
  CLIP-11 cuando haya volumen o clientes que lo justifiquen. Reemplazaría ADR-015.
- **Docker** (CLIP-17) y **estructura v2** (CLIP-16): en backlog.

## 5. Gestión

- Jira: proyecto `CLIP` en `personal-clipeo.atlassian.net`. Tickets detallados solo para el sprint siguiente.
- Roles separados (ver `CLAUDE.md`): **analista** define y prioriza; **desarrollador** implementa tickets aprobados.
