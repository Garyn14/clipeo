"""
test_juez.py — Tests de agentes/juez.py: decide sobre los rangos del A2, guarda el rango en
cada decisión (lo consume el A3 en modo copy), recibe las correcciones del editor, falla de
forma reintentable ante respuestas incompletas y se omite si el nicho no tiene memoria.

Sin Claude: get_client() se reemplaza por un cliente falso que devuelve una respuesta fija
y guarda lo que recibió.
"""

import json
from types import SimpleNamespace

import pytest

import agentes.juez as juez
from ai_client import AIRetryableError
from investigacion import comun

TRANSCRIPCION = (
    "[12:04] Tío Fritz: ¿Quieren una pelota gratis o no?\n"
    "[12:10] SPEAKER_01 [sin identificar]: ¡Sí!\n"
    "[20:00] Tío Fritz: Tenemos zapatillas a 99 soles, aprovechen.\n"
)


class ClienteFalso:
    def __init__(self, respuesta: str):
        self.respuesta = respuesta
        self.recibido: dict = {}
        self.llamadas = 0
        self.messages = self

    def create(self, **kwargs):
        self.recibido = kwargs
        self.llamadas += 1
        return SimpleNamespace(content=[SimpleNamespace(text=self.respuesta)])


def rangos():
    return [
        {"conservar": True, "inicio": "00:12:00", "fin": "00:12:30", "duracion_segundos": 30,
         "gancho": "¿Quieren una pelota gratis?",
         "pico_original": {"tipo": "generosidad_con_humilde", "en_juego": "niños sin pelota"}},
        {"conservar": False, "razon": "duplicado"},
        {"conservar": True, "inicio": "00:19:50", "fin": "00:20:30", "duracion_segundos": 40},
    ]


def veredicto():
    return {"candidatos": [
        {"n": 1, "tipo": "generosidad_con_humilde", "en_juego": "niños humildes reciben una pelota",
         "parecidos": ["El tío Fritz hace descuento a mamita que no tenía cómo pagar"], "publicar": True,
         "fuerza": 8, "linea1": "El tío Fritz regala una pelota", "linea2": "a dos hermanitos 🥹",
         "por_que": "gesto con niños"},
        {"n": 2, "tipo": "ninguno", "en_juego": "nada", "parecidos": [], "publicar": False,
         "fuerza": 2, "linea1": "El tío Fritz vende a 99", "linea2": "", "por_que": "pitch de producto"},
    ]}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    memoria = tmp_path / "investigacion" / "zapatillas_peru" / "referencias.yaml"
    memoria.parent.mkdir(parents=True)
    memoria.write_text("tipos_que_funcionan:\n  - tipo: generosidad_con_humilde\n", encoding="utf-8")
    session_dir = tmp_path / "sesion"
    chunk_dir = session_dir / "chunks" / "chunk_001"
    chunk_dir.mkdir(parents=True)
    (session_dir / "metadata.json").write_text(
        json.dumps({"title": "BOTO A MIS CAJEROS", "uploader": "FRITZ SPORT"}), encoding="utf-8")
    (chunk_dir / "speaker_map.json").write_text(json.dumps({
        "SPEAKER_00": {"nombre": "Tío Fritz", "confianza": 0.6, "estado": "confirmado_por_canal"},
        "SPEAKER_01": {"nombre": None, "confianza": 0.0, "estado": "desconocido"},
    }), encoding="utf-8")
    return SimpleNamespace(session_dir=session_dir, chunk_dir=chunk_dir,
                           config={"meta": {"id": "zapatillas_peru"}})


def correr(entorno, monkeypatch, respuesta: str):
    cliente = ClienteFalso(respuesta)
    monkeypatch.setattr(juez, "get_client", lambda: cliente)
    resultado = juez.run_juez(rangos(), transcripcion=TRANSCRIPCION, config=entorno.config,
                              session_dir=entorno.session_dir, chunk_dir=entorno.chunk_dir)
    return resultado, cliente


def test_decide_sobre_los_rangos_conservados(entorno, monkeypatch):
    resultado, _ = correr(entorno, monkeypatch, json.dumps(veredicto()))

    assert resultado["nota"] == "1/2 para publicar"
    decisiones = json.loads((entorno.chunk_dir / "juez.json").read_text(encoding="utf-8"))["decisiones"]
    assert [d["publicar"] for d in decisiones] == [True, False]
    pelota = decisiones[0]
    assert pelota["linea1"] == "El tío Fritz regala una pelota"
    assert pelota["fuerza"] == 8 and pelota["tipo"] == "generosidad_con_humilde"
    # El rango completo viaja en la decisión: lo consume el A3 en modo copy
    assert pelota["rango"]["gancho"] == "¿Quieren una pelota gratis?"
    assert decisiones[1]["rango"]["inicio"] == "00:19:50"


def test_el_prompt_lleva_memoria_video_hablantes_y_pista_del_a1(entorno, monkeypatch):
    _, cliente = correr(entorno, monkeypatch, json.dumps(veredicto()))

    assert "generosidad_con_humilde" in cliente.recibido["system"]  # la memoria va en el system
    usuario = cliente.recibido["messages"][0]["content"]
    assert "BOTO A MIS CAJEROS" in usuario and "FRITZ SPORT" in usuario
    assert "SPEAKER_00: Tío Fritz (confirmado_por_canal" in usuario
    assert "tipo sugerido: generosidad_con_humilde" in usuario and "en juego: niños sin pelota" in usuario
    assert "=== CANDIDATO 1" in usuario and "pelota gratis" in usuario
    assert "=== CANDIDATO 2" in usuario and "99 soles" in usuario
    assert "=== CANDIDATO 3" not in usuario  # el rango no conservado no se juzga


def test_las_correcciones_del_editor_entran_al_prompt(entorno, monkeypatch):
    comun.registrar_correccion("zapatillas_peru", {
        "accion": "descartado", "razon": "es un pitch disfrazado",
        "juez": {"tipo": "rivalidad_y_apuestas", "fuerza": 6, "linea1": "El tío Fritz reta", "linea2": "a Yolu"},
    })
    _, cliente = correr(entorno, monkeypatch, json.dumps(veredicto()))

    assert "CORRECCIONES DEL EDITOR" in cliente.recibido["system"]
    assert "DESCARTÓ «El tío Fritz reta / a Yolu»" in cliente.recibido["system"]
    assert "es un pitch disfrazado" in cliente.recibido["system"]


def test_sin_correcciones_no_hay_bloque(entorno, monkeypatch):
    _, cliente = correr(entorno, monkeypatch, json.dumps(veredicto()))
    assert "CORRECCIONES DEL EDITOR" not in cliente.recibido["system"]


def test_respuesta_sin_json_es_reintentable(entorno, monkeypatch):
    with pytest.raises(AIRetryableError, match="sin JSON"):
        correr(entorno, monkeypatch, "no sé, ambos están bien")
    assert not (entorno.chunk_dir / "juez.json").exists()


def test_veredicto_faltante_es_reintentable(entorno, monkeypatch):
    incompleto = veredicto()
    incompleto["candidatos"] = incompleto["candidatos"][:1]
    with pytest.raises(AIRetryableError, match=r"\[2\]"):
        correr(entorno, monkeypatch, json.dumps(incompleto))


def test_sin_memoria_se_omite_sin_llamar_a_claude(entorno, monkeypatch):
    entorno.config["meta"]["id"] = "nicho_sin_memoria"
    monkeypatch.setattr(juez, "get_client", lambda: pytest.fail("no debería llamar a Claude"))

    resultado = juez.run_juez(rangos(), transcripcion=TRANSCRIPCION, config=entorno.config,
                              session_dir=entorno.session_dir, chunk_dir=entorno.chunk_dir)

    assert resultado["omitido"] is True
    assert "sin memoria" in resultado["nota"]
