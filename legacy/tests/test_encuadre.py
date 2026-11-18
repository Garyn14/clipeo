"""
test_encuadre.py — CLIP-38: plan del encuadre 9:16 y su expresión de FFmpeg (sin OpenCV ni video).
"""

import pytest

from edicion_video import encuadre

ANCHO, ALTO = 1920, 1080
CW = encuadre.ancho_recorte(ALTO)          # 606


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


def test_ancho_de_recorte_9_16_par():
    assert CW == 606 and CW % 2 == 0


def test_sujeto_quieto_da_un_recorte_fijo_centrado_en_la_cara():
    plan = encuadre.planificar(muestras([1400] * 20), ANCHO, ALTO)
    assert {x for _, x in plan} == {1400 - CW // 2}
    assert encuadre.expresion_x(plan) == str(1400 - CW // 2)


def test_temblor_pequeno_no_mueve_la_camara():
    centros = [1000 + (30 if i % 2 else -30) for i in range(20)]   # ±30 px < zona muerta (115 px)
    plan = encuadre.planificar(muestras(centros), ANCHO, ALTO)
    assert len({x for _, x in plan}) == 1


def test_cambio_de_sujeto_se_sigue_con_velocidad_limitada():
    plan = encuadre.planificar(muestras([500] * 10 + [1500] * 20), ANCHO, ALTO)
    xs = [x for _, x in plan]
    assert xs[0] == 500 - CW // 2 and xs[-1] == 1500 - CW // 2
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


def test_filtro_crop_completo():
    f = encuadre.filtro_crop([(0.0, 657)], ALTO)
    assert f == f"crop=w={CW}:h={ALTO}:x='657':y=0,scale=1080:1920"


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
    assert encuadre.encuadrar("v.mp4", 0, 10, ANCHO, ALTO) == encuadre.filtro_crop([(0.0, 1400 - CW // 2)], ALTO)


# ── Integración con el render (agent4) ──────────────────────

def test_build_vf_usa_el_encuadre_y_texto_como_caso_b():
    from edicion_video import agent4_video_cutter as a4
    filtro = encuadre.filtro_crop([(0.0, 657)], ALTO)
    vf, params = a4._build_vf("Atacan a balazos", "tienda del tío Fritz", "", True, 420, "fijo",
                              layout="blur", source_width=ANCHO, source_height=ALTO, encuadre_filtro=filtro)
    assert vf.startswith(filtro) and "gblur" not in vf
    assert params["caso"] == "B" and params.get("encuadre_activo")


def test_build_vf_sin_encuadre_mantiene_el_blur():
    from edicion_video import agent4_video_cutter as a4
    vf, params = a4._build_vf("a", "b", "", True, 420, "fijo", layout="blur",
                              source_width=ANCHO, source_height=ALTO)
    assert "gblur" in vf and not params.get("encuadre_activo")


def test_cut_clip_pide_el_encuadre_solo_con_fuente_horizontal(monkeypatch, tmp_path):
    from edicion_video import agent4_video_cutter as a4
    pedidos, comandos = [], []
    monkeypatch.setattr(encuadre, "encuadrar", lambda *a: pedidos.append(a) or encuadre.filtro_crop([(0.0, 657)], ALTO))

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
