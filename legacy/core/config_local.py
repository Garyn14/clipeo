"""
config_local.py — CLIP-54: la configuración de la máquina en un solo lugar (el `.env`), sin variables a mano.

Se lee `legacy/.env` y el `.env` de la raíz del repo (en la laptop del operador vive ahí). Las rutas pueden ser
relativas a la raíz del repo, para que el `.env` sea portable entre máquinas:

    CLIPEO_STREAM_DATA=stream_data          # sesiones
    PUBLICACION_DB=data/publicacion.db      # cola y cuentas de publicación (ADR-015)

Una variable ya definida en el entorno gana sobre el `.env` (se puede seguir pasando a mano para pruebas).
"""

from __future__ import annotations

import os
from pathlib import Path

LEGACY = Path(__file__).resolve().parent.parent
RAIZ_REPO = LEGACY.parent


def cargar_env() -> None:
    """Carga legacy/.env y el .env de la raíz sin pisar lo que ya esté en el entorno."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for p in (LEGACY / ".env", RAIZ_REPO / ".env"):
        if p.exists():
            load_dotenv(p, override=False)


def ruta(clave: str, defecto: Path) -> Path:
    """Ruta configurada en el entorno/.env (relativa a la raíz del repo si no es absoluta), o `defecto`."""
    cargar_env()
    valor = (os.environ.get(clave) or "").strip()
    if not valor:
        return defecto
    p = Path(valor)
    return p if p.is_absolute() else (RAIZ_REPO / p).resolve()
