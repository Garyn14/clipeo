# Anexo al diagnóstico — la versión real del piloto (`v1_full`)

> Fecha: 2026-11-17 · Rama revisada: `v1_full` (commit `1c3437a`, "version 01")
> Complementa y **corrige** [`DIAGNOSTICO_ACTUAL.md`](DIAGNOSTICO_ACTUAL.md), que se hizo sobre `main` (commit `5653b66`).
> `v1_full` es la versión que el operador usa hoy para producir clips: es el **piloto de referencia**.

---

## 1. Resumen

`main` solo tenía la base del piloto. `v1_full` agrega **+18.800 líneas** (103 archivos nuevos y 23 modificados):
una aplicación web (backend + frontend), publicación real, un **sistema de calidad basado en datos** y
orquestación por pasos. **293 tests, todos pasan** (3,3 s).

El flujo general es una buena referencia. Lo que más cambia respecto del diagnóstico anterior: **la calidad
ya tiene una base sólida y medible** (memoria del nicho, juez, auditoría, correcciones). Lo que sigue débil es
**la edición** (casi sin cambios) y **la detección** (solo texto).

## 2. Qué trae `v1_full` que el diagnóstico anterior no conocía

| Área | Qué hay | Estado |
|---|---|---|
| **Juez editorial** (`agentes/juez.py`) | Único filtro de calidad del chunk: decide qué candidatos se publican comparando con la **memoria del nicho** (clips reales medidos) y las **correcciones del editor**. Clasifica tipo de momento, qué está en juego, parecidos reales, fuerza 1–10 y título. | Sólido |
| **Memoria del nicho** (`investigacion/<nicho>/referencias.yaml`) | Hallazgos con evidencia de **1.178 videos de 21 cuentas**: "historia, no formato", "nombrar al personaje", "arrancar en el conflicto", fórmula de título y **tipos de momento que funcionan** con ejemplos medidos. | Muy valioso; **solo existe para `zapatillas_peru`** |
| **Métrica outlier** (`investigacion/comun.py`) | Vistas ÷ mediana de la cuenta: mide el éxito relativo a cada cuenta (excluye videos de < 3 días). | Es la métrica correcta |
| **Investigación** (`recolectar.py`, `muestrear.py`, `transcribir_muestra.py`) | Mide cuentas del nicho con yt-dlp (sin descargar), elige top y fondo por outlier, descarga muestras, transcribe. Datos: `videos.jsonl` (1.718 filas), `muestra.jsonl`, `cuentas.yaml`. | Manual, por scripts |
| **Correcciones del editor** (`correcciones.jsonl`) | Cada aprobación, edición o descarte en la revisión web vuelve al juez como ejemplo. | Circuito cerrado (21 registros) |
| **Auditoría** (`agentes/auditoria.py`) | Busca momentos buenos que el detector **no** le pasó al juez: mide la cobertura. | Bajo demanda, fuera del flujo |
| **Experimentos** (`experimento_juez.json`, `experimento_a3.json`) | Comparaciones A/B de versiones del juez y del Agente 3 sobre casos reales. | Hay método de comparación |
| **IA sin costo** (`ai_client/cli_provider.py`) | `AI_PROVIDER=claude_cli` por defecto: cada llamada ejecuta `claude -p` aislado con la sesión de Claude Code de la máquina. Sin API ni gasto. | Funciona; requiere Claude Code instalado y con sesión |
| **Orquestación por pasos** (`core/pasos.py`) | Pasos con estado, tiempos, errores reintentables y salidas en `pipeline_estado.json`; reanuda; `--reintentar <paso>`. | Es un engine de pasos (acoplado al dominio) |
| **Backend** (FastAPI, `backend/`) | API de sesiones, corridas, clips, errores, configuración y publicaciones; lanza `pipeline.py` como subproceso. | Funciona en local |
| **Frontend** (React + Vite, `frontend/`) | Sesiones, detalle por paso (con request/response de Claude), **revisión de clips**, errores con reintento masivo, configuración, publicaciones. | Funciona en local |
| **Publicación** (`backend/app/publicacion/`) | Cola por nicho y plataforma en SQLite, horarios (8/12/16/20 Lima), cuentas reales o simuladas, **YouTube** (subida directa vía API) y **TikTok** (borrador a la bandeja). Trazabilidad por eventos, sin reenvíos ciegos. | Funciona; probado (≈1.000 líneas de tests) |

Flujo de calidad actual por chunk:

```
transcripción → A0 hablantes → A1 detecta AMPLIO → A2 ajusta bordes (sin juzgar)
  → JUEZ (memoria del nicho + correcciones) → A3 copy solo de aprobados → corte (A4)
  → revisión web → correcciones.jsonl (vuelve al juez) → cola de publicación
```

## 3. Diagnóstico de calidad (el foco)

| Etapa | Estado en `v1_full` | Brecha |
|---|---|---|
| **Detección** (A1) | Busca amplio a propósito, guiado por la memoria; solo lee **texto** de la transcripción. | Sin señales de audio (risas, gritos, energía), chat ni imagen. La auditoría mide lo que se escapa, pero no está en el flujo. |
| **Selección** (juez) | Fuerte: criterio basado en datos reales, no en opinión. | Memoria **solo para un nicho**; sin memoria el paso se omite. |
| **Bordes** (A2) | Ajusta inicio y fin; la memoria pide **arrancar en el conflicto**. | Solo corta un rango continuo: no puede reordenar ni recortar dentro del clip. |
| **Edición** (A4) | **Casi sin cambios** respecto de la base (10 líneas). Ejecuta, no decide. | **Es la brecha principal**: no hay estructura (gancho primero), ni cortes de tiempos muertos, ni encuadre por tramo decidido por el contenido. |
| **Control visual** | No existe. | Nadie verifica el clip renderizado (texto sobre caras, encuadre, barras). |
| **Aprendizaje** | Correcciones automáticas al juez; memoria del nicho construida **a mano** con scripts. | No hay medición automática de los clips propios publicados ni actualización periódica de la memoria con evidencia. |

## 4. Otros hallazgos

- **Portabilidad**: siguen 7 referencias a Windows (ruta WinGet de FFmpeg, fuentes `C:\Windows\Fonts`, `taskkill`).
- **Transcripción**: el backend usa siempre Colab (`COLAB_TRANSCRIBE_URL`), con túnel efímero.
- **Datos operativos** en archivos (`stream_data/`, `runs.json`) + SQLite solo para la cola de publicación.
- **`--live`** sigue roto; los lives se graban y se procesan como video.
- **Documentación** del backend (`backend/docs/ARQUITECTURA.md`, `API.md`, `DECISIONES.md`) y del frontend: buena.

## 5. Qué cambia respecto del análisis y el plan anteriores

| Antes (sobre `main`) | Ahora (sobre `v1_full`) |
|---|---|
| El piloto congelado en `legacy/` es el commit `5653b66`. | **El piloto de referencia es `v1_full`**: `legacy/` debe reemplazarse por esa versión. |
| La publicación debía reconstruirse (F6). | **Ya existe** y está probada; se reutiliza. |
| La web de revisión era F5 (FastAPI + HTMX). | **Ya existe** (FastAPI + React); se reutiliza y mejora. |
| El engine de pasos se construía desde cero (F1). | `core/pasos.py` ya orquesta por pasos con reintentos: **evolucionar, no rehacer**. |
| Operador IA: peticiones en espera hasta que Claude Code las resuelva. | `claude_cli` ya llama a Claude Code automáticamente desde la máquina, sin API. |
| El golden set había que armarlo desde cero (CLIP-20). | **Ya hay datos**: `videos.jsonl`, `referencias.yaml`, `muestra.jsonl`, `correcciones.jsonl` y los experimentos. Falta convertirlos en un conjunto de evaluación repetible. |
| El ciclo de aprendizaje era nuevo. | Existe a mano (investigación + memoria + correcciones); falta automatizarlo y medir los clips propios. |

## 6. Conclusión

Con el foco acordado (**clips de calidad**), el trabajo se concentra en:
1. **Medir**: convertir los datos de investigación y las correcciones en un conjunto de evaluación y una línea base.
2. **Edición pensada**: dirección editorial con estructura (gancho primero, cortes, encuadre) que el render ejecute.
3. **Detección con más señales** y la auditoría integrada para medir la cobertura.
4. **Control visual** del clip terminado.
5. **Aprendizaje continuo**: medir los clips propios publicados y actualizar la memoria con evidencia; extender la memoria a otros nichos.

Infraestructura, nube, publicación y prospección pasan a segundo plano: lo existente alcanza por ahora.
