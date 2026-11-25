# Alta de un cliente nuevo (onboarding)

> CLIP-80 (S18). Escrita a partir del alta del cliente 2, **Franco Vidal** (@nandoclips76), el 2026-11-21. Insumo para
> automatizar el alta en la épica Q6 (CLIP-26). Quién hace cada paso: **[Agente]** = Claude en sesión,
> **[Operador]** = acciones en apps y decisiones.

## Antes de empezar (decisiones del operador)

1. **Quién es el cliente** y si la cuenta es suya o una cuenta de clips del operador sobre él (Franco: cuenta del
   operador *sobre* el personaje, como @nandoclips93 con Tío Fritz).
2. **Objetivo:** viralidad, venta o ambos (Franco: solo viralidad → el juez no da nota comercial).
3. **Dónde se publica:** cuentas de TikTok/YouTube (Franco: solo TikTok al inicio).
4. **Fuentes:** dónde está el material (las consigue el operador).

## Pasos

| # | Paso | Quién | Archivos / dónde | Tiempo (Franco) |
|---|---|---|---|---|
| 1 | Diagnóstico de la cuenta existente: leer todos sus videos y comparar temas, duración y rendimiento | Agente | `investigacion/negocio.py` (lector) | 10 min |
| 2 | Perfil del cliente: nicho con prompts del detector, copy y refinamiento; juez y objetivo; duración; reglas propias (p. ej. regla política); publicación | Agente | `contexto/nichos/<nicho>.yaml` | 30 min |
| 3 | Entidad del personaje (lore, polémicas, apodos, reglas de títulos) al día, con búsqueda web | Agente | `contexto/entidades/<entidad>.yaml` | 15 min |
| 4 | Cuentas de referencia (oficial, fans/clips, propia) | Agente (+ operador si conoce cuentas) | `investigacion/<nicho>/cuentas.yaml` | 10 min |
| 5 | Medir las cuentas | Agente | `python investigacion/recolectar.py <nicho>` → `videos.jsonl` | ~5 min (11 cuentas) |
| 6 | Muestra top/fondo y descarga | Agente | `python investigacion/muestrear.py <nicho> --top 20 --fondo 8 --propia 6` | ~30 min (62 clips) |
| 7 | Levantar Colab y transcribir la muestra | Agente | `docs/CUENTAS.md`; `python investigacion/transcribir_muestra.py <nicho>` | 5 min + ~8 s por clip |
| 8 | Curar la memoria (tipos que funcionan con ejemplos y outlier, lo que no funciona, hallazgos) | Agente | `investigacion/<nicho>/referencias.yaml` | 30 min |
| 9 | **Aprobar la memoria** | Operador | — | — |
| 10 | Caras de referencia (videos de la cuenta oficial) y verificación sobre la muestra | Agente | `python -m edicion_video.referencia_cara "<Nombre>" <videos>` → `assets/caras/` (fuera del repo) | 5 min |
| 11 | Archivo de fuentes (cliente, palabras clave) | Agente | `investigacion/<nicho>/fuentes.yaml` | 2 min |
| 12 | **Agregar los canales** (propio / medios) | Operador | Panel → Fuentes → Administrar fuentes | — |
| 13 | **Conectar la cuenta de publicación** | Operador | Panel → Publicaciones → TikTok, nicho `<nicho>` | — |
| 14 | Primera foto de Negocio | Agente | `python -m investigacion.negocio actualizar <nicho>` | 1 min |
| 15 | Demo: procesar 1–2 videos, revisar, aprobar, borrador a la cuenta | Operador + agente | Panel | — |

Total del agente para el cliente 2: **unas 2–3 horas**, la mayor parte esperando descargas y Colab.

## Lecciones del cliente 2

- **Verificar el canal real de cada plataforma.** `kick.com/francovidal` existe pero no tiene grabados; el canal real es
  `kick.com/francovidalalcalde` (se vio en un edit de un fan). Buscar el handle en los propios videos del personaje.
- **Las cuentas de referencia se contaminan:** una cuenta de "cruce" (@kickasosperuoff) resultó ser de fútbol. Revisar
  la muestra antes de usarla.
- **Lo que no funciona es tan útil como lo que sí:** para Franco, la propaganda y el protocolo rinden 0,1x. Eso se
  convirtió en regla del copy.
- **Duración:** comparar la de la cuenta propia con la del ecosistema (Franco: 99 s propia vs 20–35 s de los fans).
- **Momentos sin diálogo** (edits con música, momentos visuales) no los encuentra el detector, que lee la
  transcripción.
- **Colab:** la cuenta principal puede quedar sin GPU; pasar a la de respaldo sin preguntar.
- **El sistema ya era multi-cliente:** no hizo falta código; el alta es configuración + investigación.

## Qué automatizar para el cliente 3 (prioridad)

1. **Un comando de alta** que cree el esqueleto: nicho (copiado de una plantilla), entidad, `fuentes.yaml`,
   `cuentas.yaml`, con el nombre y la cuenta de publicación.
2. **Pipeline de memoria en un solo comando:** recolectar → muestrear → transcribir (con aviso si Colab no está) y un
   resumen listo para curar.
3. **Plantilla de nicho por tipo de personaje** (vendedor, streamer, político-streamer) para no partir de cero.
4. **Campo de nicho en Publicaciones** como selector (hoy se escribe a mano).
