"""
test_encuadre.py — CLIP-38: encuadre 4:5 que sigue caras, zoom solo por tramos y su filtro de FFmpeg (sin OpenCV ni video).
"""

import pytest

from edicion_video import encuadre

ANCHO, ALTO = 1920, 1080
CW = encuadre.ancho_recorte(ALTO)          # 864 (4:5)


def cara(cx, w=120):
    return (cx - w // 2, 400, w, w)


def muestras(centros):
    return [(round(i * encuadre.PASO_S, 2), [] if c is None else (c if isinstance(c, list) else [cara(c)]))
            for i, c in enumerate(centros)]


def x_en(keyframes, t):
    """Evalúa la trayectoria por tramos (lo mismo que hace la expresión de FFmpeg)."""
    for (t0, x0), (t1, x1) in zip(keyframes, keyframes[1:]):
        if t < t1:
            return x0 + (x1 - x0) * (t - t0) / (t1 - t0)
    return keyframes[-1][1]


def test_ancho_de_recorte_4_5_par():
    assert CW == 864 and CW % 2 == 0


def test_sujeto_quieto_da_un_recorte_fijo_centrado_en_la_cara():
    plan = encuadre.planificar(muestras([1400] * 20), ANCHO, ALTO)
    assert {x for _, x in plan} == {1400 - CW // 2}
    assert encuadre.expresion_x(plan) == str(1400 - CW // 2)


def test_temblor_pequeno_no_mueve_la_camara():
    centros = [1000 + (30 if i % 2 else -30) for i in range(20)]   # ±30 px < zona muerta (115 px)
    plan = encuadre.planificar(muestras(centros), ANCHO, ALTO)
    assert len({x for _, x in plan}) == 1


def test_cambio_de_sujeto_se_sigue_con_velocidad_limitada():
    plan = encuadre.planificar(muestras([500] * 10 + [1400] * 20), ANCHO, ALTO)
    xs = [x for _, x in plan]
    assert xs[0] == 500 - CW // 2 and xs[-1] == 1400 - CW // 2
    vmax = encuadre.VELOCIDAD_MAX * ANCHO
    for (t0, x0), (t1, x1) in zip(plan, plan[1:]):
        assert abs(x1 - x0) <= vmax * (t1 - t0) + 1


def test_el_recorte_no_se_sale_del_cuadro():
    plan = encuadre.planificar(muestras([40] * 10 + [1900] * 20), ANCHO, ALTO)
    assert all(0 <= x <= ANCHO - CW for _, x in plan)


def test_huecos_sin_cara_mantienen_la_posicion():
    centros = [800] * 6 + [None] * 3 + [800] * 6
    plan = encuadre.planificar(muestras(centros), ANCHO, ALTO)
    assert {x for _, x in plan} == {800 - CW // 2}


def test_dos_caras_cercanas_se_encuadran_juntas():
    plan = encuadre.planificar(muestras([[cara(900), cara(1200)]] * 12), ANCHO, ALTO)
    assert plan[0][1] == 1050 - CW // 2


@pytest.mark.parametrize("centros", [
    [None] * 12 + [900] * 8,                               # pocas caras
    [[cara(150), cara(1750)]] * 10 + [900] * 5,            # dos personas en los extremos
])
def test_respaldo_al_layout_anterior(centros):
    assert encuadre.planificar(muestras(centros), ANCHO, ALTO) is None


def test_fuente_vertical_o_sin_muestras_no_se_encuadra():
    assert encuadre.planificar([], ANCHO, ALTO) is None
    assert encuadre.planificar(muestras([300] * 10), 1080, 1920) is None


def test_expresion_reproduce_la_trayectoria():
    plan = [(0.0, 100), (2.0, 100), (4.0, 500), (6.0, 500)]
    expr = encuadre.expresion_x(plan)
    assert "\\," in expr and "," not in expr.replace("\\,", "")     # comas escapadas para el filtergraph
    for t in (0, 1, 2, 3, 4, 5, 6):
        assert round(x_en(plan, t)) == {0: 100, 1: 100, 2: 100, 3: 300, 4: 500, 5: 500, 6: 500}[t]
    assert expr.count("if(") == 3


def test_filtro_sin_zoom_caja_4_5_sobre_blur():
    f = encuadre.filtro([(0.0, 657)], [], ALTO)
    assert f"crop=w={CW}:h={ALTO}:x='657':y=0,scale=1080:1350" in f
    assert "gblur" in f and "overlay=(W-w)/2:(H-h)/2" in f and "eval=frame" not in f
    assert encuadre.BARRA == 285


def test_filtro_con_zoom_por_tramos():
    f = encuadre.filtro([(0.0, 657)], [(4.0, 9.0)], ALTO)
    assert "eval=frame" in f and "crop=1080:1350" in f and f"{encuadre.ZOOM}" in f


def test_zoom_solo_en_primeros_planos_largos():
    grande = (700, 300, 260, 260)                  # 260 px ≥ 22% de 1080
    datos = [(round(i * 0.5, 2), [grande] if 4 <= i < 14 else [cara(800)]) for i in range(40)]
    assert encuadre.secciones_zoom(datos, ALTO) == [(2.0, 7.0)]
    corto = [(round(i * 0.5, 2), [grande] if 4 <= i < 8 else [cara(800)]) for i in range(40)]
    assert encuadre.secciones_zoom(corto, ALTO) == []                       # 2 s < 3 s
    dos = [(round(i * 0.5, 2), [grande, cara(300)]) for i in range(40)]
    assert encuadre.secciones_zoom(dos, ALTO) == []                         # dos personas: sin zoom


def test_zoom_como_maximo_40_por_ciento_del_clip():
    grande = (700, 300, 260, 260)
    datos = [(round(i * 0.5, 2), [grande]) for i in range(40)]              # 20 s de primer plano
    assert encuadre.secciones_zoom(datos, ALTO) == []                       # un tramo de 20 s supera el 40%
    datos = [(round(i * 0.5, 2), [grande] if (i // 10) % 2 == 0 else [cara(800)]) for i in range(40)]
    secciones = encuadre.secciones_zoom(datos, ALTO)
    assert sum(b - a for a, b in secciones) <= 0.4 * 20 and secciones


def test_expresion_zoom_con_rampas():
    assert encuadre.expresion_zoom([]) == "1"
    z = encuadre.expresion_zoom([(4.0, 9.0)])
    assert z.count("if(") == 4 and "4.50" in z and "8.50" in z and "," not in z.replace("\\,", "")


def test_encuadrar_apagado_vertical_o_sin_opencv(monkeypatch):
    monkeypatch.setenv("ENCUADRE_INTELIGENTE", "0")
    assert encuadre.encuadrar("v.mp4", 0, 10, ANCHO, ALTO) is None
    monkeypatch.delenv("ENCUADRE_INTELIGENTE")
    assert encuadre.encuadrar("v.mp4", 0, 10, 1080, 1920) is None

    def sin_opencv(*a, **k):
        raise ImportError("cv2")
    monkeypatch.setattr(encuadre, "detectar_caras", sin_opencv)
    assert encuadre.encuadrar("v.mp4", 0, 10, ANCHO, ALTO) is None


def test_encuadrar_con_caras(monkeypatch):
    monkeypatch.setattr(encuadre, "detectar_caras", lambda *a: muestras([1400] * 20))
    assert encuadre.encuadrar("v.mp4", 0, 10, ANCHO, ALTO) == encuadre.filtro([(0.0, 1400 - CW // 2)], [], ALTO)


# ── Integración con el render (agent4) ──────────────────────

def test_build_vf_usa_el_encuadre_y_titulo_en_la_franja_de_arriba():
    from edicion_video import agent4_video_cutter as a4
    filtro = encuadre.filtro([(0.0, 657)], [], ALTO)
    vf, params = a4._build_vf("Atacan a balazos", "tienda del tío Fritz", "", True, 420, "fijo",
                              layout="blur", source_width=ANCHO, source_height=ALTO, encuadre_filtro=filtro)
    assert vf.startswith(filtro) and vf.count("gblur") == 1
    assert params["caso"] == "A" and params["bar_height"] == encuadre.BARRA and params.get("encuadre_activo")


def test_build_vf_sin_encuadre_mantiene_el_blur():
    from edicion_video import agent4_video_cutter as a4
    vf, params = a4._build_vf("a", "b", "", True, 420, "fijo", layout="blur",
                              source_width=ANCHO, source_height=ALTO)
    assert "gblur" in vf and not params.get("encuadre_activo")


def test_cut_clip_pide_el_encuadre_solo_con_fuente_horizontal(monkeypatch, tmp_path):
    from edicion_video import agent4_video_cutter as a4
    pedidos, comandos = [], []
    monkeypatch.setattr(encuadre, "encuadrar",
                        lambda *a, **k: pedidos.append(a) or encuadre.filtro([(0.0, 657)], [], ALTO))

    class Ok:
        returncode, stderr = 0, ""
    monkeypatch.setattr(a4.subprocess, "run", lambda cmd, **k: comandos.append(cmd) or Ok())
    monkeypatch.setattr(a4, "_pick_music_track", lambda mood: None)

    a4._cut_clip(tmp_path / "v.mp4", "00:00:20", "00:01:00", "a", "b", tmp_path / "c.mp4", "", True, 420,
                 layout="blur", source_width=ANCHO, source_height=ALTO)
    assert pedidos and pedidos[0][1:] == (20, 40, ANCHO, ALTO)
    assert any("x='657'" in " ".join(map(str, c)) for c in comandos)

    pedidos.clear()
    a4._cut_clip(tmp_path / "v.mp4", "00:00:20", "00:01:00", "a", "b", tmp_path / "c.mp4", "", False, 0,
                 layout="blur", source_width=1080, source_height=1920)
    assert not pedidos                                                   # vertical: no hace falta


def test_cara_fija_y_chica_de_un_grafico_de_tv_se_ignora():
    """Demo S6: la intérprete de señas de Latina (recuadro fijo abajo a la derecha) separaba el grupo."""
    interprete = (1701, 792, 60, 72)
    datos = [(round(i * 0.5, 2), [cara(700), interprete]) for i in range(20)]
    limpias, n = encuadre.quitar_superpuestas(datos, ANCHO, ALTO)
    assert len(n) == 1 and all(c == [cara(700)] for _, c in limpias)
    assert encuadre.planificar(datos, ANCHO, ALTO)[0][1] == 700 - CW // 2


def test_persona_quieta_pero_grande_no_es_grafico():
    datos = [(round(i * 0.5, 2), [cara(700, w=300)]) for i in range(20)]
    _, fijas = encuadre.quitar_superpuestas(datos, ANCHO, ALTO)
    assert fijas == []


def test_primer_plano_mas_ancho_que_el_recorte_se_centra():
    datos = [(round(i * 0.5, 2), [(1035, 0, 700, 456)]) for i in range(20)]
    assert encuadre.planificar(datos, ANCHO, ALTO)[0][1] == min(ANCHO - CW, 1385 - CW // 2)


def test_franja_inferior_de_medios_achica_el_recorte_e_ignora_caras_del_zocalo(monkeypatch):
    """Demo S6: en medios el zócalo del noticiero quedaba cortado; se excluye el 20% inferior."""
    util = encuadre.alto_util(ALTO, encuadre.FRANJA_MEDIOS)
    assert util == 864
    zocalo = (1701, 900, 60, 72)                                   # cara dentro de la franja excluida
    monkeypatch.setattr(encuadre, "detectar_caras",
                        lambda *a: [(round(i * 0.5, 2), [cara(700), zocalo]) for i in range(20)])
    f = encuadre.encuadrar("v.mp4", 0, 10, ANCHO, ALTO, franja_inferior=encuadre.FRANJA_MEDIOS)
    cw = encuadre.ancho_recorte(util)
    assert f == encuadre.filtro([(0.0, 700 - cw // 2)], [], util)


def test_run_agent_aplica_la_franja_solo_en_medios(monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from edicion_video import agent4_video_cutter as a4
    franjas = []
    def cortar(video, inicio, fin, l1, l2, salida, *a, **k):
        franjas.append(k.get("franja_inferior"))
        Path(salida).write_bytes(b"\x00")
        return True
    monkeypatch.setattr(a4, "_cut_clip", cortar)
    monkeypatch.setattr(a4, "_detect_video_info",
                        lambda p: {"width": ANCHO, "height": ALTO, "has_letterbox": True, "bar_height": 420})
    monkeypatch.setattr(a4, "_prepare_font", lambda: ("", "default"))
    (tmp_path / "v.mp4").write_bytes(b"\x00")
    item = {"publicar": True, "rango_original": {"inicio": "00:00:10", "fin": "00:00:40"}, "texto_linea1": "a"}
    (tmp_path / "contenido.json").write_text(json.dumps({"contenido": [
        item, {**item, "fuente": {"tipo": "medios", "sobre": "Tío Fritz"}}]}), encoding="utf-8")
    a4.run_agent(str(tmp_path / "contenido.json"), video_path_override=tmp_path / "v.mp4")
    assert franjas == [0.0, encuadre.FRANJA_MEDIOS]



# ── S7: reconocer a la persona del clip (CLIP-40) y recuadros de TV (CLIP-42) ──

def test_la_cara_reconocida_manda_aunque_otra_sea_mas_grande():
    """Demo S6: en la joyería encuadraba al joyero (cara más visible) y no a Fritz."""
    fritz = (300, 400, 90, 90, True)
    joyero = (1400, 380, 200, 200, False)
    plan = encuadre.planificar([(round(i * 0.5, 2), [fritz, joyero]) for i in range(20)], ANCHO, ALTO)
    assert plan[0][1] == max(0, 345 - CW // 2)
    sin_reconocer = [(round(i * 0.5, 2), [fritz[:4], joyero[:4]]) for i in range(20)]
    assert encuadre.planificar(sin_reconocer, ANCHO, ALTO) is None or         encuadre.planificar(sin_reconocer, ANCHO, ALTO)[0][1] != max(0, 345 - CW // 2)


def test_zoom_solo_en_primeros_planos_del_sujeto_reconocido():
    otro = (700, 300, 260, 260, False)
    datos = [(round(i * 0.5, 2), [otro] if 4 <= i < 14 else [cara(800) + (False,)]) for i in range(40)]
    assert encuadre.secciones_zoom(datos, ALTO) == []
    fritz = otro[:4] + (True,)
    datos = [(round(i * 0.5, 2), [fritz] if 4 <= i < 14 else [cara(800) + (False,)]) for i in range(40)]
    assert encuadre.secciones_zoom(datos, ALTO) == [(2.0, 7.0)]


def test_la_ventana_deja_fuera_el_recuadro_de_la_interprete():
    interprete = (1701, 792, 60, 72)
    datos = [(round(i * 0.5, 2), [cara(1300), interprete]) for i in range(20)]
    plan = encuadre.planificar(datos, ANCHO, ALTO)
    limite = 1731 - encuadre.MARGEN_RECUADRO * 60
    assert all(x + CW <= limite for _, x in plan)
    assert all(x <= 1300 <= x + CW for _, x in plan)                     # el sujeto sigue dentro


def test_si_el_sujeto_esta_pegado_al_recuadro_manda_el_sujeto():
    interprete = (1701, 792, 60, 72)
    datos = [(round(i * 0.5, 2), [cara(1700, w=150), interprete]) for i in range(20)]
    plan = encuadre.planificar(datos, ANCHO, ALTO)
    assert all(x <= 1700 <= x + CW for _, x in plan)


def test_slug_y_referencias(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")   # el CI no instala numpy (dependencias livianas)
    assert encuadre.slug("Tío Fritz") == "tio_fritz"
    monkeypatch.setattr(encuadre, "DIR_CARAS", tmp_path)
    modelo = tmp_path / "sface.onnx"
    monkeypatch.setattr(encuadre, "MODELO_SFACE", modelo)
    assert encuadre.cargar_referencias("Tío Fritz") is None                # sin modelo
    modelo.write_bytes(b"x")
    assert encuadre.cargar_referencias("Tío Fritz") is None                # sin referencias
    np.save(tmp_path / "tio_fritz.npy", np.eye(2, 128))
    assert encuadre.cargar_referencias("Tío Fritz").shape == (2, 128)
    assert encuadre.cargar_referencias(None) is None
