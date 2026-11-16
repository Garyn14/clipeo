# Imágenes de relleno (layout "imagen", Fase 13)

Cada carpeta (ej. `neutral/`, `tension/`, ...) puede tener una o más
imágenes `.jpg`/`.jpeg`/`.png`. `_pick_imagen_relleno()` en
`agent4_video_cutter.py` elige una al azar de la carpeta que coincida con
el `mood` del clip, y cae a `neutral/` si esa carpeta no tiene nada. Si no
hay ninguna imagen disponible en absoluto, `layout: "imagen"` cae a
`"pillarbox"` sin avisar — el clip nunca falla por falta de este asset.

## Todavía no hay imágenes reales acá

Carpeta vacía a propósito — el layout ya está implementado y probado
(con un placeholder degradado generado con FFmpeg, ya descartado), pero
falta curar imágenes reales antes de que `layout: "imagen"` haga algo en
una corrida real.

## Cómo conseguir imágenes reales

Mismo criterio que la música (ver `../musica/README.md`): Pixabay Images
(`pixabay.com/images`) es gratis para uso comercial, sin atribución
requerida. Preferir imágenes abstractas/decorativas (gradientes, texturas,
patrones) — nada con marcas, logos o personas reconocibles. Evitar
gameplay real (esa vía sigue bloqueada por la decisión legal pendiente de
sourcing, ver plan de Fase 5/13).

## Formato recomendado

- Horizontal, ancho generoso (el código la escala a 1080px de ancho).
- Sin texto quemado propio — el hook del clip ya se superpone encima.
