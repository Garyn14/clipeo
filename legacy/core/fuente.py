"""
fuente.py — CLIP-27: de dónde viene el video de una sesión (stream propio del cliente o medios de terceros).

La sesión guarda su fuente en pipeline_estado.json (`fuente`), así retomar, reintentar o la web nunca "olvidan"
que una sesión es de medios:

    {"tipo": "medios", "sobre": "Tío Fritz", "url": "...", "canal_origen": "Panorama"}

Sin `fuente` (sesiones viejas o streams) todo funciona como siempre.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

DIR_ENTIDADES = Path(__file__).resolve().parent.parent / "contexto" / "entidades"


def nombre_sobre(valor: str) -> str:
    """`--sobre`: id de contexto/entidades/<id>.yaml (se usa su nombre) o un nombre libre."""
    valor = (valor or "").strip()
    ruta = DIR_ENTIDADES / f"{valor.lower()}.yaml"
    if valor and ruta.exists():
        try:
            nombre = ((yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}).get("entidad") or {}).get("nombre")
            if nombre:
                return str(nombre)
        except (OSError, yaml.YAMLError):
            pass
    return valor


def nueva(tipo: str, sobre: str, url: str) -> dict:
    return {"tipo": tipo, "sobre": nombre_sobre(sobre), "url": url}


def _estado_de(dir_: Path) -> Path | None:
    """pipeline_estado.json de la sesión, desde la sesión o desde un chunk (chunks/<id>/)."""
    for cand in (dir_, dir_.parent.parent):
        p = cand / "pipeline_estado.json"
        if p.exists():
            return p
    return None


def leer(dir_: Path) -> dict | None:
    p = _estado_de(Path(dir_))
    if p is None:
        return None
    try:
        fuente = json.loads(p.read_text(encoding="utf-8")).get("fuente")
    except (OSError, json.JSONDecodeError):
        return None
    if not (isinstance(fuente, dict) and fuente.get("tipo")):
        return None
    if not fuente.get("canal_origen"):   # video descargado antes de marcar la sesión como medios
        try:
            meta = json.loads((p.parent / "metadata.json").read_text(encoding="utf-8"))
            fuente["canal_origen"] = meta.get("uploader") or meta.get("channel") or None
        except (OSError, json.JSONDecodeError):
            pass
    return fuente


def es_medios(fuente: dict | None) -> bool:
    return bool(fuente) and fuente.get("tipo") == "medios"


def bloque_juez(fuente: dict | None) -> str:
    """Contexto extra para el juez: quién es el personaje cuando el canal es de TV/prensa."""
    if not es_medios(fuente):
        return ""
    sobre = fuente.get("sobre") or "el personaje"
    canal = fuente.get("canal_origen") or "(desconocido)"
    return (
        f"FUENTE: medios (TV/prensa), canal «{canal}»\n"
        f"SOBRE: {sobre} — el título nombra a {sobre} aunque en el video no se le nombre. "
        f"El canal NO es el personaje: conductores, periodistas e invitados no son el dueño del canal "
        f"(esta regla reemplaza la de \"prevalece el dueño del canal\")."
    )


def credito(fuente: dict | None) -> str:
    """Crédito al titular en la descripción de cada plataforma (R-01)."""
    if not es_medios(fuente) or not fuente.get("canal_origen"):
        return ""
    return f"Fuente: {fuente['canal_origen']}"
