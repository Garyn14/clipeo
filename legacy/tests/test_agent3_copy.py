"""
test_agent3_copy.py — A3 en modo copy: escribe el copy solo de lo que aprobó el juez,
respetando su título y su fuerza; los rechazados quedan registrados sin llamar a Claude.
"""

import json
from types import SimpleNamespace

import pytest

import agentes.agent3_viral_scorer as a3

CONFIG = {
    "meta": {"id": "nicho_test_copy"},
    "contenido": {"prompt": "PROMPT DEL NICHO", "hashtags_base": ["#base"], "score_minimo_publicar": 7},
    "seo_base": {"tiktok": {"hashtags": ["#fyp"]}, "youtube_shorts": {"hashtags": ["#Shorts"]}},
    "contenido_restricciones": {"palabras_prohibidas": ["robo"]},
}


class ClienteCopy:
    def __init__(self):
        self.recibidos: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.recibidos.append(kwargs)
        respuesta = {
            "score": 3, "publicar": False,  # el copy no decide: se ignora
            "texto_linea1": "OTRO TÍTULO", "texto_linea2": "que no debe quedar",
            "hashtags": ["#fritz"], "mood": "comedia", "estilo_texto": "dinamico_con_titulo",
            "publicacion": {"tiktok": {"descripcion": "El tío Fritz regala una pelota 🥹", "hashtags": ["#parati"]},
                            "youtube_shorts": {"titulo_alt": "Fritz regala pelota", "hashtags": ["#Peru"]}},
        }
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(respuesta))])


def decision(n, publicar, inicio, l1, l2="", fuerza=8):
    return {"n": n, "inicio": inicio, "fin": inicio, "publicar": publicar, "linea1": l1, "linea2": l2,
            "tipo": "generosidad_con_humilde" if publicar else "ninguno", "en_juego": "x",
            "parecidos": [], "fuerza": fuerza, "por_que": "porque",
            "rango": {"conservar": True, "inicio": inicio, "fin": inicio, "duracion_segundos": 30}}


@pytest.fixture
def chunk(tmp_path):
    (tmp_path / "transcripcion_completa.txt").write_text(
        "[12:04] Tío Fritz: ¿Quieren una pelota gratis?\n[20:00] Tío Fritz: zapatillas a 99\n", encoding="utf-8")
    juez_p = tmp_path / "juez.json"
    juez_p.write_text(json.dumps({"decisiones": [
        decision(1, False, "00:20:00", "El tío Fritz vende a 99", fuerza=2),
        decision(2, True, "00:12:04", "El tío Fritz regala una pelota", "a dos hermanitos 🥹"),
    ]}), encoding="utf-8")
    return tmp_path


def test_copy_respeta_titulo_y_fuerza_del_juez(chunk, monkeypatch):
    cliente = ClienteCopy()
    monkeypatch.setattr(a3, "get_client", lambda: cliente)

    contenido, advertencias = a3.run_copy(str(chunk / "juez.json"), CONFIG)

    assert len(cliente.recibidos) == 1  # el rechazado no llama a Claude
    pelota, pitch = contenido           # ordenados por inicio
    assert pelota["texto_linea1"] == "El tío Fritz regala una pelota"
    assert pelota["texto_linea2"] == "a dos hermanitos 🥹"
    assert pelota["score"] == 8 and pelota["publicar"] is True
    assert pelota["mood"] == "comedia"
    assert pelota["publicacion"]["tiktok"]["descripcion"].startswith("El tío Fritz regala")
    assert pelota["publicacion"]["tiktok"]["hashtags"] == ["#fyp", "#parati"]       # merge con SEO base
    assert pelota["publicacion"]["youtube_shorts"]["hashtags"] == ["#Shorts", "#Peru"]
    assert pelota["hashtags"][0] == "#base"
    assert pelota["juez"]["tipo"] == "generosidad_con_humilde"
    assert pelota["rango_original"]["inicio"] == "00:12:04"

    assert pitch["publicar"] is False and pitch["score"] == 2
    assert pitch["juez"]["tipo"] == "ninguno"
    assert advertencias == []
    assert json.loads((chunk / "contenido.json").read_text(encoding="utf-8"))["contenido"][0]["score"] == 8


def test_la_nota_al_copy_lleva_el_titulo(chunk, monkeypatch):
    cliente = ClienteCopy()
    monkeypatch.setattr(a3, "get_client", lambda: cliente)

    a3.run_copy(str(chunk / "juez.json"), CONFIG)

    bloque_clip = cliente.recibidos[0]["messages"][0]["content"][1]["text"]
    assert "TÍTULO DECIDIDO POR EL JUEZ" in bloque_clip
    assert "El tío Fritz regala una pelota" in bloque_clip and "pelota gratis" in bloque_clip


def test_palabra_prohibida_en_el_titulo_queda_como_advertencia(chunk, monkeypatch):
    datos = json.loads((chunk / "juez.json").read_text(encoding="utf-8"))
    datos["decisiones"][1]["linea1"] = "El robo del tío Fritz"
    (chunk / "juez.json").write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(a3, "get_client", lambda: ClienteCopy())

    contenido, advertencias = a3.run_copy(str(chunk / "juez.json"), CONFIG)

    assert len(advertencias) == 1 and "robo" in advertencias[0]
    assert contenido[0]["texto_linea1"] == "El robo del tío Fritz"  # no se descarta en silencio


def test_todo_rechazado_no_llama_a_claude(chunk, monkeypatch):
    datos = json.loads((chunk / "juez.json").read_text(encoding="utf-8"))
    datos["decisiones"][1]["publicar"] = False
    (chunk / "juez.json").write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(a3, "get_client", lambda: pytest.fail("no debería llamar a Claude"))

    contenido, _ = a3.run_copy(str(chunk / "juez.json"), CONFIG)

    assert not any(c["publicar"] for c in contenido)


def _juez_con_plan(tmp_path, plan):
    (tmp_path / "transcripcion_completa.txt").write_text(
        "[12:00] a ver a ver\n[12:04] Tío Fritz: ¿Quieren una pelota gratis?\n[12:30] ¡Gracias tío!\n",
        encoding="utf-8")
    d = decision(1, True, "00:12:00", "El tío Fritz regala una pelota")
    d["rango"].update(fin="00:12:40", plan_edicion=plan)
    (tmp_path / "juez.json").write_text(json.dumps({"decisiones": [d]}), encoding="utf-8")
    return tmp_path / "juez.json"


def test_copy_con_plan_de_un_tramo_mueve_los_bordes(tmp_path, monkeypatch):
    """CLIP-31: un tramo → corte normal con los bordes de la dirección, y el copy habla de ese tramo."""
    cliente = ClienteCopy()
    monkeypatch.setattr(a3, "get_client", lambda: cliente)
    plan = {"estructura": "lineal", "segmentos": [{"inicio": "00:12:04", "fin": "00:12:35"}]}
    (clip,), _ = a3.run_copy(str(_juez_con_plan(tmp_path, plan)), CONFIG)
    assert "segmentos" not in clip
    assert (clip["rango_original"]["inicio"], clip["rango_original"]["fin"]) == ("00:12:04", "00:12:35")
    assert "a ver a ver" not in json.dumps(cliente.recibidos[0]["messages"], ensure_ascii=False)


def test_copy_con_gancho_primero_pasa_el_montaje_al_corte(tmp_path, monkeypatch):
    """CLIP-31: gancho primero → `segmentos` en orden de montaje (Agente 4 usa `_cut_compilation`)."""
    cliente = ClienteCopy()
    monkeypatch.setattr(a3, "get_client", lambda: cliente)
    segs = [{"inicio": "00:12:30", "fin": "00:12:33"}, {"inicio": "00:12:04", "fin": "00:12:35"}]
    (clip,), _ = a3.run_copy(str(_juez_con_plan(tmp_path, {"estructura": "gancho_primero", "segmentos": segs})), CONFIG)
    assert clip["segmentos"] == segs
    assert "[— corte —]" in json.dumps(cliente.recibidos[0]["messages"], ensure_ascii=False)
