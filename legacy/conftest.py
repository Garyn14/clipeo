"""Permite ejecutar los tests del piloto desde la raíz del repo (`pytest legacy/tests`)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
