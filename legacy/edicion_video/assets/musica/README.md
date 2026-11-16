# Música de fondo por mood

Cada carpeta (`tension/`, `comedia/`, `revelacion/`, `neutral/`) puede tener
una o más pistas `.mp3`/`.wav`/`.m4a`. `_pick_music_track()` en
`agent4_video_cutter.py` elige una al azar de la carpeta que coincida con
el `mood` que devolvió Agent 3 (ver `contexto/nichos/*.yaml`), y cae a
`neutral/` si esa carpeta no tiene nada.

## ⚠️ Los archivos `PLACEHOLDER_*.mp3` de hoy NO son música real

Son tonos sintéticos generados con FFmpeg (`sine`/`aevalsrc`), solo para
probar que la mezcla de audio (`amix` en `_cut_clip`) funciona bien de
punta a punta sin depender de conseguir música real primero. Bórralos
cuando agregues pistas de verdad — están ahí únicamente como fixture de
prueba de ingeniería, no como contenido para publicar.

## Cómo conseguir música real

Pixabay Music (`pixabay.com/music`) es gratis para uso comercial, sin
atribución requerida — pero el sitio bloquea scraping automático, así que
hay que bajar los archivos a mano desde el navegador:

- Tensión / rivalidad: https://pixabay.com/music/search/tension/
- Comedia / humor: https://pixabay.com/music/search/comedy/
- Revelación / suspenso: https://pixabay.com/music/search/suspense/
- Neutral / ambiente: https://pixabay.com/music/search/background/

Bajá 2-3 pistas cortas (15-30s alcanza, `_cut_clip` las loopea si el clip
es más largo) por carpeta y listo — no hace falta tocar código.
