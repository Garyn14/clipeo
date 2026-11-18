"""test_experimento_titulo.py — CLIP-44: variantes de título y su comparación con la audiencia."""

import json

from edicion_video import agent4_video_cutter as a4


def test_asignacion_estable_y_mitad_y_mitad(monkeypatch):
    monkeypatch.delenv("EXPERIMENTO_TITULO", raising=False)
    claves = [f"s/clip_c001_{i:02d}" for i in range(200)]
    variantes = [a4.estilo_titulo_para(c) for c in claves]
    assert variantes == [a4.estilo_titulo_para(c) for c in claves]          # estable
    assert 70 < variantes.count("contorno") < 130                            # ~mitad


def test_se_puede_apagar_o_fijar(monkeypatch):
    monkeypatch.setenv("EXPERIMENTO_TITULO", "0")
    assert a4.estilo_titulo_para("x") == "caja"
    monkeypatch.setenv("EXPERIMENTO_TITULO", "contorno")
    assert a4.estilo_titulo_para("x") == "contorno"


def test_contorno_quita_la_caja_y_agrega_borde_pero_no_toca_el_cta():
    vf, params = a4._build_vf("Atacan a balazos", "tienda del tío Fritz", "", True, 420, "fijo",
                              cta_texto="Sigue para más", duracion_clip=30, estilo_titulo="contorno")
    assert "color=white:t=fill" not in vf and "borderw=5:bordercolor=black" in vf
    assert "box=1:boxcolor=white" in vf                                       # el CTA conserva su caja
    assert params["estilo_titulo"] == "contorno"
    vf_caja, _ = a4._build_vf("Atacan a balazos", "tienda del tío Fritz", "", True, 420, "fijo")
    assert "color=white:t=fill" in vf_caja and "borderw=5" not in vf_caja


def test_comparar_agrupa_outliers_por_variante(tmp_path):
    from evaluacion.experimento_titulo import comparar
    for clip, estilo in (("c1", "caja"), ("c2", "contorno"), ("c3", "contorno")):
        d = tmp_path / "s1" / "clips"; d.mkdir(parents=True, exist_ok=True)
        (d / f"{clip}.json").write_text(json.dumps({"estilo_titulo": estilo}), encoding="utf-8")
    etiquetas = [{"clave_correccion": "s1/c1", "outlier": 2.0}, {"clave_correccion": "s1/c2", "outlier": 5.0},
                 {"clave_correccion": "s1/c3", "outlier": 0.5}, {"clave_correccion": "s1/nada", "outlier": 9.0}]
    assert comparar(etiquetas, tmp_path) == {"caja": [2.0], "contorno": [5.0, 0.5]}
