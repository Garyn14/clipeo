"""
test_agent4_video_cutter.py — Tests unitarios para _sanitize_text()
(edicion_video/agent4_video_cutter.py).
"""

from edicion_video.agent4_video_cutter import _sanitize_text, _text_display_duration


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
