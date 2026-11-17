"""CLIP-20 — formato de casos, exportador y evaluador del juez (IA simulada)."""

import json
from pathlib import Path

import pytest

from evaluacion import casos as casos_mod
from evaluacion import evaluar, exportar_casos


def _caso(**extra):
    base = {
        "id": "t-1", "nicho": "zapatillas_peru", "origen": "sintetico",
        "candidato": {"inicio": "00:05", "fin": "00:20"},
        "transcripcion": "[00:05] Fritz: hola\n[00:10] Señora: no me alcanza",
        "esperado": {"publicar": True},
    }
    base.update(extra)
    return base


def test_validar_rechaza_caso_incompleto():
    with pytest.raises(casos_mod.CasoInvalido):
        casos_mod.validar(_caso(esperado={}))
    with pytest.raises(casos_mod.CasoInvalido):
        casos_mod.validar(_caso(origen="correccion"))  # sin clave_correccion


def test_casos_sinteticos_del_repo_son_validos():
    casos = casos_mod.cargar(casos_mod.DIR_CASOS / "zapatillas_peru.sinteticos.yaml")
    assert len(casos) >= 3
    assert all(c["origen"] == "sintetico" for c in casos)


def test_guardar_y_cargar_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "x.yaml"
    casos_mod.guardar([_caso()], ruta)
    assert casos_mod.cargar(ruta)[0]["id"] == "t-1"


def test_ventana_de_transcripcion():
    texto = "\n".join(f"[{m:02d}:00] linea {m}" for m in range(10))
    v = exportar_casos.ventana(texto, "04:00", "05:00", margen=60)
    assert v.splitlines() == ["[03:00] linea 3", "[04:00] linea 4", "[05:00] linea 5", "[06:00] linea 6"]


class _Resp:
    def __init__(self, texto):
        self.content = [type("B", (), {"text": texto})()]


class _ClienteFalso:
    """Simula a Claude: publica si la transcripción menciona 'no me alcanza'; guarda los prompts."""

    def __init__(self):
        self.systems = []
        self.messages = self

    def create(self, **kw):
        self.systems.append(kw["system"])
        contenido = kw["messages"][0]["content"]
        publicar = "no me alcanza" in contenido
        return _Resp(json.dumps({"candidatos": [{
            "n": 1, "tipo": "generosidad_con_humilde" if publicar else "ninguno", "en_juego": "x",
            "parecidos": [], "publicar": publicar, "fuerza": 8 if publicar else 2,
            "linea1": "Fritz ayuda", "linea2": "a mamita 🥹", "por_que": "prueba"}]}))


@pytest.fixture
def cliente(monkeypatch):
    from agentes import juez
    falso = _ClienteFalso()
    monkeypatch.setattr(juez, "get_client", lambda: falso)
    return falso


def test_evaluar_caso_acierta_y_falla(cliente):
    ok = evaluar.evaluar_caso(_caso())
    assert ok["acierto"] is True and ok["obtenido_publicar"] is True
    malo = evaluar.evaluar_caso(_caso(id="t-2", transcripcion="[00:05] Fritz: envíos a todo el Perú",
                                      esperado={"publicar": True}))
    assert malo["acierto"] is False


def test_sin_filtracion_quita_la_correccion_del_caso(cliente):
    from investigacion import comun
    lineas = (comun.carpeta_nicho("zapatillas_peru") / "correcciones.jsonl").read_text(encoding="utf-8").splitlines()
    r = json.loads(lineas[0])
    clave = f"{r['session_id']}/{r['clip_id']}"
    titulo = (r.get("juez") or {}).get("linea1")
    assert titulo
    evaluar.evaluar_caso(_caso(origen="correccion", clave_correccion=clave))
    assert titulo not in cliente.systems[-1]
    evaluar.evaluar_caso(_caso(id="t-3"))  # otro caso: la corrección sí está en el prompt
    assert titulo in cliente.systems[-1]


def test_resumir_calcula_metricas():
    res = [
        {"esperado_publicar": True, "obtenido_publicar": True, "acierto": True, "acierto_tipo": True},
        {"esperado_publicar": False, "obtenido_publicar": True, "acierto": False},
        {"esperado_publicar": True, "obtenido_publicar": False, "acierto": False},
        {"esperado_publicar": False, "obtenido_publicar": False, "acierto": True},
        {"id": "x", "error": "falló"},
    ]
    r = evaluar.resumir(res)
    assert r["matriz"] == {"vp": 1, "fp": 1, "vn": 1, "fn": 1}
    assert r["acierto"] == 0.5 and r["precision"] == 0.5 and r["recall"] == 0.5
    assert r["errores"] == 1 and r["acierto_tipo"] == 1.0


def test_main_con_sinteticos_no_guarda(cliente, capsys):
    assert evaluar.main(["zapatillas_peru", "--solo-sinteticos", "--no-guardar"]) == 0
    assert "Acierto" in capsys.readouterr().out


def test_exportar_desde_sesion_simulada(tmp_path, monkeypatch):
    """El exportador arma casos desde una sesión con el formato real del piloto."""
    from investigacion import comun

    raiz = tmp_path / "raiz"
    nicho = raiz / "investigacion" / "zapatillas_peru"
    nicho.mkdir(parents=True)
    (nicho / "correcciones.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"session_id": "S1", "clip_id": "clip_c001_01", "accion": "aprobado",
         "juez": {"tipo": "generosidad_con_humilde", "linea1": "a"}},
        {"session_id": "S1", "clip_id": "clip_c001_02", "accion": "descartado", "razon": "aburrido", "juez": {}},
        {"session_id": "NOEXISTE", "clip_id": "clip_c001_01", "accion": "aprobado", "juez": {}},
    ]), encoding="utf-8")
    sesion = tmp_path / "stream_data" / "S1"
    (sesion / "contenido_chunks").mkdir(parents=True)
    (sesion / "chunks" / "chunk_001").mkdir(parents=True)
    (sesion / "metadata.json").write_text(json.dumps({"title": "Live", "uploader": "Fritz Sport"}))
    (sesion / "contenido_chunks" / "chunk_001.json").write_text(json.dumps({"contenido": [
        {"clip_id": "clip_c001_01", "publicar": True, "inicio": "01:00", "fin": "01:30"},
        {"clip_id": "clip_c001_02", "publicar": False, "revision_descartado": True, "inicio": "05:00", "fin": "05:20"},
    ]}))
    (sesion / "chunks" / "chunk_001" / "transcripcion_enriquecida.txt").write_text(
        "\n".join(f"[{m:02d}:{s:02d}] texto {m}:{s}" for m in range(7) for s in (0, 30)), encoding="utf-8")
    monkeypatch.setattr(comun, "RAIZ", raiz)

    casos, avisos = exportar_casos.casos_de_correcciones("zapatillas_peru", tmp_path / "stream_data")
    assert [c["esperado"]["publicar"] for c in casos] == [True, False]
    assert casos[0]["esperado"]["tipo"] == "generosidad_con_humilde"
    assert casos[0]["video"]["canal"] == "Fritz Sport"
    assert "[01:00]" in casos[0]["transcripcion"] and "[03:00]" not in casos[0]["transcripcion"]
    assert any("NOEXISTE" in a for a in avisos)
    for c in casos:
        casos_mod.validar(c)


def test_salida_en_utf8_para_la_consola_de_windows():
    import importlib
    import io
    import sys

    from evaluacion import _legacy
    viejo = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    try:
        importlib.reload(_legacy)
        print("⚠ ✅")          # con cp1252 esto lanzaba UnicodeEncodeError
        assert sys.stdout.encoding.lower() == "utf-8"
    finally:
        sys.stdout = viejo


def test_exportar_con_origen_lee_datos_locales_y_correcciones_del_repo(tmp_path, capsys):
    """--origen: stream_data y muestra/ desde la carpeta local; correcciones y muestra.jsonl desde el repo."""
    origen = tmp_path / "anterior"
    (origen / "stream_data").mkdir(parents=True)
    exportar_casos.main(["zapatillas_peru", "--origen", str(origen)])
    salida = capsys.readouterr().out
    assert str(origen / "stream_data") in salida
    assert str(origen / "investigacion" / "zapatillas_peru" / "muestra") in salida
    assert "sin " not in salida.split("correcciones.jsonl")[0][-40:]   # las correcciones sí se encontraron
    assert "no está en" in salida                                     # pero sus sesiones no están en el origen


def test_rango_de_acepta_rango_original():
    assert exportar_casos._rango_de({"rango_original": {"inicio": "01:00", "fin": "01:30"}}) == ("01:00", "01:30")
    assert exportar_casos._rango_de({"inicio": "02:00", "fin": "02:10", "rango_original": {"inicio": "x", "fin": "y"}}) == ("02:00", "02:10")
    assert exportar_casos._rango_de({"rango_original": None}) == (None, None)


def test_analizar_por_caso_usa_mayoria():
    from evaluacion import analizar
    base = {"esperado_publicar": True, "origen": "muestra", "tipo_obtenido": "x"}
    datos = {"corridas": [
        {"resultados": [dict(base, id="a", obtenido_publicar=True), dict(base, id="b", obtenido_publicar=False)]},
        {"resultados": [dict(base, id="a", obtenido_publicar=True), dict(base, id="b", obtenido_publicar=True)]},
        {"resultados": [dict(base, id="a", obtenido_publicar=False), {"id": "b", "error": "x"}]},
    ]}
    filas = {r["id"]: r for r in analizar.por_caso(datos)}
    assert filas["a"]["obtenido_publicar"] is True and filas["a"]["fraccion_publicar"] == 0.67
    assert filas["b"]["obtenido_publicar"] is False and filas["b"]["corridas"] == 2   # empate → no publica
