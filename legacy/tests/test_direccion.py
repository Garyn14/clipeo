"""CLIP-31 — dirección editorial: validación del plan, texto del montaje y paso por juez / Agente 3."""

import json

import pytest

from agentes import direccion
from core.utils import _parse_segments

RANGO = {"conservar": True, "inicio": "10:00", "fin": "10:40"}


def test_plan_valido_lineal_con_recorte():
    plan = {"estructura": "lineal", "segmentos": [{"inicio": "10:05", "fin": "10:20"}, {"inicio": "10:25", "fin": "10:40"}]}
    segs, motivo = direccion.validar_plan(plan, RANGO, 15, 90)
    assert motivo == "ok" and [s["inicio"] for s in segs] == ["00:10:05", "00:10:25"]


def test_plan_gancho_primero_pone_el_remate_adelante():
    plan = {"estructura": "gancho_primero", "segmentos": [{"inicio": "10:00", "fin": "10:40"}],
            "gancho": {"inicio": "10:35", "fin": "10:38"}}
    segs, _ = direccion.validar_plan(plan, RANGO, 15, 90)
    assert segs[0] == {"inicio": "00:10:35", "fin": "00:10:38"} and len(segs) == 2


@pytest.mark.parametrize("plan, motivo", [
    ({"segmentos": [{"inicio": "08:00", "fin": "08:30"}]}, "fuera del rango"),
    ({"segmentos": [{"inicio": "10:00", "fin": "10:01"}, {"inicio": "10:05", "fin": "10:30"}]}, "< 2s"),
    ({"segmentos": [{"inicio": "10:10", "fin": "10:30"}, {"inicio": "10:20", "fin": "10:40"}]}, "solapados"),
    ({"segmentos": [{"inicio": "10:00", "fin": "10:05"}]}, "duración total"),
    ({"segmentos": []}, "sin segmentos"),
    ({"segmentos": [{"inicio": "xx", "fin": "10:05"}]}, "ilegibles"),
])
def test_planes_invalidos_se_descartan(plan, motivo):
    segs, m = direccion.validar_plan(plan, RANGO, 15, 90)
    assert segs is None and motivo in m


def test_texto_del_plan_en_orden_de_montaje():
    trans = _parse_segments("[10:00] hola\n[10:10] a ver a ver\n[10:30] ¿cuánto tienes?\n[10:36] ¡ochenta!")
    texto = direccion.texto_del_plan(trans, [{"inicio": "10:36", "fin": "10:37"}, {"inicio": "10:30", "fin": "10:40"}])
    assert texto.splitlines()[0] == "[10:36] ¡ochenta!"
    assert "[— corte —]" in texto and "a ver" not in texto


class _Cliente:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.messages = self

    def create(self, **kw):
        self.kw = kw
        return type("R", (), {"content": [type("B", (), {"text": json.dumps(self.respuesta)})()]})()


def _config():
    return {"meta": {"id": "zapatillas_peru"},
            "refinamiento": {"duracion_minima_segundos": 15, "duracion_maxima_segundos": 90}}


def test_run_direccion_agrega_plan_valido_y_descarta_invalido(monkeypatch):
    cliente = _Cliente({"candidatos": [
        {"n": 1, "estructura": "lineal", "segmentos": [{"inicio": "10:05", "fin": "10:40"}], "por_que": "arranca en la cifra"},
        {"n": 2, "estructura": "lineal", "segmentos": [{"inicio": "01:00", "fin": "01:02"}]},
    ]})
    monkeypatch.setattr(direccion, "get_client", lambda: cliente)
    rangos = [dict(RANGO), {"conservar": True, "inicio": "20:00", "fin": "20:40"}, {"conservar": False, "inicio": "30:00", "fin": "30:10"}]
    out = direccion.run_direccion(rangos, transcripcion="[10:05] ¿cuánto tienes?\n[20:00] hola", config=_config())
    assert out[0]["plan_edicion"]["segmentos"] == [{"inicio": "00:10:05", "fin": "00:10:40"}]
    assert "plan_edicion" not in out[1] and "plan_edicion" not in out[2]
    assert "CANDIDATO 2" in cliente.kw["messages"][0]["content"] and "CANDIDATO 3" not in cliente.kw["messages"][0]["content"]


def test_activada_por_variable(monkeypatch):
    monkeypatch.delenv("DIRECCION_EDITORIAL", raising=False)
    assert not direccion.activada()
    monkeypatch.setenv("DIRECCION_EDITORIAL", "1")
    assert direccion.activada()


def test_juez_usa_el_texto_del_clip_dirigido(monkeypatch, tmp_path):
    from agentes import juez
    cliente = _Cliente({"candidatos": [{"n": 1, "tipo": "x", "publicar": True, "fuerza": 7, "linea1": "a", "linea2": "b"}]})
    monkeypatch.setattr(juez, "get_client", lambda: cliente)
    rango = dict(RANGO, plan_edicion={"estructura": "gancho_primero",
                                      "segmentos": [{"inicio": "10:36", "fin": "10:38"}, {"inicio": "10:30", "fin": "10:40"}]})
    juez.run_juez([rango], transcripcion="[10:00] relleno\n[10:30] ¿cuánto tienes?\n[10:36] ¡ochenta!",
                  config={"meta": {"id": "zapatillas_peru"}}, session_dir=tmp_path, chunk_dir=tmp_path)
    mensaje = cliente.kw["messages"][0]["content"]
    assert "clip dirigido: gancho_primero" in mensaje and "relleno" not in mensaje
    decision = json.loads((tmp_path / "juez.json").read_text(encoding="utf-8"))["decisiones"][0]
    assert decision["rango"]["plan_edicion"]["estructura"] == "gancho_primero"
