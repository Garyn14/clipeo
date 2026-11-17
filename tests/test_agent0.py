"""
test_agent0.py — Tests del Agente 0 (identificación de hablantes): vista previa repartida y
regla del dueño del canal (un "posible" que es el dueño del canal se aplica).

Sin Claude: get_client() se reemplaza por un cliente falso con una respuesta fija.
"""

import json
from types import SimpleNamespace

import agentes.agent0_speaker_identifier as a0

CONFIG = {
    "personajes": [
        {"id": "fritz", "nombres": ["Tío Fritz", "Fritz", "Fritz Sport"]},
        {"id": "yolu", "nombres": ["Tío Yolu", "Yolu"]},
    ],
    "identificacion": {"umbral_alto": 0.70, "umbral_bajo": 0.40},
}


def _transcripcion(minutos: int = 20) -> str:
    lineas = []
    for m in range(minutos):
        lineas.append(f"[{m:02d}:00] SPEAKER_00: frase del minuto {m}")
        lineas.append(f"[{m:02d}:30] SPEAKER_01: respuesta del minuto {m}")
    return "\n".join(lineas)


def _correr(tmp_path, monkeypatch, respuesta: dict, uploader: str = "FRITZ SPORT"):
    raw = tmp_path / "transcripcion_raw.txt"
    raw.write_text(_transcripcion(), encoding="utf-8")
    meta = tmp_path / "metadata.json"
    meta.write_text(json.dumps({"title": "video", "uploader": uploader}), encoding="utf-8")
    cliente = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **k: SimpleNamespace(content=[SimpleNamespace(text=json.dumps(respuesta))])))
    monkeypatch.setattr(a0, "get_client", lambda: cliente)
    enriquecida = a0.identify_speakers(raw, meta, tmp_path, CONFIG)
    mapa = json.loads((tmp_path / "speaker_map.json").read_text(encoding="utf-8"))
    return mapa, enriquecida.read_text(encoding="utf-8")


def test_preview_toma_tres_ventanas_repartidas():
    preview = a0._extract_preview(_transcripcion(20))
    assert preview.count("[...]") == 2
    assert "minuto 0" in preview          # inicio
    assert "minuto 9" in preview or "minuto 10" in preview  # mitad
    assert "minuto 19" in preview         # final
    assert "minuto 5" not in preview      # no todo


def test_preview_corta_devuelve_todo():
    corta = _transcripcion(2)
    assert a0._extract_preview(corta) == corta


def test_posible_que_es_el_dueno_del_canal_se_aplica(tmp_path, monkeypatch):
    mapa, texto = _correr(tmp_path, monkeypatch, {
        "mapa": {"SPEAKER_00": "Tío Fritz (host)", "SPEAKER_01": "SPEAKER_01"},
        "confianza": {"SPEAKER_00": 0.6, "SPEAKER_01": 0.0},
    })
    assert mapa["SPEAKER_00"]["estado"] == "confirmado_por_canal"
    assert mapa["SPEAKER_00"]["nombre"] == "Tío Fritz (host)"
    assert "Tío Fritz (host): frase" in texto
    assert "SPEAKER_01 [sin identificar]:" in texto


def test_posible_de_otro_personaje_no_se_aplica(tmp_path, monkeypatch):
    # El caso real: Claude dijo "Yolu" en un video del canal FRITZ SPORT
    mapa, texto = _correr(tmp_path, monkeypatch, {
        "mapa": {"SPEAKER_00": "Tío Yolu (host)", "SPEAKER_01": "SPEAKER_01"},
        "confianza": {"SPEAKER_00": 0.6, "SPEAKER_01": 0.0},
    })
    assert mapa["SPEAKER_00"]["estado"] == "posible"  # queda como pista para el juez...
    assert "Tío Yolu" not in texto                     # ...pero no se aplica al texto


def test_confianza_alta_sigue_igual(tmp_path, monkeypatch):
    mapa, _ = _correr(tmp_path, monkeypatch, {
        "mapa": {"SPEAKER_00": "Tío Yolu", "SPEAKER_01": "SPEAKER_01"},
        "confianza": {"SPEAKER_00": 0.9, "SPEAKER_01": 0.0},
    })
    assert mapa["SPEAKER_00"]["estado"] == "confirmado"
