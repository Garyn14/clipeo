"""test_control_calidad.py — S11: control de calidad del clip (CLIP-51/52) y correcciones sin duplicados (CLIP-53)."""

import json

from edicion_video import control_calidad as cc, encuadre

SALIDA_FFMPEG = """
  Duration: 00:00:42.50, start: 0.000000, bitrate: 2000 kb/s
[blackdetect @ 0x1] black_start:0 black_end:0.8 black_duration:0.8
[blackdetect @ 0x1] black_start:20.1 black_end:20.6 black_duration:0.5
[freezedetect @ 0x2] lavfi.freezedetect.freeze_duration: 2.7
[silencedetect @ 0x3] silence_end: 30.0 | silence_duration: 3.4
[Parsed_volumedetect_0 @ 0x4] mean_volume: -27.7 dB
[Parsed_volumedetect_0 @ 0x4] max_volume: 0.0 dB
[Parsed_volumedetect_0 @ 0x4] n_samples: 100000
[Parsed_volumedetect_0 @ 0x4] histogram_0db: 2500
"""


def test_parsear_salida_de_ffmpeg():
    m = cc.parsear(SALIDA_FFMPEG)
    assert m["negros"] == [(0.0, 0.8), (20.1, 20.6)] and m["congelados"] == [2.7] and m["silencios"] == [3.4]
    assert m["volumen_medio"] == -27.7 and m["volumen_max"] == 0.0 and m["duracion"] == 42.5
    assert m["fraccion_0db"] == 0.025


def test_hallazgos_de_un_clip_con_problemas():
    codigos = [h["codigo"] for h in cc.hallazgos(cc.parsear(SALIDA_FFMPEG), duracion_esperada=50, escala_encuadre=2.1)]
    assert codigos == ["duracion_corta", "negro", "congelado", "silencio", "saturado", "acercamiento"]


def test_clip_limpio_sin_avisos():
    m = {"negros": [], "congelados": [], "silencios": [], "volumen_medio": -27.7, "volumen_max": 0.0, "duracion": 43,
         "fraccion_0db": 0.002}                                   # picos sueltos en 0 dB: no es distorsión
    assert cc.hallazgos(m, duracion_esperada=43, escala_encuadre=1.25) == []


def test_mudo_tiene_prioridad_sobre_silencio():
    m = {"negros": [], "congelados": [], "silencios": [40.0], "volumen_medio": -60, "volumen_max": -40, "duracion": 40}
    assert [h["codigo"] for h in cc.hallazgos(m)] == ["mudo"]


def test_revisar_nunca_rompe(tmp_path):
    assert cc.revisar(tmp_path / "no_existe.mp4") == [] or isinstance(cc.revisar(tmp_path / "no_existe.mp4"), list)


def test_escala_del_encuadre():
    assert encuadre.escala(None) is None
    assert encuadre.escala(encuadre.filtro([(0.0, 600)], [], 1080)) == round(1080 / 864, 2)          # 4:5 sin zoom
    con_zoom = encuadre.filtro([(0.0, 600)], [(2.0, 8.0)], 864)                                   # medios + zoom
    assert encuadre.escala(con_zoom) == round(1080 / 690 * encuadre.ZOOM, 2) and encuadre.escala(con_zoom) > cc.ESCALA_MAX


def test_correcciones_sin_duplicados_por_re_aprobar(tmp_path, monkeypatch):
    from investigacion import comun
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    filas = [
        {"session_id": "s", "clip_id": "clip_c001_03", "accion": "aprobado", "juez": {"linea1": "Casero", "linea2": "sube"}},
        {"session_id": "s", "clip_id": "clip_c001_01", "accion": "descartado", "juez": {"linea1": "Otro", "linea2": ""}},
        {"session_id": "s", "clip_id": "clip_c001_01", "accion": "aprobado", "juez": {"linea1": "Casero", "linea2": "sube"}},
    ]
    (d / "correcciones.jsonl").write_text("".join(json.dumps(f) + "\n" for f in filas), encoding="utf-8")
    texto = comun.cargar_correcciones("n")
    assert texto.count("Casero") == 1 and texto.splitlines()[-1].startswith("- APROBÓ «Casero")
