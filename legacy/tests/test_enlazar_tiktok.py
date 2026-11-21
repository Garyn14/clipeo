"""test_enlazar_tiktok.py — CLIP-69: enlace automático de videos de TikTok con sus clips (sin red ni ffprobe)."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from investigacion import comun, enlazar_tiktok as et

T0 = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)


def _video(i, dur, minutos):
    return {"id": f"V{i}", "url": f"https://www.tiktok.com/@x/video/V{i}", "duracion": dur,
            "publicado": T0 + timedelta(minutes=minutos)}


def _borrador(clip, dur, minutos, sid="S1"):
    return {"session_id": sid, "clip_id": clip, "duracion": dur, "enviada": T0 + timedelta(minutes=minutos)}


def test_emparejar_por_duracion_y_orden():
    videos = [_video(1, 66.0, 30), _video(2, 20.4, 90), _video(3, 35.0, 60), _video(4, 50.0, 100)]
    pend = [_borrador("c3", 66.0, 0), _borrador("c5", 20.0, 80), _borrador("c2", 35.0, 0),
            _borrador("c2b", 35.0, -600, sid="S0"), _borrador("c9", 50.0, 120)]
    enlaces, ambiguos = et.emparejar(videos, pend)
    assert {(v["id"], b["clip_id"]) for v, b in enlaces} == {("V1", "c3"), ("V2", "c5")}
    assert len(ambiguos) == 1 and ambiguos[0]["video"]["id"] == "V3"          # dos borradores de 35 s: no adivina
    # V4 no se enlaza: su borrador se envió DESPUÉS de publicado


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    comun.carpeta_nicho("n").mkdir(parents=True)
    monkeypatch.setattr(et, "perfil", lambda nicho: "@x")
    base = tmp_path / "pub.db"
    conn = sqlite3.connect(base)
    conn.execute("CREATE TABLE publicaciones (plataforma, nicho, estado, session_id, clip_id, enviada_en, ruta_video)")
    conn.executemany("INSERT INTO publicaciones VALUES ('tiktok','n','en_bandeja',?,?,?,?)", [
        ("S1", "c3", (T0).isoformat(), "c3.mp4"), ("S1", "c5", (T0 + timedelta(minutes=80)).isoformat(), "c5.mp4")])
    conn.commit(); conn.close()
    duraciones = {"c3.mp4": 66.0, "c5.mp4": 20.0}
    return base, (lambda ruta: duraciones.get(ruta))


def test_enlazar_registra_sin_duplicar(entorno):
    base, dur = entorno
    lector = lambda h: [_video(1, 66.0, 30), _video(2, 20.0, 90)]
    r = et.enlazar("n", lector=lector, base=base, duracion=dur)
    assert [e["clip_id"] for e in r["enlazados"]] == ["c3", "c5"] and r["error"] is None
    filas = [json.loads(l) for l in (comun.carpeta_nicho("n") / "publicados.jsonl").read_text(encoding="utf-8").splitlines()]
    assert filas[0]["video_id"] == "V1" and filas[0]["origen"] == "automatico"
    assert et.enlazar("n", lector=lector, base=base, duracion=dur)["enlazados"] == []     # segunda vez: nada nuevo


def test_no_pisa_link_pegado_a_mano_y_simular(entorno):
    base, dur = entorno
    comun.registrar_publicado("n", {"session_id": "S1", "clip_id": "c3", "plataforma": "tiktok",
                                    "video_id": "MANUAL", "url": "https://www.tiktok.com/@x/video/MANUAL"})
    lector = lambda h: [_video(1, 66.0, 30), _video(2, 20.0, 90)]
    r = et.enlazar("n", simular=True, lector=lector, base=base, duracion=dur)
    assert [e["clip_id"] for e in r["enlazados"]] == ["c5"]                               # c3 ya tenía link a mano
    assert len((comun.carpeta_nicho("n") / "publicados.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_perfil_caido_no_rompe(entorno):
    base, dur = entorno

    def lector(h):
        raise RuntimeError("captcha")
    r = et.enlazar("n", lector=lector, base=base, duracion=dur)
    assert "no se pudo leer" in r["error"] and r["enlazados"] == []
