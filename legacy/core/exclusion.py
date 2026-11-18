"""
exclusion.py — CLIP-36 (R-01): canales y personas que pidieron no ser clipeados.

La lista vive en config/exclusion.yaml (versionada). Se consulta en tres puntos: al leer la metadata del video
(no se procesa), al aprobar un clip (no se encola) y antes de cada envío (se cancela). La comparación ignora
mayúsculas, tildes y espacios repetidos.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import yaml

RUTA = Path(__file__).resolve().parent.parent / "config" / "exclusion.yaml"


def _ruta() -> Path:
    return Path(os.environ["CLIPEO_EXCLUSION"]) if os.environ.get("CLIPEO_EXCLUSION") else RUTA


def normalizar(texto: str | None) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def cargar() -> dict:
    """{"canales": [...], "personas": [...]} (vacío si no hay archivo)."""
    try:
        data = yaml.safe_load(_ruta().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        data = {}
    return {k: [str(x) for x in (data.get(k) or [])] for k in ("canales", "personas")}


def guardar(lista: dict) -> None:
    ruta = _ruta()
    texto = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    cabecera = "".join(l + "\n" for l in texto.splitlines() if l.startswith("#"))
    cuerpo = yaml.safe_dump({k: lista.get(k) or [] for k in ("canales", "personas")},
                            allow_unicode=True, sort_keys=False)
    ruta.write_text(cabecera + cuerpo, encoding="utf-8")


def agregar(canal: str | None = None, persona: str | None = None) -> bool:
    """Agrega a la lista (idempotente). Devuelve True si cambió algo."""
    lista, cambio = cargar(), False
    for clave, valor in (("canales", canal), ("personas", persona)):
        if valor and normalizar(valor) not in {normalizar(x) for x in lista[clave]}:
            lista[clave].append(valor)
            cambio = True
    if cambio:
        guardar(lista)
    return cambio


def motivo(canal: str | None = None, persona: str | None = None) -> str | None:
    """Por qué está excluido (texto para el operador), o None."""
    lista = cargar()
    if canal and normalizar(canal) in {normalizar(x) for x in lista["canales"]}:
        return f"el canal «{canal}» está en la lista de exclusión (R-01)"
    if persona and normalizar(persona) in {normalizar(x) for x in lista["personas"]}:
        return f"«{persona}» pidió no ser clipeado (lista de exclusión, R-01)"
    return None


def motivo_fuente(fuente: dict | None) -> str | None:
    """Para un clip o sesión: su canal de origen o la persona de la que trata."""
    if not fuente:
        return None
    return motivo(canal=fuente.get("canal_origen"), persona=fuente.get("sobre"))
