"""
test_exclusion.py — CLIP-36 (R-01): lista de exclusión y retiro.

Un canal o persona excluidos no se procesan (descarga), no se encolan (aprobación), se cancelan antes del envío
(motor) y el retiro lista y cancela todo lo suyo. Sin red ni Claude.
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ["PUBLICACION_MOTOR"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.publicacion import cola, db  # noqa: E402
from core import exclusion  # noqa: E402
from core.pasos import ErrorPaso  # noqa: E402

SESION = "20261118_100000"
FUENTE = {"tipo": "medios", "sobre": "Tío Fritz", "canal_origen": "Panorama", "url": "https://youtu.be/x"}


@pytest.fixture(autouse=True)
def lista(tmp_path, monkeypatch):
    ruta = tmp_path / "exclusion.yaml"
    ruta.write_text("# cabecera que se conserva\ncanales: []\npersonas: []\n", encoding="utf-8")
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(ruta))
    return ruta


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "pub.db")
    c = db.conectar()
    yield c
    c.close()


@pytest.fixture
def stream_data(tmp_path):
    """Una sesión de medios con dos clips cortados (uno ya publicado) y uno de stream de otro canal."""
    sd = tmp_path / "stream_data"
    medios = sd / SESION
    (medios / "clips").mkdir(parents=True)
    (medios / "pipeline_estado.json").write_text(json.dumps({"config": "zapatillas_peru", "fuente": FUENTE,
                                                             "video": {"canal": "Panorama"}}), encoding="utf-8")
    items = [
        {"clip_id": "clip_c001_01", "texto_linea1": "Fritz jura", "texto_linea2": "que es original",
         "fuente": FUENTE, "publicado": {"tiktok": {"url": "https://tiktok.com/@x/video/1", "video_id": "1"}}},
        {"clip_id": "clip_c001_02", "texto_linea1": "Fritz confiesa", "fuente": FUENTE},
        {"texto_linea1": "rechazado sin cortar", "fuente": FUENTE},
    ]
    (medios / "contenido_final.json").write_text(json.dumps({"contenido": items}), encoding="utf-8")
    for it in items[:2]:
        (medios / "clips" / f"{it['clip_id']}.mp4").write_bytes(b"\x00")
        (medios / "clips" / f"{it['clip_id']}.json").write_text(json.dumps({"fuente": FUENTE}), encoding="utf-8")
    stream = sd / "20261118_120000"
    stream.mkdir()
    (stream / "pipeline_estado.json").write_text(json.dumps({"video": {"canal": "FRITZ SPORT"}}), encoding="utf-8")
    (stream / "contenido_final.json").write_text(json.dumps({"contenido": [{"clip_id": "clip_c001_01"}]}),
                                                 encoding="utf-8")
    return sd


# ── core/exclusion.py ───────────────────────────────────────

def test_motivo_ignora_mayusculas_tildes_y_espacios(lista):
    assert exclusion.motivo(canal="Panorama") is None
    exclusion.agregar(canal="Panorama", persona="Tío Fritz")
    assert "lista de exclusión" in exclusion.motivo(canal="  PANORAMA ")
    assert exclusion.motivo(persona="tio  fritz")
    assert exclusion.motivo(canal="Willax") is None
    assert exclusion.motivo_fuente(FUENTE) and exclusion.motivo_fuente(None) is None


def test_agregar_es_idempotente_y_conserva_la_cabecera(lista):
    assert exclusion.agregar(canal="Panorama") is True
    assert exclusion.agregar(canal="panorama") is False
    texto = lista.read_text(encoding="utf-8")
    assert texto.startswith("# cabecera que se conserva") and exclusion.cargar()["canales"] == ["Panorama"]


def test_sin_archivo_no_excluye(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "no_existe.yaml"))
    assert exclusion.cargar() == {"canales": [], "personas": []}
    assert exclusion.motivo(canal="Panorama") is None


# ── Descarga ────────────────────────────────────────────────

def test_canal_excluido_no_se_procesa(tmp_path, monkeypatch):
    import pipeline
    exclusion.agregar(canal="Panorama")
    capturado = {}

    def ejecutar(mgr, chunk_id, nombre, fn, **k):
        if nombre == "descarga":
            capturado["fn"] = fn

    monkeypatch.setattr(pipeline, "ejecutar_paso", ejecutar)
    monkeypatch.setattr(pipeline, "_procesar_pendientes", lambda *a, **k: None)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    def descarga_falsa(url, session_dir, subpasos=None, on_metadata=None):
        on_metadata({"titulo": "Entrevista", "canal": "Panorama"})
        raise AssertionError("no debía llegar a bajar el video")

    import captura.video_capture as vc
    monkeypatch.setattr(vc, "download_video", descarga_falsa)
    monkeypatch.setattr(pipeline, "STREAM_DATA", tmp_path)
    cfg = type("Cfg", (), {"get": lambda self, *a, default=None: "zapatillas_peru"})()
    pipeline._run_video_chunks(cfg, {}, "https://youtu.be/x", manual=True, session_id="s1")

    with pytest.raises(ErrorPaso) as e:
        capturado["fn"]()
    assert "lista de exclusión" in str(e.value) and e.value.reintentable is False


# ── Aprobación y motor ──────────────────────────────────────

def test_clip_excluido_no_se_encola(tmp_path, conn, monkeypatch):
    from app.services import review_actions
    (tmp_path / "pipeline_estado.json").write_text(json.dumps({"config": "zapatillas_peru"}), encoding="utf-8")
    llamadas = []
    monkeypatch.setattr(review_actions, "_encolar_en", lambda *a, **k: llamadas.append(a))

    review_actions._encolar_publicacion(tmp_path, "clip_c001_01", {"fuente": FUENTE})
    assert len(llamadas) == 2                       # TikTok y YouTube
    exclusion.agregar(persona="Tío Fritz")
    review_actions._encolar_publicacion(tmp_path, "clip_c001_02", {"fuente": FUENTE})
    assert len(llamadas) == 2                       # no se encoló


def test_el_motor_cancela_los_excluidos_antes_de_enviar(conn, stream_data):
    clips = stream_data / SESION / "clips"
    a = cola.encolar(conn, SESION, "clip_c001_01", "zapatillas_peru", str(clips / "clip_c001_01.mp4"), "A")
    otro = stream_data / "otro.mp4"
    otro.write_bytes(b"\x00")
    b = cola.encolar(conn, "20261118_120000", "clip_c001_01", "zapatillas_peru", str(otro), "B")

    assert cola.primero_enviable(conn, "zapatillas_peru")["id"] == a["id"]
    exclusion.agregar(canal="Panorama")
    assert cola.primero_enviable(conn, "zapatillas_peru")["id"] == b["id"]
    assert cola.obtener(conn, a["id"])["estado"] == "cancelado"


# ── Retiro ──────────────────────────────────────────────────

def test_retiro_lista_cancela_y_excluye(conn, stream_data):
    from investigacion import retirar
    clips = stream_data / SESION / "clips"
    for clip_id in ("clip_c001_01", "clip_c001_02"):
        cola.encolar(conn, SESION, clip_id, "zapatillas_peru", str(clips / f"{clip_id}.mp4"), "t")

    vista = retirar.retirar("Panorama", None, aplicar=False, stream_data=stream_data, conn=conn)
    assert [c["clip_id"] for c in vista["clips"]] == ["clip_c001_01", "clip_c001_02"]   # el stream no
    assert vista["cancelados"] == 0 and exclusion.motivo(canal="Panorama") is None

    r = retirar.retirar("Panorama", None, aplicar=True, stream_data=stream_data, conn=conn)
    assert r["cancelados"] == 2
    assert all(p["estado"] == "cancelado" for c in r["clips"] for p in c["colas"])
    assert [c["clip_id"] for c in r["a_mano"]] == ["clip_c001_01"]                       # ya publicado
    assert exclusion.motivo(canal="Panorama")


def test_retiro_por_persona(conn, stream_data):
    from investigacion import retirar
    r = retirar.retirar(None, "tio fritz", aplicar=False, stream_data=stream_data, conn=conn)
    assert len(r["clips"]) == 2
