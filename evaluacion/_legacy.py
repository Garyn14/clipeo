"""Acceso al piloto (legacy/) desde la evaluación: agrega legacy/ al sys.path una sola vez."""

import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
LEGACY = RAIZ_REPO / "legacy"

if str(LEGACY) not in sys.path:
    sys.path.insert(0, str(LEGACY))

# La consola de Windows (cp1252) no puede mostrar emojis/símbolos (⚠, ✅): forzar UTF-8 como el piloto.
for _flujo in (sys.stdout, sys.stderr):
    try:
        _flujo.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
