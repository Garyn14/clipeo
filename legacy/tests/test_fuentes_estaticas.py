"""test_fuentes_estaticas.py — S14: fuentes estáticas por nicho (sin red)."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from investigacion import comun, fuentes_estaticas as fe

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <entry><yt:videoId>AAA</yt:videoId><title>Balean tienda en Los Olivos</title>
  <published>2026-11-17T10:00:00+00:00</published>
  <media:group><media:description>El local de Fritz Sport fue atacado</media:description></media:group></entry>
 <entry><yt:videoId>BBB</yt:videoId><title>Clima en Lima</title><published>2026-11-16T10:00:00+00:00</published>
  <media:group><media:description>Pronóstico</media:description></media:group></entry>
</feed>"""
AHORA = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def test_parsear_feed():
    v = fe.parsear_feed(FEED)
    assert [x["id"] for x in v] == ["AAA", "BBB"] and "Fritz Sport" in v[0]["descripcion"]
    assert v[0]["publicado"] == datetime(2026, 11, 17, 10, tzinfo=timezone.utc)


def test_channel_id():
    assert fe.channel_id("https://www.youtube.com/channel/UCcNnyGHnzZnzkjUvOOkKaRg") == "UCcNnyGHnzZnzkjUvOOkKaRg"
    assert fe.channel_id("https://www.youtube.com/@fritzsport") is None


def test_decidir_propio_medios_y_exclusion(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "ex.yaml"))
    palabras = ["fritz sport", "tio fritz"]
    nota = {"titulo": "Balean tienda", "descripcion": "El local de Fritz Sport"}
    assert fe.decidir(nota, {"rol": "medios", "nombre": "Latina"}, palabras) == ("nuevo", "menciona «fritz sport»")
    assert fe.decidir({"titulo": "Clima", "descripcion": ""}, {"rol": "medios", "nombre": "Latina"}, palabras)[0] == "descartado"
    assert fe.decidir({"titulo": "x", "descripcion": ""}, {"rol": "propio", "nombre": "FRITZ SPORT"}, palabras)[0] == "nuevo"
    (tmp_path / "ex.yaml").write_text("canales: [Latina]\npersonas: []\n", encoding="utf-8")
    assert fe.decidir(nota, {"rol": "medios", "nombre": "Latina"}, palabras)[0] == "descartado"


@pytest.fixture
def nicho(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    monkeypatch.setenv("CLIPEO_EXCLUSION", str(tmp_path / "ex.yaml"))
    monkeypatch.setattr(fe, "ids_ya_procesados", lambda sd: {"PROC"})
    d = comun.carpeta_nicho("n"); d.mkdir(parents=True)
    (d / "fuentes.yaml").write_text(
        "activo: true\nventana_inicial_dias: 7\npalabras_clave: [fritz sport]\ncanales:\n"
        "  - {nombre: Latina, url: 'https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx', rol: medios}\n"
        "  - {nombre: Propio, url: 'https://www.youtube.com/channel/UCyyyyyyyyyyyyyyyyyyyyyy', rol: propio}\n"
        "  - {nombre: Apagado, url: 'https://www.youtube.com/channel/UCzzzzzzzzzzzzzzzzzzzzzz', rol: propio, activo: false}\n",
        encoding="utf-8")
    return d


def _lector(canal):
    base = [{"id": "AAA", "titulo": "Balean tienda", "descripcion": "Fritz Sport", "publicado": AHORA - timedelta(days=1)},
            {"id": "BBB", "titulo": "Clima", "descripcion": "", "publicado": AHORA - timedelta(days=2)},
            {"id": "VIEJO", "titulo": "Fritz Sport 2021", "descripcion": "", "publicado": AHORA - timedelta(days=60)},
            {"id": "PROC", "titulo": "Fritz Sport ya hecho", "descripcion": "", "publicado": AHORA - timedelta(days=1)}]
    if canal["nombre"] == "Propio":
        return [{"id": "STREAM1", "titulo": "Remato todo", "descripcion": "", "publicado": AHORA - timedelta(days=3)}]
    return base


def test_ejecutar_ventana_dedup_filtro_e_historial(nicho):
    r = fe.ejecutar("n", lector=_lector, ahora=AHORA)
    assert {c["canal"]: (c["nuevos"], c["descartados"]) for c in r["canales"]} == {"Latina": (1, 1), "Propio": (1, 0)}
    assert sorted(c["id"] for c in fe.candidatos("n")) == ["AAA", "STREAM1"]       # VIEJO fuera de ventana, PROC ya hecho
    descartado = fe.estado_actual(fe.leer_historial("n"))["BBB"]
    assert descartado["estado"] == "descartado" and descartado["motivo"] == "no menciona al cliente"
    estado = json.loads((nicho / "fuentes_estado.json").read_text(encoding="utf-8"))
    assert len(estado) == 2                                                          # el canal apagado no se revisa
    r2 = fe.ejecutar("n", lector=_lector, ahora=AHORA + timedelta(hours=1))
    assert all(c["nuevos"] == 0 and c["descartados"] == 0 for c in r2["canales"])   # deduplicado


def test_ejecutar_ultimos_n_y_canal_caido(nicho):
    def lector(canal):
        if canal["nombre"] == "Propio":
            raise OSError("sin red")
        return _lector(canal)
    r = fe.ejecutar("n", ultimos=1, lector=lector, ahora=AHORA)
    por_canal = {c["canal"]: c for c in r["canales"]}
    assert por_canal["Latina"]["nuevos"] == 1 and "sin red" in por_canal["Propio"]["error"]


def test_nicho_inactivo(nicho):
    (nicho / "fuentes.yaml").write_text("activo: false\ncanales: []\n", encoding="utf-8")
    assert fe.ejecutar("n", lector=_lector, ahora=AHORA) == {"activo": False, "canales": []}
