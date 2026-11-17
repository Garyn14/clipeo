"""CLIP-24 — cobertura del detector (A1 → A2), repeticiones y export de casos de cobertura."""

import json

import pytest

from evaluacion import cobertura, evaluar, exportar_casos


def test_solape_y_encontrado():
    esp = {"inicio": "01:00", "fin": "01:40"}
    assert cobertura.solape(esp, {"inicio": "01:20", "fin": "02:00"}) == 0.5
    assert cobertura.solape(esp, {"inicio": "03:00", "fin": "04:00"}) == 0
    assert cobertura.encontrado(esp, [{"inicio": "00:50", "fin": "01:35"}])          # 35/40
    assert not cobertura.encontrado(esp, [{"inicio": "01:30", "fin": "02:00"}])      # 10/40


def _caso():
    return {
        "id": "c-1", "nicho": "zapatillas_peru", "transcripcion": "[00:00] hola",
        "esperados": [{"inicio": "01:00", "fin": "01:40", "clip_id": "a"},
                      {"inicio": "10:00", "fin": "10:30", "clip_id": "b"}],
        "descartados": [{"inicio": "20:00", "fin": "20:20", "clip_id": "c"}],
    }


def test_evaluar_caso_con_detector_simulado(monkeypatch):
    monkeypatch.setattr(cobertura, "detectar", lambda t, c: [
        {"inicio": "00:55", "fin": "01:45"}, {"inicio": "20:00", "fin": "20:20"}, {"inicio": "30:00", "fin": "30:30"}])
    r = cobertura.evaluar_caso(_caso(), config={})
    assert (r["esperados"], r["encontrados"], r["propuestos"], r["descartados_repropuestos"]) == (2, 1, 3, 1)
    assert r["no_encontrados"] == [{"inicio": "10:00", "fin": "10:30", "clip_id": "b"}]


def test_error_del_detector_no_detiene(monkeypatch):
    def falla(t, c):
        raise SystemExit(1)
    monkeypatch.setattr(cobertura, "detectar", falla)
    assert "error" in cobertura.evaluar_caso(_caso(), config={})


def test_detectar_usa_a1_y_a2_del_piloto(monkeypatch):
    from agentes import agent1_peak_detector as a1
    from agentes import agent2_range_refiner as a2
    vistos = {}

    def falso_a1(path, config):
        vistos["trans"] = open(path, encoding="utf-8").read()
        return [{"timestamp": "01:10"}]

    monkeypatch.setattr(a1, "run_agent", falso_a1)
    monkeypatch.setattr(a2, "run_agent", lambda p, c: [
        {"conservar": True, "inicio": "01:00", "fin": "01:30"}, {"conservar": False, "inicio": "05:00", "fin": "05:10"}])
    assert cobertura.detectar("[01:10] texto", {}) == [{"conservar": True, "inicio": "01:00", "fin": "01:30"}]
    assert vistos["trans"] == "[01:10] texto"


def test_resumir_variacion_e_inestables():
    c1 = {"resultados": [{"id": "x", "esperados": 2, "encontrados": 1, "propuestos": 4, "descartados_repropuestos": 0}]}
    c2 = {"resultados": [{"id": "x", "esperados": 2, "encontrados": 2, "propuestos": 6, "descartados_repropuestos": 1}]}
    for c in (c1, c2):
        c["resumen"] = cobertura.resumir(c["resultados"])
    assert c1["resumen"]["cobertura"] == 0.5 and c2["resumen"]["cobertura"] == 1.0
    assert cobertura.variacion([c1, c2], "cobertura") == {"media": 0.75, "min": 0.5, "max": 1.0}
    assert cobertura.inestables([c1, c2]) == ["x"]


def test_config_real_del_nicho_carga():
    config = cobertura.cargar_config("zapatillas_peru")
    assert config["deteccion"]["prompt"] and config["refinamiento"]["prompt"]


def test_evaluar_juez_con_repeticiones(monkeypatch, capsys):
    decisiones = iter([True, False, True, True, False, True])  # 3 casos x 2 corridas
    monkeypatch.setattr(evaluar, "evaluar_caso", lambda c: {
        "id": c["id"], "esperado_publicar": True, "obtenido_publicar": (o := next(decisiones)), "acierto": o,
        "tipo_obtenido": "x", "titulo": "t"})
    assert evaluar.main(["zapatillas_peru", "--solo-sinteticos", "--repeticiones", "2", "--no-guardar"]) == 0
    salida = capsys.readouterr().out
    assert "inestables" in salida and "zp-sint-002" in salida


def test_export_de_cobertura_desde_sesion_simulada(tmp_path, monkeypatch):
    from investigacion import comun
    raiz = tmp_path / "raiz"
    nicho = raiz / "investigacion" / "zapatillas_peru"
    nicho.mkdir(parents=True)
    (nicho / "correcciones.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"session_id": "S1", "clip_id": "clip_c001_01", "accion": "descartado", "juez": {}},
        {"session_id": "S1", "clip_id": "clip_c001_01", "accion": "aprobado", "juez": {}},   # la última manda
        {"session_id": "S1", "clip_id": "clip_c001_02", "accion": "descartado", "juez": {}},
    ]), encoding="utf-8")
    sesion = tmp_path / "stream_data" / "S1"
    (sesion / "contenido_chunks").mkdir(parents=True)
    (sesion / "chunks" / "chunk_001").mkdir(parents=True)
    (sesion / "contenido_chunks" / "chunk_001.json").write_text(json.dumps({"contenido": [
        {"clip_id": "clip_c001_01", "publicar": True, "inicio": "01:00", "fin": "01:30"},
        {"clip_id": "clip_c001_02", "revision_descartado": True, "inicio": "05:00", "fin": "05:20"},
    ]}))
    (sesion / "chunks" / "chunk_001" / "transcripcion_raw.txt").write_text("[00:00] uno\n[09:00] dos")
    monkeypatch.setattr(comun, "RAIZ", raiz)

    casos, avisos = exportar_casos.casos_de_cobertura("zapatillas_peru", tmp_path / "stream_data")
    assert len(casos) == 1 and not avisos
    assert casos[0]["esperados"] == [{"inicio": "01:00", "fin": "01:30", "clip_id": "clip_c001_01"}]
    assert casos[0]["descartados"][0]["clip_id"] == "clip_c001_02"
    assert "[09:00] dos" in casos[0]["transcripcion"]
    cobertura.validar(casos[0])
