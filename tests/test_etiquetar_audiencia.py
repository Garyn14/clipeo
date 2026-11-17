"""CLIP-33 — cruce de clips aprobados con videos publicados por duración y fecha."""

from datetime import date

from evaluacion import etiquetar_audiencia as ea


def _clip(i, dur, rev=date(2026, 10, 10)):
    return {"id": i, "clave": f"s/{i}", "dur": dur, "revision": rev}


def _video(i, dur, pub=date(2026, 10, 11), outlier=2.0):
    return {"id": i, "_dur": dur, "_pub": pub, "outlier": outlier}


def test_cruce_unico_es_automatico():
    res = ea.cruzar([_clip("a", 33)], [_video("v1", 33), _video("v2", 50)])
    assert [(c["id"], v["id"]) for c, v in res["automaticos"]] == [("a", "v1")]


def test_video_candidato_de_dos_clips_nunca_se_asigna_solo():
    """El caso real del S3: 44 s y 43 s comparten el video de 43 s → ambos dudosos."""
    res = ea.cruzar([_clip("a", 44), _clip("b", 43)], [_video("v1", 43)])
    assert not res["automaticos"] and {c["id"] for c, _ in res["dudosos"]} == {"a", "b"}


def test_fuera_de_fecha_o_duracion_queda_sin_publicar():
    res = ea.cruzar([_clip("a", 30)], [_video("v1", 30, pub=date(2026, 12, 1)), _video("v2", 45)])
    assert [c["id"] for c in res["sin_publicar"]] == ["a"]


def test_manual_se_conserva_y_avisa_si_el_cruce_la_contradice():
    res = {"automaticos": [(_clip("a", 33), _video("v9", 33))], "dudosos": [], "sin_publicar": [_clip("b", 50)]}
    existentes = [{"clave_correccion": "s/a", "video_id": "v1", "outlier": 1.0},
                  {"clave_correccion": "s/b", "video_id": "v2", "outlier": 1.0},
                  {"clave_correccion": "s/c", "video_id": "v3", "outlier": 1.0, "fuente": "automatica"}]
    nuevas, avisos = ea.actualizar(existentes, res)
    assert [e["clave_correccion"] for e in nuevas] == ["s/a", "s/b"]   # la automática vieja se recalcula
    assert len(avisos) == 2


def test_titulo_de_portada_desempata_entre_duraciones_parecidas():
    """Caso real: varios clips de ~48 s revisados el mismo día; el título quemado decide."""
    clips = [dict(_clip("a", 48), titulo="El tío Fritz exige cinco videos diarios a su editor"),
             dict(_clip("b", 49), titulo="El tío Fritz presiona a su técnico por internet")]
    videos = [dict(_video("v1", 48), titulo_pantalla="El tío Fritz exige cinco videos diarios a su editor y lo presiona"),
              dict(_video("v2", 48), titulo_pantalla="El tío Fritz pilla a Rafael durmiendo")]
    res = ea.cruzar(clips, videos)
    assert [(c["id"], v["id"]) for c, v in res["automaticos"]] == [("a", "v1")]
    assert [c["id"] for c in res["sin_publicar"]] == ["b"]
