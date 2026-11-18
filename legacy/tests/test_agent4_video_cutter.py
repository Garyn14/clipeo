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
    _build_vf,
    _build_vf_animated,
    _build_vf_zoom,
    _build_vf_splitscreen,
    _build_vf_imagen,
    _build_vf_crop,
    _pick_music_track,
    _pick_imagen_relleno,
    _pick_sound_effect,
    _con_marca_agua,
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
    monkeypatch.setenv("MUSICA_FONDO", "1")
    monkeypatch.setattr(avc, "_MUSICA_DIR", tmp_path)
    (tmp_path / "tension").mkdir()
    pista = tmp_path / "tension" / "track.mp3"
    pista.write_bytes(b"fake mp3")

    assert _pick_music_track("tension") == pista


def test_pick_music_track_cae_a_neutral_si_mood_vacio(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSICA_FONDO", "1")
    monkeypatch.setattr(avc, "_MUSICA_DIR", tmp_path)
    (tmp_path / "comedia").mkdir()  # existe pero vacía
    (tmp_path / "neutral").mkdir()
    pista = tmp_path / "neutral" / "track.mp3"
    pista.write_bytes(b"fake mp3")

    assert _pick_music_track("comedia") == pista


def test_pick_music_track_retorna_none_sin_ninguna_pista(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_MUSICA_DIR", tmp_path)
    assert _pick_music_track("tension") is None


def test_build_vf_sin_texto_ignora_lineas_provistas():
    # estilo_texto="sin_texto" es una decisión editorial: aunque lleguen
    # líneas de texto, el módulo de edición no debe quemar nada.
    vf, params = _build_vf("hola", "mundo", "", False, 0, estilo_texto="sin_texto")
    assert "drawtext" not in vf
    assert "duracion_texto_seg" not in params


def test_build_vf_fijo_no_agrega_ventana_de_tiempo():
    vf, params = _build_vf("hola", "que tal", "", False, 0, estilo_texto="fijo")
    assert "enable=" not in vf
    assert "duracion_texto_seg" not in params


def test_build_vf_fijo_inicial_limita_duracion_en_vertical():
    vf, params = _build_vf("hola", "que tal", "", False, 0, estilo_texto="fijo_inicial")
    assert "enable=lte(t" in vf
    assert "duracion_texto_seg" in params


def test_build_vf_fijo_inicial_limita_duracion_en_letterbox():
    # has_letterbox solo decide geometría (barra), no si el texto es
    # efímero — fijo_inicial debe limitar la duración en ambos casos.
    vf, params = _build_vf("hola", "que tal", "", True, 200, estilo_texto="fijo_inicial")
    assert "enable=lte(t" in vf
    assert "duracion_texto_seg" in params
    # el drawbox (caja blanca) debe ocultarse junto con el texto — de lo
    # contrario queda una caja vacía en pantalla el resto del clip.
    drawbox_segment = vf.split("drawbox=")[1].split(",drawtext")[0]
    assert "enable=lte(t" in drawbox_segment


def test_build_vf_zoom_retorna_none_sin_momento():
    assert _build_vf_zoom(None, 640, 360) is None


def test_build_vf_zoom_retorna_none_sin_dimensiones():
    assert _build_vf_zoom(10.0, 0, 0) is None


def test_build_vf_zoom_escala_con_eval_frame_y_recorta_a_tamano_fijo():
    # scale con eval=frame (no crop dinámico) es lo que permite que el
    # zoom pueda agrandar Y volver a achicar — un crop con w/h en función
    # de t se achica pero después no vuelve a agrandar (probado empíricamente).
    vf = _build_vf_zoom(10.0, 640, 360)
    assert vf is not None
    assert "scale=" in vf
    assert "eval=frame" in vf
    assert "if(lt(t" in vf
    assert "crop=w=640:h=360" in vf


def test_build_vf_zoom_no_arranca_la_rampa_en_tiempo_negativo():
    # Momento de énfasis muy cerca del inicio del clip: el ffmpeg ya
    # recortado nunca ve t<0, así que la rampa debe clampear a 0.0.
    vf = _build_vf_zoom(0.0, 640, 360)
    assert vf is not None
    assert "lt(t\\,0.00)" in vf


def test_build_vf_sin_cta_no_agrega_nada_extra():
    _, params = _build_vf("hola", "", "", False, 0, cta_texto="", duracion_clip=20)
    assert "cta_desde_seg" not in params


def test_build_vf_cta_aparece_solo_en_los_ultimos_segundos():
    vf, params = _build_vf("hola", "", "", False, 0, cta_texto="Sigueme para mas", duracion_clip=20)
    assert "cta_desde_seg" in params
    assert params["cta_desde_seg"] == 17.0
    assert "enable=gte(t\\,17.0)" in vf
    assert "Sigueme para mas" in vf


def test_build_vf_pillarbox_no_usa_split_ni_blur():
    vf, params = _build_vf("hola", "que tal", "", True, 200, layout="pillarbox")
    assert "split=" not in vf
    assert "gblur" not in vf
    assert params["layout"] == "pillarbox"


def test_build_vf_blur_arma_split_y_overlay_en_letterbox():
    vf, params = _build_vf("hola", "que tal", "", True, 200, layout="blur")
    assert vf.startswith("split=2[_bgblur][_fgblur];")
    assert "gblur=sigma=20" in vf
    assert "overlay=(W-w)/2:(H-h)/2" in vf
    assert params["layout"] == "blur"


def test_build_vf_blur_no_aplica_sin_letterbox():
    # layout solo tiene sentido cuando hay barras que rellenar — en
    # vertical nativo (Caso B) no debe intentar el split.
    vf, params = _build_vf("hola", "que tal", "", False, 0, layout="blur")
    assert "split=" not in vf
    assert "layout" not in params


def test_build_vf_splitscreen_arma_dos_crops_y_vstack():
    vf = _build_vf_splitscreen(
        {"x": 0, "y": 0, "w": 640, "h": 240},
        {"x": 0, "y": 240, "w": 640, "h": 360},
    )
    assert vf.count("crop=") == 2
    assert "vstack=inputs=2" in vf
    assert "drawbox" not in vf  # sin overlays_ocultar, no debe aparecer


def test_build_vf_splitscreen_tapa_overlays_antes_del_split():
    vf = _build_vf_splitscreen(
        {"x": 0, "y": 0, "w": 640, "h": 240},
        {"x": 0, "y": 240, "w": 640, "h": 360},
        overlays_ocultar=[{"x": 500, "y": 10, "w": 130, "h": 40}],
    )
    assert vf.index("drawbox=x=500:y=10:w=130:h=40:color=black:t=fill") < vf.index("split=2")


def test_build_vf_splitscreen_activa_y_desactiva_letterbox():
    # Con layout_streaming completo, el split-screen resuelve el encuadre
    # por su cuenta — el texto debe posicionarse como Caso B, no Caso A,
    # sin importar el has_letterbox real de la fuente.
    vf, params = _build_vf(
        "hola", "que tal", "", True, 657,
        layout_streaming={
            "facecam_rect":   {"x": 0, "y": 0, "w": 640, "h": 240},
            "contenido_rect": {"x": 0, "y": 240, "w": 640, "h": 360},
        },
    )
    assert params["caso"] == "B"
    assert params["splitscreen"] is True
    assert "vstack=inputs=2" in vf


def test_build_vf_sin_layout_streaming_no_activa_splitscreen():
    _, params = _build_vf("hola", "que tal", "", True, 657, layout_streaming=None)
    assert "splitscreen" not in params


def test_pick_imagen_relleno_elige_de_la_carpeta_del_mood(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_IMAGENES_RELLENO_DIR", tmp_path)
    (tmp_path / "tension").mkdir()
    imagen = tmp_path / "tension" / "foto.jpg"
    imagen.write_bytes(b"fake jpg")
    assert _pick_imagen_relleno("tension") == imagen


def test_pick_imagen_relleno_cae_a_neutral_si_mood_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_IMAGENES_RELLENO_DIR", tmp_path)
    (tmp_path / "comedia").mkdir()
    (tmp_path / "neutral").mkdir()
    imagen = tmp_path / "neutral" / "foto.png"
    imagen.write_bytes(b"fake png")
    assert _pick_imagen_relleno("comedia") == imagen


def test_pick_imagen_relleno_retorna_none_sin_ninguna(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_IMAGENES_RELLENO_DIR", tmp_path)
    assert _pick_imagen_relleno("tension") is None


def test_pick_sound_effect_elige_de_la_carpeta_del_tipo(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_EFECTOS_SONIDO_DIR", tmp_path)
    (tmp_path / "whoosh").mkdir()
    efecto = tmp_path / "whoosh" / "sonido.mp3"
    efecto.write_bytes(b"fake mp3")
    assert _pick_sound_effect("whoosh") == efecto


def test_pick_sound_effect_sin_fallback_a_neutral(tmp_path, monkeypatch):
    # A diferencia de música/imagen, un tipo de efecto sin assets propios
    # NO cae a ninguna carpeta genérica — aunque exista "neutral" con algo.
    monkeypatch.setattr(avc, "_EFECTOS_SONIDO_DIR", tmp_path)
    (tmp_path / "neutral").mkdir()
    (tmp_path / "neutral" / "sonido.mp3").write_bytes(b"fake mp3")
    assert _pick_sound_effect("whoosh") is None


def test_pick_sound_effect_retorna_none_sin_ninguna(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_EFECTOS_SONIDO_DIR", tmp_path)
    assert _pick_sound_effect("whoosh") is None


def test_build_vf_imagen_arma_video_arriba_imagen_abajo_con_franjas():
    # Fuente 640x360, recorte suave (90% ancho) — matches la prueba visual
    # validada con el usuario.
    fragmento, params = _build_vf_imagen(640, 360)
    assert "crop=w=576:h=360:x=32:y=0" in fragmento
    assert "[1:v]scale=1080:" in fragmento
    assert "vstack=inputs=2" in fragmento
    assert "pad=1080:1920:0:" in fragmento
    # Franja de arriba más alta que la de abajo (ajuste visual pedido)
    assert params["barra_arriba"] > params["barra_abajo"]
    assert params["seam_y"] == params["barra_arriba"] + params["video_h"]
    # Todo suma exactamente 1920 (nada de negro/gap extra sin contabilizar)
    assert params["barra_arriba"] + params["video_h"] + params["imagen_h"] + params["barra_abajo"] == 1920


def test_build_vf_usa_imagen_ancla_texto_en_el_limite_con_solape():
    vf, params = _build_vf(
        "hola", "que tal", "", True, 657, layout="imagen",
        source_width=640, source_height=360,
        imagen_relleno_path=avc.Path("fake.jpg"),
    )
    assert params["imagen_activa"] is True
    assert params["caso"] == "IMG"
    # La caja empieza ANTES del límite real (solape), no justo en él
    assert params["y_box"] < params["seam_y"]
    assert "vstack=inputs=2" in vf


def test_build_vf_layout_imagen_sin_asset_cae_a_pillarbox():
    # Sin imagen_relleno_path resuelto, layout="imagen" no debe activarse
    # — se degrada a pillarbox en silencio, igual que música/marca de agua.
    vf, params = _build_vf(
        "hola", "que tal", "", True, 657, layout="imagen",
        source_width=640, source_height=360, imagen_relleno_path=None,
    )
    assert "imagen_activa" not in params
    assert params["caso"] == "A"
    assert "vstack" not in vf


def test_build_vf_crop_recorta_centrado_a_9_16():
    # Fuente 640x360 (mismo fixture que Fase 13): crop_w = int(360*9/16) = 202,
    # x_off = (640-202)//2 = 219.
    fragmento = _build_vf_crop(640, 360)
    assert "crop=w=202:h=360:x=219:y=0" in fragmento
    assert "scale=1080:1920" in fragmento
    assert "pad" not in fragmento
    assert "gblur" not in fragmento
    assert "vstack" not in fragmento


def test_build_vf_layout_crop_usa_geometria_de_texto_caso_b():
    vf, params = _build_vf(
        "hola", "que tal", "", True, 657, layout="crop",
        source_width=640, source_height=360,
    )
    assert params["crop_activo"] is True
    assert params["caso"] == "B"
    assert "crop=w=202:h=360:x=219:y=0" in vf


def test_con_marca_agua_respeta_start_index(tmp_path, monkeypatch):
    logo = tmp_path / "marca_agua.png"
    logo.write_bytes(b"fake png")
    monkeypatch.setattr(avc, "_MARCA_AGUA_PATH", logo)
    filtro, extra_inputs = _con_marca_agua("scale=1080:1920", start_index=2)
    assert "[2:v]scale=" in filtro
    assert extra_inputs == [logo]


def test_con_marca_agua_sin_archivo_no_cambia_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(avc, "_MARCA_AGUA_PATH", tmp_path / "no_existe.png")
    filtro, extra_inputs = _con_marca_agua("scale=1080:1920")
    assert filtro == "scale=1080:1920"
    assert extra_inputs == []


def test_con_marca_agua_con_archivo_agrega_overlay(tmp_path, monkeypatch):
    logo = tmp_path / "marca_agua.png"
    logo.write_bytes(b"fake png")
    monkeypatch.setattr(avc, "_MARCA_AGUA_PATH", logo)
    filtro, extra_inputs = _con_marca_agua("scale=1080:1920")
    assert extra_inputs == [logo]
    assert "[1:v]scale=" in filtro
    assert "overlay=W-w-30:H-h-30" in filtro
    assert filtro.startswith("scale=1080:1920[__premark];")


def test_build_vf_animated_resalta_palabras_clave_en_rojo():
    words = [
        {"word": "Fritz",  "start": 0.0, "end": 0.5},
        {"word": "vendio", "start": 0.5, "end": 0.8},
    ]
    vf = _build_vf_animated(words, "", palabras_clave=["fritz"])
    assert vf is not None
    fritz_filter  = [f for f in vf.split(",") if "text='Fritz'" in f][0]
    vendio_filter = [f for f in vf.split(",") if "text='vendio'" in f][0]
    assert "fontcolor=red" in fritz_filter
    assert "fontcolor=black" in vendio_filter


def test_preset_x264_veryfast_por_defecto_y_configurable(monkeypatch):
    """CLIP-39: el corte usa 'veryfast' (mitad de tiempo, misma calidad); CORTE_PRESET lo cambia."""
    from edicion_video import agent4_video_cutter as a4
    monkeypatch.delenv("CORTE_PRESET", raising=False)
    assert a4._preset_x264() == "veryfast"
    monkeypatch.setenv("CORTE_PRESET", "medium")
    assert a4._preset_x264() == "medium"



def test_musica_de_fondo_apagada_por_defecto(tmp_path, monkeypatch):
    """Operador, 2026-11-18: la música de prueba de la v1 no suma; solo con MUSICA_FONDO=1."""
    from edicion_video import agent4_video_cutter as a4
    monkeypatch.delenv("MUSICA_FONDO", raising=False)
    assert a4._pick_music_track("tension") is None


def test_con_encuadre_no_se_suma_el_punch_in(monkeypatch, tmp_path):
    from edicion_video import agent4_video_cutter as a4, encuadre
    comandos = []
    monkeypatch.setattr(encuadre, "encuadrar", lambda *a, **k: encuadre.filtro([(0.0, 600)], [], 1080))

    class Ok:
        returncode, stderr = 0, ""
    monkeypatch.setattr(a4.subprocess, "run", lambda cmd, **k: comandos.append(" ".join(map(str, cmd))) or Ok())
    a4._cut_clip(tmp_path / "v.mp4", "00:00:20", "00:01:00", "a", "b", tmp_path / "c.mp4", "", True, 420,
                 layout="blur", source_width=1920, source_height=1080, momento_enfasis_seg=5.0)
    assert comandos and "1.0+" not in comandos[0]                         # sin la rampa del punch-in de la v1
