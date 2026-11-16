---
name: seo-refresh
description: Investiga hashtags/prácticas de SEO vigentes por plataforma (TikTok, YouTube Shorts, y a futuro Facebook Reels) para un nicho del pipeline, usando WebSearch directo en la sesión (sin gastar la API de Anthropic), y guarda el resultado curado en el bloque seo_base del YAML del nicho tras aprobación. Usar cuando el usuario pida "actualizar/refrescar los hashtags o el SEO de <nicho>" para alguna plataforma.
---

# Refresco de SEO por plataforma (`seo_base`)

Procedimiento para actualizar el bloque `seo_base` de `legacy/contexto/nichos/<id>.yaml` (hashtags base + notas de estilo por plataforma que el Agente 3 usa para armar `publicacion` en cada clip — ver `docs/ARQUITECTURA.md` §16 y `docs/ESTRUCTURA_DATOS.md`).

**Por qué existe este skill en vez de un script**: `legacy/contexto/contexto_refresh.py` hacía este tipo de investigación llamando a la API de Anthropic con la *tool* de búsqueda web — quedó deprecado porque consumía mucho de la API medida (ver memoria `preferencia-claude-code-reemplaza-scripts-de-api`). El reemplazo es que un agente de Claude Code haga la investigación directo, con su propio `WebSearch`/`WebFetch`, sin pasar por `ANTHROPIC_API_KEY`.

## 1. Investigar

Usar `WebSearch` para cada plataforma pedida (`tiktok`, `youtube_shorts`, y `facebook_reels` solo si ya está activo para ese nicho — ver `docs/ESTRUCTURA_DATOS.md`):
- Mejores prácticas vigentes de la plataforma (cuántos hashtags, dónde van, qué pesa más para el algoritmo — esto cambia con el tiempo, buscar el año actual).
- Hashtags específicos del nicho/ecosistema (ej. para `streamers_peru`: streamers peruanos, Kick Perú; para `zapatillas_peru`: vendedores de zapatillas Perú).

**Nota honesta a tener presente y a comunicarle al usuario si pregunta**: no existe una API pública confiable de "hashtags en tendencia ahora mismo" de TikTok/YouTube. Lo que se investiga son mejores prácticas y hashtags de nicho vigentes a la fecha de la búsqueda — no tendencia minuto a minuto. Por eso este refresco es periódico (cuando se pida), no algo que corra en cada clip.

## 2. Presentar para aprobación

Igual que hacía `contexto_refresh.py`: mostrar lo encontrado (hashtags candidatos + 1-2 líneas de justificación por cada uno) antes de guardar nada — no escribir el YAML sin que el usuario lo vea primero. Usar `AskUserQuestion` si hay que elegir entre variantes, o simplemente listarlo y pedir confirmación en texto si es una lista larga.

## 3. Guardar

Editar el bloque `seo_base` del nicho correspondiente en `legacy/contexto/nichos/<id>.yaml`, con este schema (ver `streamers_peru.yaml` como referencia ya poblada):

```yaml
seo_base:
  actualizado: "<fecha de hoy, YYYY-MM-DD>"
  tiktok:
    hashtags: ["#...", "#...", "#..."]     # 3-5 máximo
    notas: |
      Guía de estilo breve (cuántos hashtags, qué pesa más, etc.)
  youtube_shorts:
    hashtags: ["#Shorts", "#...", "#..."]   # #Shorts siempre primero
    tags_backend: ["...", "..."]            # keywords sin "#", no hashtags
    notas: |
      Guía de estilo breve
  facebook_reels:
    hashtags: []      # dejar vacío/placeholder mientras la plataforma no esté activa
    notas: ""
```

No hace falta tocar `legacy/agentes/agent3_viral_scorer.py` ni `legacy/contexto/context_loader.py` — ya leen `seo_base` automáticamente (`_format_seo_context()` lo inyecta en el prompt del Agente 3 en la próxima corrida).

## 4. Verificar

```bash
python -c "import yaml; yaml.safe_load(open('legacy/contexto/nichos/<id>.yaml', encoding='utf-8'))"
```

Y opcionalmente correr el Agente 3 en modo manual (skill `pipeline-manual`) sobre un rango de prueba para confirmar que el bloque `SEO BASE POR PLATAFORMA` llega actualizado en la request.
