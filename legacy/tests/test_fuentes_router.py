"""test_fuentes_router.py — CLIP-63: endpoints /fuentes del panel (sin red, sin pipeline real)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from investigacion import comun, fuentes_estaticas as fe  # noqa: E402
from test_fuentes_estaticas import AHORA, _lector  # noqa: E402


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "ex.yaml"))
    monkeypatch.setattr(fe, "ids_ya_procesados", lambda sd: set())
    from transcripcion import video_transcriber
    monkeypatch.setattr(video_transcriber, "colab_vivo", lambda timeout=5: (False, "caído"))
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    (d / "fuentes.yaml").write_text(
        "activo: true\nventana_inicial_dias: 7\npalabras_clave: [fritz sport]\ncanales:\n"
        "  - {nombre: Latina, url: 'https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx', rol: medios}\n",
        encoding="utf-8")
    from app.main import app
    from app.routers import fuentes
    lanzados = []
    monkeypatch.setattr(fuentes.subprocess, "Popen", lambda cmd, **kw: lanzados.append(cmd))
    monkeypatch.setattr(fuentes, "LOGS", tmp_path / "logs")
    c = TestClient(app)
    c.lanzados = lanzados
    return c


def test_nichos_detalle_y_404(cliente):
    assert cliente.get("/fuentes").json() == [{"nicho": "n", "cliente": "N", "canales": 1, "candidatos": 0}]
    d = cliente.get("/fuentes/n").json()
    assert d["activo"] and d["canales"][0]["ultima_revision"] is None and d["colab"] == {"vivo": False, "motivo": "caído"}
    assert cliente.get("/fuentes/otro").status_code == 404


def test_ejecutar_y_procesar(cliente, monkeypatch):
    real = fe.ejecutar
    monkeypatch.setattr(fe, "ejecutar", lambda nicho, **kw: real(nicho, lector=_lector, ahora=AHORA, **kw))
    r = cliente.post("/fuentes/n/ejecutar", json={}).json()
    assert r["canales"][0]["canal"] == "Latina" and r["canales"][0]["nuevos"] >= 1
    d = cliente.get("/fuentes/n").json()
    ids = [c["id"] for c in d["candidatos"]]
    assert "AAA" in ids and d["canales"][0]["ultima_revision"]
    assert cliente.post("/fuentes/n/procesar", json={"ids": ["NOEXISTE"]}).status_code == 400
    r = cliente.post("/fuentes/n/procesar", json={"ids": ["AAA", "NOEXISTE"]}).json()
    assert r["iniciado"] == ["AAA"] and cliente.lanzados[0][-3:] == ["procesar", "n", "AAA"]
