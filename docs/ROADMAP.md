# Clipeo v2 — Roadmap

> Estado: **v0.2 aprobada** · Fecha: 2026-11-15 · Horizonte MVP: ~10 semanas (referencial)
> Basado en [`TO_BE.md`](TO_BE.md) y [`ARQUITECTURA_OBJETIVO.md`](ARQUITECTURA_OBJETIVO.md).

---

## 0. Regla de oro: el negocio no se detiene

Los objetivos del MVP (clip de 1M y primer cliente) **no dependen de terminar la v2**. Mientras se
construye, el operador sigue produciendo clips con el piloto (congelado en `legacy/`) en cuentas de
captación y prospectando. La v2 reemplaza al piloto solo cuando lo iguala (hito H1).

## 1. Fases del MVP

> v0.2: reordenado priorizando la **calidad del clip** (ver ARQUITECTURA_OBJETIVO §11).

| Fase | Semanas | Objetivo | Entregables principales | Hito |
|---|---|---|---|---|
| **F0 Fundación** | 1 | Repo listo para trabajar con agentes | Tag `piloto-v2.0`; piloto → `legacy/`; `CLAUDE.md` nuevo + `docs/ESTADO.md`; `pyproject.toml` con versiones fijadas, ruff, mypy, pytest; CI en GitHub Actions; quitar rutas de Windows; **subir código de publicación de v1**; **armar golden set** con clips del piloto y sus resultados | Cualquier sesión de Claude Code retoma el trabajo leyendo `CLAUDE.md` |
| **F1 Engine núcleo** | 2–3 | Engine agnóstico funcionando | Step/Flow/Run/StepRun en SQLite; worker; reintentos; idempotencia; estado "en espera"; scheduler; registro de costo; test de arquitectura | Flow de ejemplo reanudable tras matar el proceso |
| **F2 IA + producción con EDL** | 3–4 | Paridad con el piloto, ya con edición pensada | Capa LLM (`claude_code` operador IA + skill, `anthropic`, `openai_compatible`); salidas validadas; prompts versionados; agentes del piloto como steps; **dirección editorial → EDL** (incl. `gancho_primero`) + render que ejecuta EDL; evaluación contra golden set | **H1: la v2 iguala o supera al piloto en el golden set** |
| **F3 Transcripción + clientes + ingesta** | 4–5 | Producción automática por cliente, sin GPU | Cascada STT (Groq → Colab/Kaggle pull → CPU); modelo `Cliente/Objetivo/Fuente`; migración de `contexto/` y `aprendizajes/`; adaptadores YouTube, Kick, TikTok; flow `ingesta`; **etiquetado de rasgos de cada clip** | Fritz Sport configurado; contenido nuevo se procesa solo |
| **F4 Detección multiseñal + QA visual** | 5–6 | Mejores momentos y menos clips rotos | Señales de audio/escena/chat → candidatos; selección de historia (arcos completos); QA visual con fotogramas; evaluación contra golden set | **H2: mejora medible en el golden set vs. H1** |
| **F5 Revisión + inventario** | 6–7 | Operador revisa en navegador | Web local (FastAPI + HTMX): cola de revisión con video, aprobar/editar/descartar; inventario; flow `caducidad` | **H3: de punta a punta hasta inventario sin terminal** |
| **F6 Despacho + publicación** | 7–8 | Publicar con cadencia | `CuentaDestino`; flow `despacho` (4/día, score × frescura, variantes A/B); publicadores `manual`, `youtube_api`, `tiktok_inbox`; `SecretStore` | **H4: clips publicados según cadencia en ≥ 2 plataformas** |
| **F7 Métricas + aprendizaje + prospección** | 9–10 | Medir, aprender y vender | Flow `metricas` normalizado por cuenta; **bot analista semanal** con informe y reglas propuestas; libro de reglas versionado; reporte simple por cliente; costo por clip; módulo `prospeccion`; benchmark de modelos open source | **H5: MVP operativo** — primer informe semanal con reglas aprobadas y 10 prospectos/semana gestionados |

## 2. Fases posteriores (resumen)

| Fase | Objetivo | Contenido |
|---|---|---|
| **Fase 2** (10–20 clientes) | Operación repetible | Panel web de operador completo, reporte para el cliente, cobro, agente revisor por cliente, aprendizaje automático desde métricas, Facebook Reels por API, Postgres, storage S3-compatible |
| **Fase 3** (~100 clientes) | Escala | Portal del cliente, workers múltiples / servidor, API de IA de pago donde convenga, agentes de negocio, PO, dev y finanzas |

## 3. Dependencias y ruta crítica

```
F0 ─▶ F1 ─▶ F2 ─▶ F3 ─▶ F4 ─▶ F5 ─▶ F6 ─▶ F7
                   └──────────────────▲    (F5 puede empezar con datos de F2 si F3/F4 se atrasan)
Trámites externos (iniciar en F0, corren en paralelo):
  • Auditoría de app TikTok (Content Posting API) · Revisión de app Meta · Ampliación de cuota YouTube
```

## 4. Riesgos del plan

| Riesgo | Impacto | Respuesta |
|---|---|---|
| Operador único con poco tiempo | Retraso | Fases cortas con hito verificable; Claude Code implementa, operador valida |
| H1 no alcanza la calidad del piloto | Bloquea migración | Se reutilizan prompts y lógica del piloto tal cual antes de mejorarlos |
| Aprobación de APIs de publicación tarda | F6 parcial | Modo `manual` (paquete) es el default; `tiktok_inbox` y YouTube ya probados en v1 |
| Límites de uso de la suscripción de Claude | Producción lenta | Lotes; pasos mecánicos a modelos gratuitos tras benchmark (F7) |
| Límites del plan gratuito de Groq | Transcripción lenta | Cascada a Colab/Kaggle y CPU local |
| Bloqueos de descarga en plataformas fuente | Ingesta intermitente | Reintentos espaciados, cookies del operador, Colab como IP alternativa (ya usado en v1) |

## 5. Cómo se gestiona la ejecución

- **Tickets**: al aprobar este roadmap, cada fase se descompone en issues de GitHub (o Jira, si se decide) con criterios de aceptación; un *milestone* por fase.
- **Ramas y PRs**: una rama por ticket; PR con tests verdes en CI antes de integrar a `main`.
- **Continuidad**: al cerrar cada ticket se actualiza `docs/ESTADO.md` (fase actual, hecho, siguiente, bloqueos). `CLAUDE.md` apunta siempre ahí.
- **Revisión de fase**: al final de cada fase, demo del hito y ajuste del roadmap.
