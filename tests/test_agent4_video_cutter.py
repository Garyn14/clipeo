"""
test_agent4_video_cutter.py — Tests unitarios para _sanitize_text()
(edicion_video/agent4_video_cutter.py).
"""

from edicion_video.agent4_video_cutter import _sanitize_text


def test_sanitize_preserva_emoji():
    assert _sanitize_text("esto es lo que tiene por dentro 😱") == "esto es lo que tiene por dentro 😱"
    assert _sanitize_text("no puede ser 👀") == "no puede ser 👀"
    assert _sanitize_text("bravazo 🔥") == "bravazo 🔥"
    assert _sanitize_text("jajaja 😂") == "jajaja 😂"


def test_sanitize_preserva_espanol():
    assert _sanitize_text("Tío Fritz vendió más caro") == "Tío Fritz vendió más caro"
    assert _sanitize_text("¿no puede ser? ¡increíble!") == "¿no puede ser? ¡increíble!"


def test_sanitize_quita_metacaracteres_ffmpeg():
    assert _sanitize_text('el número 1, dice: "nadie me iguala"') == "el número 1 dice nadie me iguala"
    assert _sanitize_text("no puede ser; ni yo lo creo") == "no puede ser ni yo lo creo"
    assert _sanitize_text("Fritz's tienda") == "Fritz s tienda"


def test_sanitize_colapsa_espacios_dobles():
    assert _sanitize_text("hola,   mundo") == "hola mundo"
