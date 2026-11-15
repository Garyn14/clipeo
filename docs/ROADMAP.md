# Clipeo v2 — Roadmap

> Estado: **propuesta v0.1 para validación** · Fecha: 2026-11-15 · Horizonte MVP: ~8 semanas (referencial)
> Basado en [`TO_BE.md`](TO_BE.md) y [`ARQUITECTURA_OBJETIVO.md`](ARQUITECTURA_OBJETIVO.md).

---

## 0. Regla de oro: el negocio no se detiene

Los objetivos del MVP (clip de 1M y primer cliente) **no dependen de terminar la v2**. Mientras se
construye, el operador sigue produciendo clips con el piloto (congelado en `legacy/`) en cuentas de
captación y prospectando. La v2 reemplaza al piloto solo cuando lo iguala (hito H1).

## 1. Fases del MVP

| Fase | Semanas | Objetivo | Entregables principales | Hito |
|---|---|---|---|---|
| **F0 Fundación** | 1 | Repo listo para trabajar con agentes | Tag `piloto-v2.0`; piloto → `legacy/`; `CLAUDE.md` nuevo + `docs/ESTADO.md`; `pyproject.toml` con versiones fijadas, ruff, mypy, pytest; CI en GitHub Actions; quitar rutas de Windows; versionar servidor Colab; **subir código de publicación de v1** | Cualquier sesión de Claude Code retoma el trabajo leyendo `CLAUDE.md` |
| **F1 Engine núcleo** | 2–3 | Engine agnóstico funcionando | Step/Flow/Run/StepRun en SQLite; worker; reintentos; idempotencia; estado "en espera"; scheduler; registro de costo; test de arquitectura (engine sin dominio) | Flow de ejemplo reanudable tras matar el proceso |
| **F2 IA + producción** | 3–4 | Paridad con el piloto | Capa LLM (`claude_code` operador IA + skill, `anthropic`, `openai_compatible`); salidas validadas; prompts versionados; agentes 0–4 del piloto envueltos como steps; flow `produccion` sobre un video local | **H1: la v2 produce clips de calidad igual o mejor que el piloto** con el mismo video |
| **F3 Clientes + ingesta** | 4–5 | Producción automática por cliente | Modelo `Cliente/Objetivo/Fuente`; migración de `contexto/` y `aprendizajes/` a `knowledge/`; adaptadores YouTube, Kick, TikTok; flow `ingesta` programado | Fritz Sport configurado; contenido nuevo se procesa solo |
| **F4 Revisión + inventario** | 5–6 | Operador revisa en navegador | Web local (FastAPI + HTMX): cola de revisión con video, aprobar/editar/descartar; inventario; flow `caducidad`; aprendizaje desde revisiones | **H2: flujo de punta a punta hasta inventario sin tocar la terminal** |
| **F5 Despacho + publicación** | 6–7 | Publicar con cadencia | `CuentaDestino` (propia/cliente, captación/cliente); flow `despacho` (4/día, score × frescura); publicadores `manual` (paquete), `youtube_api`, `tiktok_inbox`; `SecretStore` | **H3: clips publicados según cadencia en ≥ 2 plataformas** |
| **F6 Métricas + prospección + cierre** | 7–8 | Medir y vender | Flow `metricas` (YouTube, TikTok); reporte simple por cliente y KPI; costo por clip; módulo `prospeccion` + skill; benchmark de modelos open source vs. Claude por paso | **H4: MVP operativo** — reporte de un cliente real/prueba y 10 prospectos/semana gestionados |

## 2. Fases posteriores (resumen)

| Fase | Objetivo | Contenido |
|---|---|---|
| **Fase 2** (10–20 clientes) | Operación repetible | Panel web de operador completo, reporte para el cliente, cobro, agente revisor por cliente, aprendizaje automático desde métricas, Facebook Reels por API, Postgres, storage S3-compatible |
| **Fase 3** (~100 clientes) | Escala | Portal del cliente, workers múltiples / servidor, API de IA de pago donde convenga, agentes de negocio, PO, dev y finanzas |

## 3. Dependencias y ruta crítica

```
F0 ─▶ F1 ─▶ F2 ─▶ F3 ─▶ F4 ─▶ F5 ─▶ F6
                   └────────────▲          (F4 puede empezar con datos de F2 si F3 se atrasa)
Trámites externos (iniciar en F0, corren en paralelo):
  • Auditoría de app TikTok (Content Posting API) · Revisión de app Meta · Ampliación de cuota YouTube
```

## 4. Riesgos del plan

| Riesgo | Impacto | Respuesta |
|---|---|---|
| Operador único con poco tiempo | Retraso | Fases cortas con hito verificable; Claude Code implementa, operador valida |
| H1 no alcanza la calidad del piloto | Bloquea migración | Se reutilizan prompts y lógica del piloto tal cual antes de mejorarlos |
| Aprobación de APIs de publicación tarda | F5 parcial | Modo `manual` (paquete) es el default; `tiktok_inbox` y YouTube ya probados en v1 |
| Límites de uso de la suscripción de Claude | Producción lenta | Lotes; pasos mecánicos a modelos gratuitos tras benchmark (F6) |
| Bloqueos de descarga en plataformas fuente | Ingesta intermitente | Reintentos espaciados, cookies del operador, Colab como IP alternativa (ya usado en v1) |

## 5. Cómo se gestiona la ejecución

- **Tickets**: al aprobar este roadmap, cada fase se descompone en issues de GitHub (o Jira, si se decide) con criterios de aceptación; un *milestone* por fase.
- **Ramas y PRs**: una rama por ticket; PR con tests verdes en CI antes de integrar a `main`.
- **Continuidad**: al cerrar cada ticket se actualiza `docs/ESTADO.md` (fase actual, hecho, siguiente, bloqueos). `CLAUDE.md` apunta siempre ahí.
- **Revisión de fase**: al final de cada fase, demo del hito y ajuste del roadmap.
