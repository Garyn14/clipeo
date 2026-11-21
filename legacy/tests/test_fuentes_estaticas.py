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
    r = fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA)
    assert {c["canal"]: (c["nuevos"], c["descartados"]) for c in r["canales"]} == {"Latina": (1, 1), "Propio": (1, 0)}
    assert sorted(c["id"] for c in fe.candidatos("n")) == ["AAA", "STREAM1"]       # VIEJO fuera de ventana, PROC ya hecho
    descartado = fe.estado_actual(fe.leer_historial("n"))["BBB"]
    assert descartado["estado"] == "descartado" and descartado["motivo"] == "no menciona al cliente"
    estado = json.loads((nicho / "fuentes_estado.json").read_text(encoding="utf-8"))
    assert len(estado) == 2                                                          # el canal apagado no se revisa
    filas = len(fe.leer_historial("n"))
    r2 = fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA + timedelta(hours=1))
    assert sorted(c["id"] for c in fe.candidatos("n")) == ["AAA", "STREAM1"]       # CLIP-71: lo no procesado sigue
    assert {c["canal"]: c["nuevos"] for c in r2["canales"]} == {"Latina": 1, "Propio": 1}
    assert len(fe.leer_historial("n")) == filas                                      # sin cambios no se duplica


# ── CLIP-71: candidatos dinámicos ────────────────────────────

def _lector_hasta(ahora):
    """Un video del canal propio por día (D20 el 20, D21 el 21), tal como se vería en `ahora`."""
    def lector(canal):
        if canal["nombre"] != "Propio":
            return []
        videos = [{"id": "D20", "titulo": "Stream del 20", "descripcion": "",
                   "publicado": datetime(2026, 11, 20, 15, tzinfo=timezone.utc)},
                  {"id": "D21", "titulo": "Stream del 21", "descripcion": "",
                   "publicado": datetime(2026, 11, 21, 15, tzinfo=timezone.utc)}]
        return [v for v in videos if v["publicado"] <= ahora]
    return lector


def _buscar(dia, hora=20, **kw):
    ahora = datetime(2026, 11, dia, hora, tzinfo=timezone.utc)
    return fe.ejecutar("n", lector=_lector_hasta(ahora), ahora=ahora, **kw)


def test_ultimo_dia_dos_dias_seguidos_y_aviso_de_anteriores(nicho):
    r = _buscar(20)
    assert r["dias"] == 1                                                            # rango por defecto: último día
    assert [c["id"] for c in fe.candidatos("n")] == ["D20"]
    _buscar(21)
    assert [c["id"] for c in fe.candidatos("n")] == ["D21"]                          # solo lo del último día
    assert [c["id"] for c in fe.anteriores("n")] == ["D20"]                          # lo de ayer: al aviso plegado
    busqueda = fe.ultima_busqueda("n")
    assert busqueda["dias"] == 1 and busqueda["ids"] == ["D21"]


def test_no_procesado_reaparece_y_procesado_nunca(nicho):
    _buscar(21)
    assert [c["id"] for c in fe.candidatos("n")] == ["D21"]
    fe._guardar_historial("n", fe.leer_historial("n") + [{"id": "D21", "estado": "procesado", "sesion": "s"}])
    _buscar(21, hora=21, dias=3)
    assert [c["id"] for c in fe.candidatos("n")] == ["D20"]                          # D20 vuelve; D21 procesado no
    assert fe.anteriores("n") == []


def test_descartado_por_filtro_se_reevalua(nicho):
    fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA)
    assert fe.estado_actual(fe.leer_historial("n"))["BBB"]["estado"] == "descartado"
    (nicho / "fuentes.yaml").write_text((nicho / "fuentes.yaml").read_text(encoding="utf-8")
                                        .replace("[fritz sport]", "[fritz sport, clima]"), encoding="utf-8")
    fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA)
    assert "BBB" in {c["id"] for c in fe.candidatos("n")}                            # ahora menciona una palabra clave


def test_canal_quitado_no_aporta_candidatos(nicho):
    fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA)
    assert "STREAM1" in {c["id"] for c in fe.candidatos("n")}
    (nicho / "fuentes.yaml").write_text((nicho / "fuentes.yaml").read_text(encoding="utf-8")
                                        .replace("  - {nombre: Propio", "  - {activo: false, nombre: Propio"),
                                        encoding="utf-8")
    assert "STREAM1" not in {c["id"] for c in fe.candidatos("n")}                    # sin buscar de nuevo ya no se ve
    assert "STREAM1" in {c["id"] for c in fe.anteriores("n")}                        # pero no se pierde


def test_descartar_por_el_operador_no_vuelve(nicho):
    fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA)
    assert fe.descartar("n", ["AAA", "NOEXISTE", "AAA"]) == ["AAA"]
    fe.ejecutar("n", dias=7, lector=_lector, ahora=AHORA + timedelta(hours=1))
    assert "AAA" not in {c["id"] for c in fe.candidatos("n") + fe.anteriores("n")}
    assert fe.estado_actual(fe.leer_historial("n"))["AAA"]["por"] == "operador"


def test_sin_busqueda_previa_todo_pendiente_va_al_aviso(nicho):
    """Al desplegar CLIP-71 no hay fuentes_busqueda.json: lo acumulado queda en «anteriores», no en la lista."""
    fe._guardar_historial("n", [{"id": "X1", "titulo": "Viejo", "canal": "Propio", "rol": "propio", "estado": "nuevo"},
                                {"id": "M1", "titulo": "Manual", "canal": "Otro", "rol": "medios", "estado": "nuevo",
                                 "motivo": "agregado a mano"}])
    assert [c["id"] for c in fe.candidatos("n")] == ["M1"]                           # los links a mano siguen
    assert [c["id"] for c in fe.anteriores("n")] == ["X1"]


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
