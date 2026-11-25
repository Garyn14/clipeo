"""
test_estado_operacion.py — CLIP-84: GET /estado (pie de la barra lateral). Sin red: Colab y Claude simulados.
"""

import sys
from pathlib import Path

import pytest


@pytest.fixture
def cliente(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import estado
    from transcripcion import video_transcriber

    llamadas = {"colab": 0, "claude": 0}

    def colab(timeout=10.0):
        llamadas["colab"] += 1
        return False, "el túnel de Colab no responde"

    def claude(nombre, timeout=20):
        llamadas["claude"] += 1
        return {"sesion": True, "cuenta": "op@ejemplo.com", "plan": "pro", "metodo": "claude.ai"}

    monkeypatch.setattr(video_transcriber, "colab_vivo", colab)
    monkeypatch.setattr(estado.perfiles, "estado", claude)
    monkeypatch.setattr(estado.perfiles, "perfil_activo", lambda: "cuenta2")
    monkeypatch.setattr(estado.state_reader, "list_errores", lambda: [{"paso": "agente2"}, {"paso": "agente0"}])
    estado._cache.clear()
    return TestClient(app), llamadas


def test_estado_resume_colab_claude_y_errores(cliente):
    c, _ = cliente
    r = c.get("/estado").json()
    assert r["colab"] == {"vivo": False, "motivo": "el túnel de Colab no responde"}
    assert r["claude"] == {"perfil": "cuenta2", "cuenta": "op@ejemplo.com", "sesion": True, "plan": "pro"}
    assert r["errores"] == 2


def test_estado_cachea_lo_caro_y_refrescar_lo_limpia(cliente):
    c, llamadas = cliente
    c.get("/estado")
    c.get("/estado")
    assert llamadas == {"colab": 1, "claude": 1}
    c.get("/estado?refrescar=true")
    assert llamadas == {"colab": 2, "claude": 2}
