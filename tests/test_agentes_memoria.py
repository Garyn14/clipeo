"""
test_agentes_memoria.py — Con memoria del nicho, A1 busca amplio (bloque de memoria + umbral
bajo) y A2 solo define bordes (sufijo que ignora los criterios de descarte). Sin memoria,
todo igual que antes. También: el mapeo pico_original ↔ rango por segundos.
"""

import json
from types import SimpleNamespace

import pytest

import agentes.agent1_peak_detector as a1
import agentes.agent2_range_refiner as a2
from investigacion import comun

TRANSCRIPCION = "[12:04] Tío Fritz: ¿Quieren una pelota gratis?\n[12:10] Niño: ¡Sí!\n"


class Cliente:
    def __init__(self, respuesta: dict):
        self.respuesta = json.dumps(respuesta)
        self.recibido: dict = {}
        self.messages = self

    def create(self, **kwargs):
        self.recibido = kwargs
        return SimpleNamespace(content=[SimpleNamespace(text=self.respuesta)])


@pytest.fixture
def memoria(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    p = tmp_path / "investigacion" / "con_memoria" / "referencias.yaml"
    p.parent.mkdir(parents=True)
    p.write_text("tipos_que_funcionan:\n  - tipo: generosidad_con_humilde\n", encoding="utf-8")


def _config(canal: str) -> dict:
    return {
        "meta": {"id": canal},
        "deteccion": {"prompt": "PROMPT A1", "confianza_minima": 0.75},
        "refinamiento": {"prompt": "PROMPT A2\nCRITERIOS PARA DESCARTAR: ...", "contexto_antes_segundos": 45,
                         "contexto_despues_segundos": 45, "duracion_minima_segundos": 20,
                         "duracion_maxima_segundos": 90},
    }


PICOS = {"picos": [
    {"timestamp": "00:12:04", "razon": "regala pelota", "confianza": 0.6, "tipo": "generosidad_con_humilde",
     "en_juego": "niños sin pelota"},
    {"timestamp": "00:15:00", "razon": "dudoso", "confianza": 0.4, "tipo": "ninguno"},
]}


def _correr_a1(tmp_path, monkeypatch, canal: str):
    t = tmp_path / "chunk" / "transcripcion_completa.txt"
    t.parent.mkdir(exist_ok=True)
    t.write_text(TRANSCRIPCION, encoding="utf-8")
    cliente = Cliente(PICOS)
    monkeypatch.setattr(a1, "get_client", lambda: cliente)
    picos = a1.run_agent(str(t), _config(canal))
    prompt = cliente.recibido["messages"][0]["content"][0]["text"]
    return picos, prompt


def test_a1_con_memoria_busca_amplio(tmp_path, monkeypatch, memoria):
    picos, prompt = _correr_a1(tmp_path, monkeypatch, "con_memoria")
    assert "MEMORIA DEL NICHO" in prompt and "generosidad_con_humilde" in prompt
    assert [p["timestamp"] for p in picos] == ["00:12:04"]  # 0.6 pasa con umbral 0.5; 0.4 no


def test_a1_sin_memoria_igual_que_antes(tmp_path, monkeypatch, memoria):
    picos, prompt = _correr_a1(tmp_path, monkeypatch, "sin_memoria")
    assert prompt == "PROMPT A1"
    assert picos == []  # 0.6 y 0.4 no pasan el 0.75


def _correr_a2(tmp_path, monkeypatch, canal: str, rango_pico_ts: str):
    d = tmp_path / "chunk2"
    d.mkdir(exist_ok=True)
    (d / "transcripcion_completa.txt").write_text(TRANSCRIPCION, encoding="utf-8")
    (d / "picos.json").write_text(json.dumps(PICOS), encoding="utf-8")
    cliente = Cliente({"rangos": [{"pico_timestamp": rango_pico_ts, "conservar": True, "inicio": "00:12:02",
                                   "fin": "00:12:40", "duracion_segundos": 38, "razon": "bordes", "gancho": "x"}]})
    monkeypatch.setattr(a2, "get_client", lambda: cliente)
    rangos = a2.run_agent(str(d / "picos.json"), _config(canal))
    return rangos, cliente.recibido["system"][0]["text"], cliente.recibido["messages"][0]["content"]


def test_a2_con_memoria_solo_bordes(tmp_path, monkeypatch, memoria):
    _, system, usuario = _correr_a2(tmp_path, monkeypatch, "con_memoria", "00:12:04")
    assert "MODO BORDES" in system and "IGNORA" in system
    assert "En juego  : niños sin pelota" in usuario


def test_a2_sin_memoria_sin_sufijo(tmp_path, monkeypatch, memoria):
    _, system, _ = _correr_a2(tmp_path, monkeypatch, "sin_memoria", "00:12:04")
    assert "MODO BORDES" not in system


@pytest.mark.parametrize("ts", ["12:04", "00:12:04", "00:12:05"])
def test_pico_original_se_mapea_por_segundos(tmp_path, monkeypatch, memoria, ts):
    rangos, _, _ = _correr_a2(tmp_path, monkeypatch, "con_memoria", ts)
    assert rangos[0]["pico_original"]["razon"] == "regala pelota"
    assert rangos[0]["momento_enfasis_seg"] >= 0


def test_pico_original_lejano_no_se_mapea():
    assert a2._pico_de("00:13:00", PICOS["picos"]) == {}
    assert a2._pico_de(None, PICOS["picos"]) == {}
