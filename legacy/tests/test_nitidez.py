"""test_nitidez.py — CLIP-41: el clip no arranca en un cuadro movido."""

from edicion_video import nitidez


def test_primer_cuadro_movido_corre_el_inicio_un_segundo():
    assert nitidez.elegir_desfase([(0.0, 40.0), (1.0, 300.0)]) == 1


def test_primer_cuadro_nitido_no_cambia_nada():
    assert nitidez.elegir_desfase([(0.0, 250.0), (1.0, 300.0)]) == 0
    assert nitidez.elegir_desfase([(0.0, 300.0), (1.0, 40.0)]) == 0


def test_sin_datos_o_video_ilegible_no_cambia_nada(tmp_path):
    assert nitidez.elegir_desfase([]) == 0
    assert nitidez.elegir_desfase([(0.0, 0.0), (1.0, 0.0)]) == 0
    assert nitidez.desfase_inicio(tmp_path / "no_existe.mp4", 10) == 0
