"""
test_fuente_medios.py — CLIP-27: la fuente "medios" (TV/prensa) de una sesión.

Se guarda en pipeline_estado.json, el juez la recibe como contexto (sobre quién trata, el canal no es el
personaje), el copy da crédito al canal y cada clip la lleva hasta la revisión web. Sin Claude.
"""

import json
import sys

import pytest

import agentes.agent3_viral_scorer as a3
import agentes.juez as juez
from core import fuente
from tests.test_agent3_copy import CONFIG, ClienteCopy, decision
from tests.test_juez import ClienteFalso, TRANSCRIPCION, entorno, rangos, veredicto  # noqa: F401 (fixture)

MEDIOS = {"tipo": "medios", "sobre": "Tío Fritz", "url": "https://youtu.be/x", "canal_origen": "Panorama"}


def _estado(dir_, fuente_=None):
    estado = {"config": "zapatillas_peru"}
    if fuente_:
        estado["fuente"] = fuente_
    (dir_ / "pipeline_estado.json").write_text(json.dumps(estado), encoding="utf-8")


# ── core/fuente.py ──────────────────────────────────────────

def test_sobre_resuelve_la_entidad_o_queda_como_nombre_libre():
    assert fuente.nombre_sobre("fritz") == "Tío Fritz"       # contexto/entidades/fritz.yaml
    assert fuente.nombre_sobre("Fritz") == "Tío Fritz"
    assert fuente.nombre_sobre("Magaly Medina") == "Magaly Medina"


def test_leer_desde_la_sesion_o_desde_un_chunk(tmp_path):
    chunk_dir = tmp_path / "chunks" / "chunk_001"
    chunk_dir.mkdir(parents=True)
    assert fuente.leer(chunk_dir) is None                     # sin estado
    _estado(tmp_path)
    assert fuente.leer(chunk_dir) is None                     # stream: sin fuente
    _estado(tmp_path, MEDIOS)
    assert fuente.leer(tmp_path) == MEDIOS
    assert fuente.leer(chunk_dir) == MEDIOS


def test_canal_origen_sale_de_la_metadata_si_falta(tmp_path):
    _estado(tmp_path, {"tipo": "medios", "sobre": "Tío Fritz"})
    (tmp_path / "metadata.json").write_text(json.dumps({"uploader": "Willax"}), encoding="utf-8")
    assert fuente.leer(tmp_path)["canal_origen"] == "Willax"


def test_bloque_y_credito_solo_en_medios():
    assert fuente.bloque_juez(None) == "" and fuente.credito(None) == ""
    assert fuente.bloque_juez({"tipo": "stream"}) == ""
    bloque = fuente.bloque_juez(MEDIOS)
    assert "FUENTE: medios" in bloque and "Panorama" in bloque
    assert "nombra a Tío Fritz" in bloque and "NO es el personaje" in bloque
    assert fuente.credito(MEDIOS) == "Fuente: Panorama"


# ── Juez ────────────────────────────────────────────────────

def _juzgar(entorno, monkeypatch, **kwargs):
    cliente = ClienteFalso(json.dumps(veredicto()))
    monkeypatch.setattr(juez, "get_client", lambda: cliente)
    juez.run_juez(rangos(), transcripcion=TRANSCRIPCION, config=entorno.config,
                  session_dir=entorno.session_dir, chunk_dir=entorno.chunk_dir, **kwargs)
    return cliente.recibido["messages"][0]["content"]


def test_juez_de_un_stream_no_cambia(entorno, monkeypatch):
    assert "FUENTE:" not in _juzgar(entorno, monkeypatch)


def test_juez_lee_la_fuente_de_la_sesion(entorno, monkeypatch):
    _estado(entorno.session_dir, MEDIOS)
    usuario = _juzgar(entorno, monkeypatch)
    assert "FUENTE: medios (TV/prensa), canal «Panorama»" in usuario
    assert "SOBRE: Tío Fritz" in usuario


def test_juez_acepta_la_fuente_explicita(entorno, monkeypatch):
    usuario = _juzgar(entorno, monkeypatch, fuente_sesion={**MEDIOS, "canal_origen": "Magaly TV"})
    assert "canal «Magaly TV»" in usuario


# ── Copy (A3) ───────────────────────────────────────────────

@pytest.fixture
def chunk_medios(tmp_path):
    session_dir = tmp_path / "sesion"
    chunk_dir = session_dir / "chunks" / "chunk_001"
    chunk_dir.mkdir(parents=True)
    _estado(session_dir, MEDIOS)
    (chunk_dir / "transcripcion_completa.txt").write_text("[12:04] Fritz: son originales\n", encoding="utf-8")
    (chunk_dir / "juez.json").write_text(json.dumps({"decisiones": [
        decision(1, True, "00:12:04", "Fritz jura que Gucci", "es 100% original"),
        decision(2, False, "00:20:00", "nada", fuerza=2),
    ]}), encoding="utf-8")
    return chunk_dir


def test_copy_lleva_la_fuente_y_el_credito(chunk_medios, monkeypatch):
    monkeypatch.setattr(a3, "get_client", lambda: ClienteCopy())
    contenido, _ = a3.run_copy(str(chunk_medios / "juez.json"), CONFIG)

    gucci, rechazado = contenido
    assert gucci["fuente"] == MEDIOS and rechazado["fuente"] == MEDIOS
    tiktok = gucci["publicacion"]["tiktok"]["descripcion"]
    assert tiktok.startswith("El tío Fritz regala") and tiktok.endswith("\n\nFuente: Panorama")
    assert gucci["publicacion"]["youtube_shorts"]["descripcion"] == "Fuente: Panorama"


def test_copy_de_un_stream_sin_fuente(tmp_path, monkeypatch):
    chunk_dir = tmp_path / "s" / "chunks" / "chunk_001"
    chunk_dir.mkdir(parents=True)
    (chunk_dir / "transcripcion_completa.txt").write_text("[12:04] Fritz: hola\n", encoding="utf-8")
    (chunk_dir / "juez.json").write_text(json.dumps({"decisiones": [decision(1, True, "00:12:04", "x")]}),
                                         encoding="utf-8")
    monkeypatch.setattr(a3, "get_client", lambda: ClienteCopy())
    contenido, _ = a3.run_copy(str(chunk_dir / "juez.json"), CONFIG)
    assert "fuente" not in contenido[0]
    assert "Fuente:" not in contenido[0]["publicacion"]["tiktok"]["descripcion"]


# ── pipeline.py: argumentos y persistencia ──────────────────

def _main(monkeypatch, *argv):
    import pipeline
    llamadas = []
    monkeypatch.setattr(pipeline, "_load_config", lambda canal: ({}, None))
    monkeypatch.setattr(pipeline, "run_pipeline", lambda *a, **k: llamadas.append(k))
    monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
    pipeline.main()
    return llamadas


def test_medios_requiere_sobre_y_video(monkeypatch):
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--video", "https://youtu.be/x", "--medios")
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--test", "dir", "--medios", "--sobre", "fritz")
    with pytest.raises(SystemExit):
        _main(monkeypatch, "--video", "https://youtu.be/x", "--sobre", "fritz")


def test_medios_pasa_la_fuente_nueva(monkeypatch):
    (k,) = _main(monkeypatch, "--video", "https://youtu.be/x", "--medios", "--sobre", "fritz")
    assert k["fuente_nueva"] == {"tipo": "medios", "sobre": "Tío Fritz", "url": "https://youtu.be/x"}
    (k,) = _main(monkeypatch, "--video", "https://youtu.be/x")
    assert k["fuente_nueva"] is None


def test_la_sesion_guarda_la_fuente_y_retomar_no_la_cambia(tmp_path, monkeypatch):
    import pipeline
    monkeypatch.setattr(pipeline, "ejecutar_paso", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_procesar_pendientes", lambda *a, **k: None)
    video = tmp_path / "video.mp4"
    video.write_bytes(b"")
    cfg = type("Cfg", (), {"get": lambda self, *a, default=None: "zapatillas_peru"})()

    def correr(fuente_nueva):
        pipeline._run_video_chunks(cfg, {}, str(video), manual=True, session_id=None, fuente_nueva=fuente_nueva)
        return json.loads((tmp_path / "pipeline_estado.json").read_text(encoding="utf-8")).get("fuente")

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert correr(fuente.nueva("medios", "fritz", str(video)))["sobre"] == "Tío Fritz"
    assert correr(None)["sobre"] == "Tío Fritz"                                   # retomar sin --medios
    assert correr(fuente.nueva("medios", "Yolu", str(video)))["sobre"] == "Tío Fritz"  # no se pisa


def test_crear_el_plan_no_borra_la_fuente(tmp_path):
    """Demo S5: crear_plan rehacía el estado y la sesión perdía `fuente` antes del juez."""
    from core.chunk_manager import ChunkManager
    mgr = ChunkManager(tmp_path, chunk_minutos=30)
    mgr.iniciar(url="https://youtu.be/x", config="zapatillas_peru")
    mgr.actualizar_sesion(fuente=MEDIOS, video={"canal": "Panorama"})
    mgr.duracion_total = 130
    mgr.crear_plan(url="https://youtu.be/x", config="zapatillas_peru")
    estado = json.loads((tmp_path / "pipeline_estado.json").read_text(encoding="utf-8"))
    assert estado["fuente"] == MEDIOS and estado["video"] == {"canal": "Panorama"}
    assert fuente.leer(tmp_path / "chunks" / "chunk_001") == MEDIOS
