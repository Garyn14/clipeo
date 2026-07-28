"""
test_agent4_video_cutter.py — Tests unitarios para _sanitize_text()
(edicion_video/agent4_video_cutter.py).
"""

import json

import edicion_video.agent4_video_cutter as avc
from edicion_video.agent4_video_cutter import (
    _sanitize_text,
    _text_display_duration,
    _load_word_timings,
    _build_vf_animated,
    _pick_music_track,
)


def test_sanitize_quita_emoji():
    # Sin emoji a propósito: drawtext no los renderiza a color, y el
    # criterio editorial es texto solo, sin emoji quemado en el video.
    assert _sanitize_text("esto es lo que tiene por dentro 😱") == "esto es lo que tiene por dentro"
    assert _sanitize_text("no puede ser 👀") == "no puede ser"
    assert _sanitize_text("bravazo 🔥") == "bravazo"
    assert _sanitize_text("jajaja 😂") == "jajaja"


def test_sanitize_preserva_espanol():
    assert _sanitize_text("Tío Fritz vendió más caro") == "Tío Fritz vendió más caro"
    assert _sanitize_text("¿no puede ser? ¡increíble!") == "¿no puede ser? ¡increíble!"


def test_sanitize_quita_metacaracteres_ffmpeg():
    assert _sanitize_text('el número 1, dice: "nadie me iguala"') == "el número 1 dice nadie me iguala"
    assert _sanitize_text("no puede ser; ni yo lo creo") == "no puede ser ni yo lo creo"
    assert _sanitize_text("Fritz's tienda") == "Fritz s tienda"


def test_sanitize_colapsa_espacios_dobles():
    assert _sanitize_text("hola,   mundo") == "hola mundo"


def test_duracion_texto_respeta_minimo():
    # "Wow" + "🔥" -> 2 palabras, la fórmula pura daría menos del mínimo
    assert _text_display_duration("Wow", "🔥") == 3.0


def test_duracion_texto_escala_con_largo():
    corta = _text_display_duration("Wow", "que fuerte")
    larga = _text_display_duration(
        "Partieron el calzado del Tio Fritz",
        "y encontraron esto adentro increible de verdad",
    )
    assert larga > corta


def test_duracion_texto_respeta_maximo():
    texto_muy_largo = " ".join(["palabra"] * 40)
    assert _text_display_duration(texto_muy_largo, "") == 7.0


def _escribir_palabras(tmp_path, palabras):
    (tmp_path / "palabras.json").write_text(json.dumps(palabras), encoding="utf-8")


def test_load_word_timings_sin_archivo_retorna_vacio(tmp_path):
    assert _load_word_timings(tmp_path, 0, 10) == []


def test_load_word_timings_filtra_y_ajusta_relativo(tmp_path):
    _escribir_palabras(tmp_path, [
        {"word": "antes",  "start": 5.0,  "end": 5.3},
        {"word": "Esto",   "start": 10.0, "end": 10.3},
        {"word": "es",     "start": 10.5, "end": 10.7},
        {"word": "despues", "start": 25.0, "end": 25.3},
    ])
    out = _load_word_timings(tmp_path, 10.0, 20.0)
    assert [w["word"] for w in out] == ["Esto", "es"]
    assert out[0]["start"] == 0.0
    assert out[1]["start"] == 0.5


def test_load_word_timings_ignora_json_corrupto(tmp_path):
    (tmp_path / "palabras.json").write_text("no es json valido", encoding="utf-8")
    assert _load_word_timings(tmp_path, 0, 10) == []


def test_build_vf_animated_retorna_none_sin_palabras():
    assert _build_vf_animated([], "") is None


def test_build_vf_animated_una_palabra_por_drawtext():
    words = [
        {"word": "Esto",  "start": 0.0, "end": 0.5},
        {"word": "es",    "start": 0.5, "end": 0.8},
    ]
    vf = _build_vf_animated(words, "")
    assert vf is not None
    assert vf.count("drawtext=") == 2
    assert "text='Esto'" in vf
    assert "text='es'" in vf


def test_pick_music_track_elige_de_la_carpeta_del_mood(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_MUSICA_DIR", tmp_path)
    (tmp_path / "tension").mkdir()
    pista = tmp_path / "tension" / "track.mp3"
    pista.write_bytes(b"fake mp3")

    assert _pick_music_track("tension") == pista


def test_pick_music_track_cae_a_neutral_si_mood_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_MUSICA_DIR", tmp_path)
    (tmp_path / "comedia").mkdir()  # existe pero vacía
    (tmp_path / "neutral").mkdir()
    pista = tmp_path / "neutral" / "track.mp3"
    pista.write_bytes(b"fake mp3")

    assert _pick_music_track("comedia") == pista


def test_pick_music_track_retorna_none_sin_ninguna_pista(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_MUSICA_DIR", tmp_path)
    assert _pick_music_track("tension") is None
