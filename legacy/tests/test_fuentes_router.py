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
    class _Proc:
        def poll(self):
            return None                      # sigue corriendo (no falló al arrancar)

    monkeypatch.setattr(fuentes.subprocess, "Popen", lambda cmd, **kw: lanzados.append(cmd) or _Proc())
    monkeypatch.setattr(fuentes.time, "sleep", lambda s: None)
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


def test_lanzar_y_esperar_registra_la_corrida(tmp_path, monkeypatch):
    """Lo que lanza Fuentes queda en runs.json como una corrida más (el panel la ve activa y con log)."""
    import json
    from app.services import pipeline_runner as pr
    monkeypatch.setattr(pr, "RUNS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(pr, "RUNS_LOG_DIR", tmp_path)
    run_id, rc = pr.lanzar_y_esperar([sys.executable, "-c", "print('hola')"], "sesion_x", "fuentes")
    run = json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))[run_id]
    assert rc == 0 and run["session_id"] == "sesion_x" and run["accion"] == "fuentes" and run["returncode"] == 0
    assert "hola" in (tmp_path / f"{run_id}.log").read_text(encoding="utf-8")


def test_clip71_anteriores_y_descartar(cliente, monkeypatch):
    real = fe.ejecutar
    monkeypatch.setattr(fe, "ejecutar", lambda nicho, **kw: real(nicho, lector=_lector, ahora=AHORA, **kw))
    fe._guardar_historial("n", [{"id": "VIEJO1", "titulo": "De otra búsqueda", "canal": "Latina", "rol": "medios",
                                 "estado": "nuevo"}])
    r = cliente.post("/fuentes/n/ejecutar", json={}).json()
    assert r["dias"] == 1                                         # rango por defecto: último día
    d = cliente.get("/fuentes/n").json()
    assert {c["id"] for c in d["candidatos"]} == {"AAA", "PROC"} and [c["id"] for c in d["anteriores"]] == ["VIEJO1"]
    assert d["ultima_busqueda"]["dias"] == 1 and "ids" not in d["ultima_busqueda"]
    r = cliente.post("/fuentes/n/procesar", json={"ids": ["VIEJO1"]}).json()   # lo anterior también se procesa
    assert r["iniciado"] == ["VIEJO1"]
    assert cliente.post("/fuentes/n/descartar", json={"ids": ["AAA", "PROC"]}).json() == {"descartados": ["AAA", "PROC"]}
    assert cliente.post("/fuentes/n/descartar", json={"ids": ["AAA"]}).status_code == 400
    assert cliente.get("/fuentes/n").json()["candidatos"] == []
