"""test_fuentes_config.py — CLIP-66/67: tipos de fuente desacoplados y edición de fuentes (sin red)."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from investigacion import comun, fuentes_config as fc, fuentes_estaticas as fe, tipos_fuente as tf

AHORA = datetime.now(timezone.utc)


class Simulado(tf.TipoFuente):
    """Plataforma de prueba: demuestra que una fuente nueva recorre todo sin tocar el código común."""
    clave = "simulado"
    nombre = "Simulado"

    def resolver(self, entrada):
        if not entrada.startswith("sim://"):
            raise tf.FuenteError("link inválido")
        return {"nombre": entrada[6:].title(), "url": entrada}

    def listar(self, canal):
        return [{"id": f"{canal['url'][6:]}-{i}", "titulo": f"Video {i} de Fritz Sport", "descripcion": "",
                 "publicado": AHORA - timedelta(days=i), "url": f"{canal['url']}/v{i}"} for i in range(1, 4)]


class ManualSimulado(tf.TipoFuente):
    clave = "manual_sim"
    nombre = "Manual simulado"
    automatico = False

    def info_video(self, link):
        if "roto" in link:
            raise tf.FuenteError("sitio no soportado")
        return {"id": link.rsplit("/", 1)[-1], "titulo": f"Video {link[-1]}", "canal": "Canal X",
                "publicado": AHORA, "url": link}


@pytest.fixture
def nicho(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "ex.yaml"))
    (tmp_path / "ex.yaml").write_text("canales: [Prohibido]\npersonas: []\n", encoding="utf-8")
    monkeypatch.setattr(fe, "ids_ya_procesados", lambda sd: {"YA"})
    monkeypatch.setitem(tf.REGISTRO, "simulado", Simulado())
    monkeypatch.setitem(tf.REGISTRO, "manual_sim", ManualSimulado())
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    (d / "fuentes.yaml").write_text("# encabezado que se conserva\nactivo: true\npalabras_clave: [fritz sport]\n"
                                    "canales: []\n", encoding="utf-8")
    return d


def test_registro_trae_youtube_manual_y_proximamente():
    claves = {t["clave"]: t for t in tf.tipos()}
    assert claves["youtube"]["implementado"] and claves["youtube"]["automatico"]
    assert claves["manual"]["implementado"] and not claves["manual"]["automatico"]
    assert not claves["twitch"]["implementado"]
    assert claves["kick"]["implementado"] and claves["kick"]["roles"] == ["propio"]
    with pytest.raises(tf.FuenteError):
        tf.obtener("inexistente")


def test_tipo_simulado_recorre_agregar_buscar_y_candidatos(nicho):
    vista = fc.previsualizar("simulado", "sim://fritzlandia")
    assert vista["nombre"] == "Fritzlandia" and len(vista["videos"]) == 3
    fc.agregar_canal("n", "simulado", "sim://fritzlandia", "propio")
    texto = (nicho / "fuentes.yaml").read_text(encoding="utf-8")
    assert texto.startswith("# encabezado que se conserva")
    assert yaml.safe_load(texto)["canales"][0]["plataforma"] == "simulado"

    r = fe.ejecutar("n")                                   # sin lector inyectado: usa el registro
    assert r["canales"] == [{"canal": "Fritzlandia", "nuevos": 3, "descartados": 0}]
    cands = fe.candidatos("n")
    assert {c["url"] for c in cands} == {"sim://fritzlandia/v1", "sim://fritzlandia/v2", "sim://fritzlandia/v3"}
    assert fc.aportes("n")["Fritzlandia"]["nuevo"] == 3


def test_validaciones_al_agregar(nicho):
    fc.agregar_canal("n", "simulado", "sim://uno", "medios")
    with pytest.raises(tf.FuenteError, match="ya está"):
        fc.agregar_canal("n", "simulado", "sim://uno", "medios")
    with pytest.raises(tf.FuenteError, match="exclusión"):
        fc.agregar_canal("n", "simulado", "sim://prohibido", "medios")
    with pytest.raises(tf.FuenteError, match="inválido"):
        fc.agregar_canal("n", "simulado", "http://otra", "medios")
    with pytest.raises(tf.FuenteError, match="rol"):
        fc.agregar_canal("n", "simulado", "sim://dos", "jefe")
    with pytest.raises(tf.FuenteError, match="elige el rol"):     # sin rol preseleccionado: hay que elegirlo
        fc.agregar_canal("n", "simulado", "sim://dos", "")
    with pytest.raises(tf.FuenteError, match="no disponible|no se agrega"):
        fc.agregar_canal("n", "twitch", "twitch.tv/x", "medios")
    with pytest.raises(tf.FuenteError, match="solo admite el rol Propio"):   # CLIP-70: Kick solo propio
        fc.agregar_canal("n", "kick", "kick.com/x", "medios")


def test_pausar_editar_y_quitar_conserva_historial(nicho):
    fc.agregar_canal("n", "simulado", "sim://uno", "propio")
    fc.editar_canal("n", "sim://uno", activo=False, nombre="Uno TV", rol="medios")
    canal = fe.cargar_config("n")["canales"][0]
    assert canal == {"nombre": "Uno TV", "plataforma": "simulado", "url": "sim://uno", "rol": "medios", "activo": False}
    assert fe.ejecutar("n")["canales"] == []               # pausado: no se revisa
    fc.editar_canal("n", "sim://uno", activo=True)
    fe.ejecutar("n")
    fc.quitar_canal("n", "sim://uno")
    assert fe.cargar_config("n")["canales"] == []
    assert len(fe.leer_historial("n")) == 3                # el historial queda
    with pytest.raises(tf.FuenteError):
        fc.quitar_canal("n", "sim://uno")


def test_palabras_clave(nicho):
    assert fc.guardar_palabras("n", ["Tío Fritz", " tío fritz ", "", "fritz sport"]) == ["Tío Fritz", "fritz sport"]
    assert fe.cargar_config("n")["palabras_clave"] == ["Tío Fritz", "fritz sport"]


def test_lista_manual_agrega_candidatos_con_dedup_y_errores(nicho):
    r = fc.agregar_links("n", ["https://x.com/a1", "https://x.com/roto", "https://x.com/YA", "https://x.com/a1", ""],
                         "medios", tipo_clave="manual_sim")
    assert [x["ok"] for x in r] == [True, False, False, False]
    assert "no soportado" in r[1]["motivo"] and "ya estaba" in r[2]["motivo"]
    cands = fe.candidatos("n")
    assert len(cands) == 1 and cands[0]["rol"] == "medios" and cands[0]["fuente"] == "manual_sim"


def test_router_administrar(nicho, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from fastapi.testclient import TestClient
    from app.main import app
    from transcripcion import video_transcriber
    monkeypatch.setattr(video_transcriber, "colab_vivo", lambda timeout=5: (False, "caído"))
    c = TestClient(app)
    assert any(t["clave"] == "simulado" for t in c.get("/fuentes/tipos").json())
    assert c.post("/fuentes/n/canales/previsualizar", json={"plataforma": "simulado", "entrada": "x"}).status_code == 400
    sin_rol = c.post("/fuentes/n/canales", json={"plataforma": "simulado", "entrada": "sim://tres"})
    assert sin_rol.status_code == 400 and "elige el rol" in sin_rol.json()["detail"]
    assert c.post("/fuentes/n/manual", json={"links": ["https://x.com/a"]}).status_code == 422
    assert c.post("/fuentes/n/canales", json={"plataforma": "simulado", "entrada": "sim://tres", "rol": "propio"}).status_code == 200
    assert c.patch("/fuentes/n/canales", json={"url": "sim://tres", "activo": False}).json()["activo"] is False
    d = c.get("/fuentes/n").json()
    assert d["canales"][0]["plataforma"] == "simulado" and d["palabras_clave"] == ["fritz sport"]
    assert c.put("/fuentes/n/palabras", json={"palabras": ["a b c d"]}).json() == {"palabras": ["a b c d"]}
    assert c.delete("/fuentes/n/canales", params={"url": "sim://tres"}).status_code == 200
