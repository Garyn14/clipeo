"""
test_correcciones_y_auditoria.py — Tus decisiones de revisión vuelven al juez
(investigacion/<nicho>/correcciones.jsonl) y la auditoría de momentos perdidos.
"""

import json
from types import SimpleNamespace

import pytest

import agentes.auditoria as auditoria
from ai_client import AIRetryableError
from investigacion import comun


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    return tmp_path


def _juez(l1, tipo="generosidad_con_humilde", fuerza=7):
    return {"tipo": tipo, "fuerza": fuerza, "linea1": l1, "linea2": "remate"}


def test_registrar_y_resumir_correcciones(raiz):
    comun.registrar_correccion("n", {"accion": "aprobado", "juez": _juez("El tío Fritz regala")})
    comun.registrar_correccion("n", {"accion": "editado", "juez": _juez("Título viejo"),
                                     "titulo_final": "El tío Fritz / nuevo"})
    comun.registrar_correccion("n", {"accion": "descartado", "juez": _juez("Un pitch", "ninguno", 5),
                                     "razon": "es venta"})

    resumen = comun.cargar_correcciones("n").splitlines()
    assert resumen == [
        "- APROBÓ «El tío Fritz regala / remate» (tipo generosidad_con_humilde, fuerza 7)",
        "- CAMBIÓ el título «Título viejo / remate» por «El tío Fritz / nuevo» (tipo generosidad_con_humilde, fuerza 7)",
        "- DESCARTÓ «Un pitch / remate» (tipo ninguno, fuerza 5): es venta",
    ]
    lineas = (raiz / "investigacion" / "n" / "correcciones.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 3


def test_resumen_se_limita_a_las_ultimas_n(raiz):
    for i in range(5):
        comun.registrar_correccion("n", {"accion": "aprobado", "juez": _juez(f"clip {i}")})
    resumen = comun.cargar_correcciones("n", n=2)
    assert "clip 3" in resumen and "clip 4" in resumen and "clip 0" not in resumen


def test_sin_correcciones_resumen_vacio(raiz):
    assert comun.cargar_correcciones("nicho_nuevo") == ""


# ── Auditoría ────────────────────────────────────────────────────────────────

@pytest.fixture
def chunk(raiz):
    m = raiz / "investigacion" / "zap" / "referencias.yaml"
    m.parent.mkdir(parents=True)
    m.write_text("tipos_que_funcionan: [generosidad_con_humilde]", encoding="utf-8")
    d = raiz / "chunk"
    d.mkdir()
    (d / "transcripcion_completa.txt").write_text("[10:07] Tío Fritz: toma, una pelota para ti\n", encoding="utf-8")
    (d / "rangos.json").write_text(json.dumps({"rangos": [
        {"conservar": True, "inicio": "00:12:04", "fin": "00:12:50"}, {"conservar": False}]}), encoding="utf-8")
    return d


def _cliente(texto, recibido):
    def create(**kw):
        recibido.update(kw)
        return SimpleNamespace(content=[SimpleNamespace(text=texto)])
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_auditoria_lista_lo_perdido(chunk, monkeypatch):
    recibido = {}
    respuesta = {"perdidos": [{"timestamp": "00:10:07", "tipo": "generosidad_con_humilde",
                               "en_juego": "un niño sin pelota", "por_que": "nadie lo detectó"}]}
    monkeypatch.setattr(auditoria, "get_client", lambda: _cliente(json.dumps(respuesta), recibido))

    r = auditoria.auditar(chunk, "zap")

    assert r["detectados"] == 1 and r["perdidos"][0]["timestamp"] == "00:10:07"
    assert "00:12:04 → 00:12:50" in recibido["messages"][0]["content"]  # le dice qué ya llegó
    assert "pelota para ti" in recibido["messages"][0]["content"]
    assert json.loads((chunk / "auditoria.json").read_text(encoding="utf-8")) == r


def test_auditoria_respuesta_rota_es_reintentable(chunk, monkeypatch):
    monkeypatch.setattr(auditoria, "get_client", lambda: _cliente("no sé", {}))
    with pytest.raises(AIRetryableError):
        auditoria.auditar(chunk, "zap")
