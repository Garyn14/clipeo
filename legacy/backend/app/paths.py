"""
paths.py — Rutas compartidas + parche de sys.path/cwd.

El backend importa módulos de la raíz del repo directamente (pipeline.py,
edicion_video/, core/, contexto/) en vez de por subproceso, salvo para
lanzar la corrida completa del pipeline (ver services/pipeline_runner.py).
Cualquier módulo que necesite `import pipeline` o similar debe importar
PROJECT_ROOT de acá PRIMERO, para garantizar que sys.path ya está parchado.

Algunas de esas funciones importadas asumen, además, que el *cwd* del
proceso es la raíz del repo — ej. `_prepare_font()` en
`edicion_video/agent4_video_cutter.py` escribe/lee con la ruta relativa
`Path("stream_data")`, no una anclada a `PROJECT_ROOT`. Eso siempre fue
cierto para `pipeline.py`/`revisar_clips.py` (se invocan desde la raíz),
pero el backend arranca con cwd=`backend/` (`cd backend && uvicorn
app.main:app`). Sin este chdir, esas funciones escribirían/buscarían en
`backend/stream_data/` en vez de la carpeta real — se detectó exactamente
así durante las pruebas manuales de este v1 (apareció un
`backend/stream_data/impact.ttf` espurio).
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# CLIPEO_STREAM_DATA: carpeta de sesiones fuera de legacy/ (p. ej. D:/clipeo/stream_data en la laptop del operador)
STREAM_DATA  = Path(os.environ["CLIPEO_STREAM_DATA"]).resolve() if os.environ.get("CLIPEO_STREAM_DATA") \
    else PROJECT_ROOT / "stream_data"
CONFIG_DIR   = PROJECT_ROOT / "config"
CONTEXTO_DIR = PROJECT_ROOT / "contexto"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.chdir(PROJECT_ROOT)
