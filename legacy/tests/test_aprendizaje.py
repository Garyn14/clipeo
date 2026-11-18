"""test_aprendizaje.py — S10: medición de publicados (CLIP-48), aprendizaje por tipo (CLIP-49) y crédito al final (CLIP-50)."""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from investigacion import aprendizaje, comun, medir_publicados as mp  # noqa: E402


def test_publicados_une_links_de_tiktok_y_videos_de_youtube(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    (d / "publicados.jsonl").write_text(
        json.dumps({"session_id": "s1", "clip_id": "c1", "plataforma": "tiktok", "url": "https://tt/1"}) + "\n" +
        json.dumps({"session_id": "s1", "clip_id": "c1", "plataforma": "tiktok", "url": "https://tt/2"}) + "\n",
        encoding="utf-8")
    base = tmp_path / "pub.db"
    c = sqlite3.connect(base)
    c.execute("create table publicaciones (plataforma, nicho, session_id, clip_id, estado, publish_id)")
    c.executemany("insert into publicaciones values (?,?,?,?,?,?)", [
        ("youtube", "n", "s1", "c1", "en_bandeja", "AAA"), ("youtube", "n", "s1", "c2", "en_cola", None),
        ("tiktok", "n", "s1", "c1", "en_bandeja", "v_inbox")])
    c.commit(); c.close()
    pubs = sorted(mp.publicados("n", base), key=lambda p: p["plataforma"])
    assert pubs == [{"plataforma": "tiktok", "clave": "s1/c1", "url": "https://tt/2"},
                    {"plataforma": "youtube", "clave": "s1/c1", "url": "https://www.youtube.com/shorts/AAA"}]


def test_aprendizaje_ultima_medicion_madura_y_outlier_por_tipo():
    filas = [
        {"plataforma": "tiktok", "clave": "a", "medido": "2026-11-01", "vistas": 10, "edad_dias": 5, "tipo": "x"},
        {"plataforma": "tiktok", "clave": "a", "medido": "2026-11-10", "vistas": 300, "edad_dias": 14, "tipo": "x"},
        {"plataforma": "tiktok", "clave": "b", "medido": "2026-11-10", "vistas": 100, "edad_dias": 9, "tipo": "y"},
        {"plataforma": "tiktok", "clave": "c", "medido": "2026-11-10", "vistas": 9999, "edad_dias": 1, "tipo": "z"},
    ]
    ult = aprendizaje.ultima_por_clip(filas, dias_min=3)
    assert sorted((f["clave"], f["vistas"]) for f in ult) == [("a", 300), ("b", 100)]   # c aún no madura
    tabla = aprendizaje.por_tipo(aprendizaje.con_outlier(ult))
    assert [(r["tipo"], r["mediana_outlier"]) for r in tabla] == [("x", 1.5), ("y", 0.5)]


def test_credito_de_medios_va_despues_de_los_hashtags():
    from app.publicacion.texto import texto_tiktok
    clip = {"publicacion": {"tiktok": {"descripcion": "Zeein le dice todo 👀\n\nFuente: Noticiero Kick",
                                       "hashtags": ["#fyp", "#parati"]}}}
    assert texto_tiktok(clip) == "Zeein le dice todo 👀 #fyp #parati\n\nFuente: Noticiero Kick"
    sin_credito = {"publicacion": {"tiktok": {"descripcion": "Hola", "hashtags": ["#fyp"]}}}
    assert texto_tiktok(sin_credito) == "Hola #fyp"
