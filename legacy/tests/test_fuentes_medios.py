"""test_fuentes_medios.py — CLIP-43: candidatos de TV/prensa sobre la persona del nicho (sin red)."""

import json

from investigacion import comun, fuentes_medios as fm


def r(vid, canal, dur=150, titulo="Nota"):
    return {"id": vid, "channel": canal, "duration": dur, "title": titulo}


def test_filtra_canal_propio_sin_canal_duracion_y_vistos(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "exclusion.yaml"))
    res = [r("a", "Latina Noticias"), r("b", "FRITZ SPORT"), r("c", "FritzSport"), r("d", ""),
           r("e", "24 Horas", dur=20), r("f", "24 Horas", dur=4000), r("g", "Panorama"), r("a", "Latina Noticias")]
    out = fm.filtrar(res, "Tío Fritz", ya_vistos={"g"})
    assert [c["id"] for c in out] == ["a"]
    assert out[0]["estado"] == "pendiente" and out[0]["url"].endswith("v=a") and out[0]["sobre"] == "Tío Fritz"


def test_respeta_la_lista_de_exclusion(monkeypatch, tmp_path):
    ex = tmp_path / "exclusion.yaml"
    ex.write_text("canales: [Latina Noticias]\npersonas: []\n", encoding="utf-8")
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(ex))
    assert fm.filtrar([r("a", "Latina Noticias")], "Tío Fritz", set()) == []


def test_ids_procesados_desde_las_sesiones(tmp_path):
    s = tmp_path / "s1"; s.mkdir()
    (s / "pipeline_estado.json").write_text(json.dumps({"url": "https://www.youtube.com/watch?v=XYZ&t=3"}), encoding="utf-8")
    t = tmp_path / "s2"; t.mkdir()
    (t / "pipeline_estado.json").write_text(json.dumps({"url": "https://www.tiktok.com/@x/live"}), encoding="utf-8")
    assert fm.ids_procesados(tmp_path) == {"XYZ"}


def test_buscar_agrega_solo_nuevos_y_descartar(monkeypatch, tmp_path):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "exclusion.yaml"))
    monkeypatch.setenv("CLIPEO_STREAM_DATA", str(tmp_path / "sd"))
    monkeypatch.setattr(fm, "_buscar_youtube", lambda q, n: [r("a", "Latina Noticias"), r("b", "Panorama")])
    assert len(fm.buscar("nicho_x", "Tío Fritz")) == 2
    assert fm.buscar("nicho_x", "Tío Fritz") == []                      # ya listados
    fm._marcar("nicho_x", {"a"}, estado="descartado")
    assert [f["id"] for f in fm.pendientes("nicho_x")] == ["b"]
