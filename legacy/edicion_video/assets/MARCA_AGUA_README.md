# Marca de agua propia (opcional)

Para quemar un logo/handle propio en la esquina inferior derecha de cada
clip, colocá el archivo acá:

```
edicion_video/assets/marca_agua.png
```

`_con_marca_agua()` en `agent4_video_cutter.py` lo detecta automáticamente
si existe — no hace falta ningún flag ni cambio de código. Si el archivo
no existe, los clips se generan igual, simplemente sin marca de agua.

Recomendaciones para el PNG:
- Fondo transparente (canal alfa), para que no tape nada de más.
- Ancho recomendado: ~300-600px (se reescala a 150px de ancho en el clip
  final vía `_MARCA_AGUA_ANCHO`).
- Se superpone SIEMPRE en la esquina inferior derecha (`overlay=W-w-30:H-h-30`) —
  si se necesita otra posición, ajustar esa constante en el código.
