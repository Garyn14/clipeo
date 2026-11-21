"""test_fuentes_kick.py — CLIP-70: fuente Kick (directos grabados de canales propios), sin red."""

from datetime import timedelta

import pytest

from investigacion import comun, fuentes_config as fc, fuentes_estaticas as fe, tipos_fuente as tf

VODS = [
    {"start_time": "2026-11-20 19:17:46", "session_title": "Transmisión en directo de FritzSport", "is_live": False,
     "duration": 2142000, "video": {"uuid": "a1159d5f-7b6d-45a4-adf1-763c1807f7fc"}},
    {"start_time": "2026-11-21 10:00:00", "session_title": "En vivo ahora", "is_live": True,
     "duration": 0, "video": {"uuid": "vivo-ahora"}},
    {"start_time": "2026-11-18 20:00:00", "session_title": "", "is_live": False, "duration": 3600000,
     "video": {"uuid": "viejo-1"}},
]


def test_slug():
    assert tf.kick_slug("https://kick.com/FritzSport") == "fritzsport"
    assert tf.kick_slug("kick.com/fritzsport/videos/abc") == "fritzsport"
    assert tf.kick_slug("@fritzsport") == "fritzsport"
    assert tf.kick_slug("https://www.youtube.com/@x") is None


def test_parsear_vods_solo_grabados():
    videos = tf.parsear_vods("fritzsport", VODS)
    assert [v["id"] for v in videos] == ["a1159d5f-7b6d-45a4-adf1-763c1807f7fc", "viejo-1"]   # el vivo no entra
    v = videos[0]
    assert v["url"] == "https://kick.com/fritzsport/videos/a1159d5f-7b6d-45a4-adf1-763c1807f7fc"
    assert v["duracion_s"] == 2142 and v["publicado"].tzinfo is not None
    assert videos[1]["titulo"] == "Directo grabado"


@pytest.fixture
def nicho(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "ex.yaml"))
    monkeypatch.setattr(fe, "ids_ya_procesados", lambda sd: set())

    def falso_get(ruta):
        if ruta == "fritzsport":
            return {"slug": "fritzsport", "user": {"username": "FritzSport"}}
        if ruta == "fritzsport/videos":
            return VODS
        raise tf.FuenteError("Kick no respondió (404)")
    monkeypatch.setattr(tf, "_kick_get", falso_get)
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    (d / "fuentes.yaml").write_text("activo: true\nventana_inicial_dias: 7\ncanales: []\n", encoding="utf-8")
    return d


def test_agregar_kick_propio_y_buscar(nicho):
    vista = fc.previsualizar("kick", "kick.com/fritzsport")
    assert vista["nombre"] == "FritzSport" and len(vista["videos"]) == 2
    with pytest.raises(tf.FuenteError, match="solo admite el rol Propio"):
        fc.agregar_canal("n", "kick", "kick.com/fritzsport", "medios")
    canal = fc.agregar_canal("n", "kick", "https://kick.com/FritzSport", "propio")
    assert canal["url"] == "https://kick.com/fritzsport" and canal["plataforma"] == "kick"
    with pytest.raises(tf.FuenteError, match="solo admite"):
        fc.editar_canal("n", canal["url"], rol="medios")

    ahora = tf.parsear_vods("fritzsport", VODS)[0]["publicado"] + timedelta(days=1)
    r = fe.ejecutar("n", ahora=ahora)                      # ventana inicial de 7 días: entran los 2 grabados
    assert r["canales"] == [{"canal": "FritzSport", "nuevos": 2, "descartados": 0}]
    urls = {c["url"] for c in fe.candidatos("n")}
    assert "https://kick.com/fritzsport/videos/a1159d5f-7b6d-45a4-adf1-763c1807f7fc" in urls


def test_kick_caido_no_frena_las_demas(nicho):
    with pytest.raises(tf.FuenteError, match="Kick no respondió"):
        fc.previsualizar("kick", "kick.com/otro")
    (nicho / "fuentes.yaml").write_text(
        "activo: true\ncanales:\n  - {nombre: Otro, plataforma: kick, url: 'https://kick.com/otro', rol: propio}\n",
        encoding="utf-8")
    r = fe.ejecutar("n")
    assert r["canales"][0]["canal"] == "Otro" and "Kick no respondió" in r["canales"][0]["error"]


def test_dedup_vod_ya_procesado(tmp_path):
    import json
    from investigacion.fuentes_medios import ids_procesados
    s = tmp_path / "20261121_propio_x"; s.mkdir()
    (s / "pipeline_estado.json").write_text(json.dumps({"url": "https://kick.com/fritzsport/videos/abc-123"}),
                                            encoding="utf-8")
    assert "abc-123" in ids_procesados(tmp_path)
