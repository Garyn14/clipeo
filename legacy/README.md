# Piloto `v1_full` (referencia)

Versión del piloto que el operador usa hoy para producir clips (rama `v1_full`, commit `1c3437a`). Es la base que
la v2 **evoluciona**: los cambios de calidad se hacen sobre este código según `docs/ROADMAP.md`.

- Guía completa del piloto: [`legacy/CLAUDE.md`](CLAUDE.md) y `legacy/docs/` (arquitectura, comandos, estructura
  de datos, aprendizaje). Backend: `legacy/backend/docs/`. Frontend: `legacy/frontend/docs/`.
- Diagnóstico: `docs/DIAGNOSTICO_V1_FULL.md`.
- Versión anterior (base `5653b66`): tag `piloto-v2.0`.

## Diferencias con la rama `v1_full` (CLIP-23)

Solo de ubicación y configuración, sin cambios funcionales:
- El código vive en `legacy/` en vez de la raíz.
- No se copiaron: `archive/` (sigue en la rama `v1_full`), `.claude/` (el skill `seo-refresh` está en la raíz con
  rutas ajustadas; `pipeline-manual` se eliminó porque `AI_PROVIDER=claude_cli` lo reemplaza), `.env.example` y
  `.gitignore` (fusionados con los de la raíz).
- Se agregó `legacy/conftest.py` para correr los tests desde la raíz.

## Cómo usarlo

Todos los comandos se ejecutan **desde esta carpeta**, porque el piloto usa rutas relativas (`stream_data/`,
`config/`, `contexto/`):

```bash
cd legacy
pip install -r requirements.txt
python pipeline.py --video <url_o_ruta> --config <canal_id> [--revisar]
```

Panel web (backend + frontend): ver `legacy/CLAUDE.md`, sección "Web panel".

`.env`: copiar el `.env.example` de la raíz a `legacy/.env`.

## Tests

```bash
python -m pytest -q legacy/tests   # desde la raíz (293 tests)
cd legacy && python -m pytest -q   # o desde aquí
```
