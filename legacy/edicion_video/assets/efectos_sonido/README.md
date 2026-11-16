# Efectos de sonido cortos (stingers/whoosh), Fase 15

Cada carpeta (ej. `whoosh/`, `impacto/`) puede tener uno o más archivos
`.mp3`/`.wav` cortos (idealmente <1s, sin diálogo). `_pick_sound_effect()`
en `agent4_video_cutter.py` elige uno al azar de la carpeta que coincida
con el `efecto_sonido` que devolvió Agent 3. A diferencia de la música
(mood) o la imagen de relleno, **no hay fallback a una carpeta "neutral"**
— si la carpeta del tipo pedido no tiene nada, simplemente no suena
ningún efecto en ese clip.

El efecto se mezcla anclado al `momento_enfasis_seg` del clip (el mismo
instante que ya usa el zoom/punch-in de la Fase 5) — si el clip no tiene
ese instante calculado, el efecto se omite en vez de sonar en un punto
arbitrario.

## Todavía no hay efectos reales acá

Carpeta vacía a propósito — el mecanismo ya está implementado y probado
(con un placeholder sintético generado con FFmpeg, descartado después),
pero falta curar sonidos reales antes de que `efecto_sonido` haga algo en
una corrida real. Tampoco está todavía en el prompt de Agente 3 — no
tiene sentido pedírselo a Claude mientras no haya assets para usar.

## Cómo conseguir efectos reales

Mismo criterio que la música (ver `../musica/README.md`): Pixabay
(`pixabay.com/sound-effects`) o Freesound (`freesound.org`, filtrando por
licencia CC0/sin atribución) son gratis para uso comercial. Buscar
"whoosh", "swoosh transition" o "impact hit" para tener 2-3 opciones por
carpeta.

## Formato recomendado

- Muy corto (<1s), sin diálogo ni música de fondo propia.
- Volumen ya normalizado — el código lo mezcla a un volumen fijo
  (`_EFECTO_VOLUMEN`), no compensa clips demasiado bajos o saturados.
