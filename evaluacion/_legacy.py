"""Acceso al piloto (legacy/) desde la evaluación: agrega legacy/ al sys.path una sola vez."""

import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
LEGACY = RAIZ_REPO / "legacy"

if str(LEGACY) not in sys.path:
    sys.path.insert(0, str(LEGACY))
