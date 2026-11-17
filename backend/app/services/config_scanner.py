"""
config_scanner.py — Lista los canal_id disponibles para el selector del
frontend, sin instanciar ConfigLoader/ContextLoader (evita sus prints y el
costo de ensamblar todo el contexto solo para mostrar una etiqueta).

Respeta la misma precedencia que pipeline.py::_load_config(): si existe
contexto/nichos/<id>.yaml (v2), gana sobre config/<id>.yaml o
config/<id>/_index.yaml (v1).
"""

import yaml

from app.paths import CONFIG_DIR, CONTEXTO_DIR


def _safe_load(path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def list_canales() -> list[dict]:
    vistos = set()
    resultado = []

    nichos_dir = CONTEXTO_DIR / "nichos"
    if nichos_dir.exists():
        for f in sorted(nichos_dir.glob("*.yaml")):
            canal_id = f.stem
            nicho = _safe_load(f).get("nicho", {})
            resultado.append({
                "canal_id": canal_id,
                "descripcion": nicho.get("descripcion", ""),
                "sistema": "v2",
            })
            vistos.add(canal_id)

    if CONFIG_DIR.exists():
        for f in sorted(CONFIG_DIR.glob("*.yaml")):
            canal_id = f.stem
            if canal_id in vistos:
                continue
            meta = _safe_load(f).get("meta", {})
            resultado.append({
                "canal_id": canal_id,
                "descripcion": meta.get("descripcion", ""),
                "sistema": "v1",
            })
            vistos.add(canal_id)

        for d in sorted(CONFIG_DIR.iterdir()):
            if not d.is_dir():
                continue
            index_file = d / "_index.yaml"
            if not index_file.exists() or d.name in vistos:
                continue
            meta = _safe_load(index_file).get("meta", {})
            resultado.append({
                "canal_id": d.name,
                "descripcion": meta.get("descripcion", ""),
                "sistema": "v1-ecosistema",
            })
            vistos.add(d.name)

    return resultado
