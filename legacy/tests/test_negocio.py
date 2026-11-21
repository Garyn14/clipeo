"""test_negocio.py — S17: lector de cuentas (CLIP-73) y reporte de negocio por mes (CLIP-74). Sin red."""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from investigacion import comun, negocio as ng

AHORA = datetime(2026, 11, 21, 18, tzinfo=timezone.utc)


def _ts(dia: int, mes: int = 11) -> int:
    return int(datetime(2026, mes, dia, 12, tzinfo=timezone.utc).timestamp())


ENTRADAS_TT = [
    {"id": "111", "title": "Clip Clipeo noviembre", "timestamp": _ts(10), "view_count": 1000, "like_count": 50,
     "comment_count": 5, "repost_count": 5, "duration": 40, "url": "https://www.tiktok.com/@cuenta/video/111"},
    {"id": "222", "title": "Video propio noviembre", "timestamp": _ts(12), "view_count": 300, "like_count": 10,
     "comment_count": 0, "repost_count": 0, "url": "https://www.tiktok.com/@cuenta/video/222"},
    {"id": "333", "title": "Octubre", "timestamp": _ts(5, 10), "view_count": 500, "like_count": 20,
     "comment_count": 0, "repost_count": 0, "url": "https://www.tiktok.com/@cuenta/video/333"},
]
ENTRADAS_YT = [
    {"id": "yt1abcdefgh", "title": "Short Clipeo", "upload_date": "20261115", "view_count": 10, "like_count": 1,
     "comment_count": None, "duration": 30},
]


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    monkeypatch.setattr(ng, "LEGACY", tmp_path)
    monkeypatch.setenv("CLIPEO_NEGOCIO", str(tmp_path / "data" / "negocio"))
    (tmp_path / "contexto" / "nichos").mkdir(parents=True)
    (tmp_path / "contexto" / "nichos" / "n.yaml").write_text(
        "publicacion:\n  tiktok_perfil: '@cuenta'\n  youtube_canal: UCUuYyvh52_GsWKFR6cq-2hgXX\n", encoding="utf-8")
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    (d / "fuentes.yaml").write_text("cliente: Tío Prueba\ncanales: []\n", encoding="utf-8")
    (d / "publicados.jsonl").write_text(json.dumps({"session_id": "20261110_propio_x", "clip_id": "clip_c001_01",
                                                    "url": "https://www.tiktok.com/@cuenta/video/111"}) + "\n",
                                        encoding="utf-8")
    (d / "metricas_publicados.jsonl").write_text(json.dumps({"clave": "20261110_propio_x/clip_c001_01",
                                                             "tipo": "precio_y_oferta", "medios": False}) + "\n",
                                                 encoding="utf-8")
    (d / "fuentes_historial.jsonl").write_text(json.dumps({"id": "kk", "url": "https://kick.com/fritzsport/videos/kk",
                                                           "rol": "propio", "estado": "procesado",
                                                           "sesion": "20261110_propio_x"}) + "\n", encoding="utf-8")
    (d / "correcciones.jsonl").write_text("".join(json.dumps(r) + "\n" for r in [
        {"fecha": "2026-11-10T10:00:00", "accion": "aprobado"}, {"fecha": "2026-11-11T10:00:00", "accion": "descartado"},
        {"fecha": "2026-10-11T10:00:00", "accion": "aprobado"}]), encoding="utf-8")
    base = tmp_path / "publicacion.db"
    conn = sqlite3.connect(str(base))
    conn.execute("CREATE TABLE cuentas (plataforma TEXT, nicho TEXT)")
    conn.execute("CREATE TABLE publicaciones (plataforma TEXT, session_id TEXT, clip_id TEXT, nicho TEXT, estado TEXT, "
                 "publish_id TEXT, enviada_en TEXT, id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO publicaciones (plataforma, session_id, clip_id, nicho, estado, publish_id, enviada_en) "
                 "VALUES ('youtube', '20261112_medios_y', 'clip_c001_02', 'n', 'en_bandeja', 'yt1abcdefgh', "
                 "'2026-11-15T10:00:00')")
    conn.commit(); conn.close()
    from investigacion import medir_publicados as mp
    monkeypatch.setattr(mp, "_stream_data", lambda: tmp_path / "stream_data")
    monkeypatch.setattr(mp, "_contexto_clip", lambda clave, sd: {"tipo": "medios_y_polemica", "medios": True})
    return base


def _lector(cuenta):
    entradas = ENTRADAS_TT if cuenta["plataforma"] == "tiktok" else ENTRADAS_YT
    return [ng.fila_video(e, cuenta["plataforma"], cuenta["cuenta"]) for e in entradas]


def test_cuentas_del_cliente(entorno):
    lista, avisos = ng.cuentas("n", entorno)
    assert [c["plataforma"] for c in lista] == ["tiktok", "youtube"] and avisos == []
    assert lista[0]["url"] == "https://www.tiktok.com/@cuenta"


def test_fila_video_normaliza_fechas_y_links():
    tt = ng.fila_video(ENTRADAS_TT[0], "tiktok", "@cuenta")
    assert tt["publicado"].startswith("2026-11-10") and tt["vistas"] == 1000 and tt["compartidos"] == 5
    yt = ng.fila_video(ENTRADAS_YT[0], "youtube", "UC…")
    assert yt["publicado"].startswith("2026-11-15") and yt["url"] == "https://www.youtube.com/shorts/yt1abcdefgh"


def test_actualizar_marca_clipeo_guarda_foto_y_sigue_si_una_cuenta_falla(entorno, tmp_path):
    foto = ng.actualizar("n", lector=_lector, base=entorno, ahora=AHORA)
    tt = foto["cuentas"][0]["videos"]
    clip = next(v for v in tt if v["id"] == "111")
    assert clip["clipeo"] and clip["tipo"] == "precio_y_oferta" and clip["origen"] == "Kick"
    assert not next(v for v in tt if v["id"] == "222")["clipeo"]
    yt = foto["cuentas"][1]["videos"][0]
    assert yt["clipeo"] and yt["origen"] == "TV / medios"                  # medios según el clip
    archivo = tmp_path / "data" / "negocio" / "n" / "20261121_180000.json"
    assert archivo.exists() and ng.ultima_foto("n")["fecha"] == foto["fecha"]

    def lector_caido(cuenta):
        if cuenta["plataforma"] == "youtube":
            raise RuntimeError("sin red")
        return _lector(cuenta)
    foto = ng.actualizar("n", lector=lector_caido, base=entorno, ahora=AHORA)
    assert foto["cuentas"][1]["error"] == "sin red" and len(foto["cuentas"][0]["videos"]) == 3


def test_reporte_del_mes_con_comparacion_y_desgloses(entorno):
    ng.actualizar("n", lector=_lector, base=entorno, ahora=AHORA)
    r = ng.reporte("n", "2026-11", base=entorno)
    s = r["resumen"]
    assert (s["videos"], s["vistas"], s["interacciones"]) == (3, 1310, 60 + 10 + 1)
    assert s["anterior"]["vistas"] == 500 and s["variacion"]["vistas"] == pytest.approx(1.62)
    assert [t["vistas"] for t in r["top"]] == [1000, 300, 10] and r["bottom"] == []
    assert {g["grupo"]: g["videos"] for g in r["por_origen"]} == {"Kick": 1, "TV / medios": 1, "No es de Clipeo": 1}
    assert {g["grupo"]: g["vistas"] for g in r["clipeo_vs_resto"]} == {"Clipeo": 1010, "Resto de la cuenta": 300}
    assert r["produccion"] == {"revisados": 2, "aprobados": 1, "enviados": {"youtube": 1}}
    assert [e["mes"] for e in r["evolucion"]][-2:] == ["2026-10", "2026-11"] and r["evolucion"][-2]["vistas"] == 500
    assert r["meses"] == ["2026-11", "2026-10"] and r["cliente"] == "Tío Prueba" and r["seguidores"] is None
    octubre = ng.reporte("n", "2026-10", base=entorno)                     # otro mes, sin volver a leer
    assert octubre["resumen"]["videos"] == 1 and octubre["produccion"]["revisados"] == 1


def test_sin_foto_y_vista_global(entorno):
    assert ng.reporte("n", base=entorno)["foto"] is None
    assert ng.global_(base=entorno)[0]["foto"] is None
    ng.actualizar("n", lector=_lector, base=entorno, ahora=AHORA)
    fila = ng.global_("2026-11", base=entorno)[0]
    assert fila["cliente"] == "Tío Prueba" and fila["resumen"]["vistas"] == 1310 and fila["cuentas"] == 2


def test_mes_anterior_y_variacion():
    assert ng.mes_anterior("2026-01") == "2025-12" and ng.mes_anterior("2026-11") == "2026-10"
    assert ng.variacion(150, 100) == 0.5 and ng.variacion(10, 0) is None
