# Piloto v2.0 (congelado)

Código del piloto que ya produjo clips reales. Se conserva **tal cual** como referencia y para seguir
produciendo clips mientras se construye la v2 (ADR-008, migración *strangler*). No se agregan funciones nuevas aquí:
solo correcciones mínimas para que siga funcionando (p. ej. portabilidad, CLIP-19).

- Versión exacta congelada: commit `5653b66` (tag `piloto-v2.0`).
- Documentación del piloto: `docs/ARQUITECTURA.md`, `docs/COMANDOS.md`, `docs/ESTRUCTURA_DATOS.md`, `docs/APRENDIZAJE.md`.
- Cambios respecto al commit congelado: se movió a `legacy/`, se eliminó el modo `--live` (estaba roto) y
  `archive/` (sigue disponible en el historial git).

## Cómo usarlo

Todos los comandos se ejecutan **desde esta carpeta** (`cd legacy`), porque el piloto usa rutas relativas
(`stream_data/`, `config/`, `contexto/`):

```bash
cd legacy
pip install -r requirements.txt
python pipeline.py --video <url_o_ruta> --config <canal_id> [--revisar]
python pipeline.py --test stream_data/<session_id>/ --config <canal_id>
```

Lives: `python captura/tiktok_capture.py --usuario @handle` y luego `pipeline.py --video` sobre cada chunk.

El `.env` del piloto se busca en el directorio de trabajo (`legacy/.env`) o en sus padres; usar el `.env.example` de la raíz.

## Tests

```bash
python -m pytest -q legacy/tests   # desde la raíz
cd legacy && python -m pytest -q   # o desde aquí
```
