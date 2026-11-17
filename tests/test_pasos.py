"""
test_pasos.py — Tests de core/pasos.py (motor de pasos), core/chunk_manager.py (estado por
pasos, reset, retrocompatibilidad) y core/clip_ids.py (nombres de clip).

Sin red ni Claude: las funciones de paso son lambdas que fallan o devuelven a demanda, y
time.sleep se reemplaza para que los reintentos no esperen.
"""

import json

import pytest

import core.pasos as pasos_module
from ai_client import AIFatalError, AIRetryableError
from core.chunk_manager import PASOS_CHUNK, ChunkManager
from core.clip_ids import asignar_clip_ids, prefijo_chunk
from core.pasos import ErrorPaso, PasoFallido, Subpasos, clasificar_error, ejecutar_paso


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr(pasos_module.time, "sleep", lambda s: None)
    monkeypatch.setenv("PIPELINE_ESPERAS_REINTENTO", "1,1,1")
    m = ChunkManager(tmp_path, duracion_total=3700, chunk_minutos=30)
    m.iniciar(url="https://x", config="test")
    m.crear_plan(url="https://x", config="test")
    return m


def _leer_estado(m: ChunkManager) -> dict:
    return json.loads(m.estado_path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────
#  ejecutar_paso
# ─────────────────────────────────────────

def test_paso_ok_guarda_estado_y_salidas(mgr, tmp_path):
    salida = tmp_path / "chunks" / "chunk_001" / "picos.json"
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: {"salidas": [salida], "nota": "3 picos"})

    paso = _leer_estado(mgr)["chunks"]["chunk_001"]["pasos"]["agente1"]
    assert paso["estado"] == "ok"
    assert paso["intentos"] == 1
    assert paso["nota"] == "3 picos"
    assert paso["salidas"] == ["chunks/chunk_001/picos.json"]  # relativa a la sesión


def test_paso_terminado_se_salta(mgr):
    llamadas = []
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: llamadas.append(1))
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: llamadas.append(1))
    assert llamadas == [1]


def test_paso_omitido_cuenta_como_terminado(mgr):
    ejecutar_paso(mgr, "chunk_001", "agente0", lambda: {"omitido": True, "nota": "sin speakers"})
    assert mgr.paso("chunk_001", "agente0")["estado"] == "omitido"


def test_reintentable_se_reintenta_hasta_tener_exito(mgr):
    intentos = []

    def fn():
        intentos.append(1)
        if len(intentos) < 3:
            raise AIRetryableError("límite de uso")
        return {"nota": "ok al 3er intento"}

    ejecutar_paso(mgr, "chunk_001", "agente1", fn)
    paso = mgr.paso("chunk_001", "agente1")
    assert paso["estado"] == "ok"
    assert paso["intentos"] == 3
    assert paso["error"] is None


def test_reintentable_agota_reintentos_y_queda_en_error(mgr):
    intentos = []

    def fn():
        intentos.append(1)
        raise AIRetryableError("límite de uso")

    with pytest.raises(PasoFallido):
        ejecutar_paso(mgr, "chunk_001", "agente1", fn)

    assert len(intentos) == 4  # 1 + 3 reintentos
    paso = _leer_estado(mgr)["chunks"]["chunk_001"]["pasos"]["agente1"]
    assert paso["estado"] == "error"
    assert paso["error"]["reintentable"] is True
    assert _leer_estado(mgr)["chunks"]["chunk_001"]["estado"] == "fallido"


def test_no_reintentable_falla_sin_reintentar(mgr):
    intentos = []

    def fn():
        intentos.append(1)
        raise AIFatalError("sesión no iniciada")

    with pytest.raises(PasoFallido) as exc:
        ejecutar_paso(mgr, "chunk_001", "agente1", fn)

    assert len(intentos) == 1
    assert exc.value.error["reintentable"] is False
    assert exc.value.error["tipo"] == "AIFatalError"


def test_sys_exit_de_un_agente_es_error_no_reintentable(mgr):
    def fn():
        raise SystemExit(1)

    with pytest.raises(PasoFallido) as exc:
        ejecutar_paso(mgr, "chunk_001", "agente2", fn)
    assert exc.value.error["tipo"] == "EntradaFaltante"


def test_keyboard_interrupt_deja_el_paso_pendiente(mgr):
    def fn():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ejecutar_paso(mgr, "chunk_001", "agente1", fn)
    assert mgr.paso("chunk_001", "agente1")["estado"] == "pendiente"


def test_trace_dir_se_expone_y_se_restaura(mgr, tmp_path, monkeypatch):
    monkeypatch.delenv("PIPELINE_TRACE_DIR", raising=False)
    visto = {}
    trace = tmp_path / "trazas" / "agente1"

    def fn():
        import os
        visto["dir"] = os.environ.get("PIPELINE_TRACE_DIR")

    ejecutar_paso(mgr, "chunk_001", "agente1", fn, trace_dir=trace)
    import os
    assert visto["dir"] == str(trace)
    assert "PIPELINE_TRACE_DIR" not in os.environ


@pytest.mark.parametrize("exc,reintentable", [
    (AIRetryableError("x"), True),
    (AIFatalError("x"), False),
    (ErrorPaso("x", reintentable=True), True),
    (KeyError("deteccion"), False),
    (FileNotFoundError("x"), False),
    (RuntimeError("desconocido"), True),
])
def test_clasificar_error(exc, reintentable):
    assert clasificar_error(exc)[0] is reintentable


# ─────────────────────────────────────────
#  ChunkManager — estado derivado, reset, retrocompat
# ─────────────────────────────────────────

def test_chunk_completado_cuando_todos_sus_pasos_terminan(mgr):
    for p in PASOS_CHUNK:
        ejecutar_paso(mgr, "chunk_001", p, lambda: None)
    assert _leer_estado(mgr)["chunks"]["chunk_001"]["estado"] == "completado"


def test_get_pendientes_excluye_completados_y_con_error(mgr):
    for p in PASOS_CHUNK:
        ejecutar_paso(mgr, "chunk_001", p, lambda: None)
    with pytest.raises(PasoFallido):
        ejecutar_paso(mgr, "chunk_002", "agente1", lambda: (_ for _ in ()).throw(AIFatalError("x")))
    assert [c["id"] for c in mgr.get_pendientes()] == ["chunk_003"]


def test_resetear_desde_vuelve_pendientes_y_devuelve_salidas(mgr):
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: {"salidas": [mgr.session_dir / "a.json"]})
    ejecutar_paso(mgr, "chunk_001", "agente2", lambda: {"salidas": [mgr.session_dir / "b.json"]})
    mgr.actualizar_paso(None, "revision", estado="esperando")

    salidas = mgr.resetear_desde("agente1", "chunk_001")

    assert sorted(salidas) == ["a.json", "b.json"]
    pasos = _leer_estado(mgr)["chunks"]["chunk_001"]["pasos"]
    assert pasos["agente1"]["estado"] == "pendiente"
    assert pasos["agente2"]["estado"] == "pendiente"
    # reabrir un chunk reabre la revisión de la sesión
    assert mgr.paso(None, "revision")["estado"] == "pendiente"


def test_resetear_sin_chunk_toma_los_chunks_con_ese_paso_en_error(mgr):
    with pytest.raises(PasoFallido):
        ejecutar_paso(mgr, "chunk_002", "transcripcion",
                      lambda: (_ for _ in ()).throw(AIFatalError("x")))
    ejecutar_paso(mgr, "chunk_001", "transcripcion", lambda: None)

    mgr.resetear_desde("transcripcion")

    assert mgr.paso("chunk_002", "transcripcion")["estado"] == "pendiente"
    assert mgr.paso("chunk_001", "transcripcion")["estado"] == "ok"  # no estaba en error


def test_crear_plan_conserva_pasos_de_sesion(tmp_path):
    m = ChunkManager(tmp_path)
    m.iniciar(url="u", config="c")
    m.actualizar_paso(None, "descarga", estado="ok", nota="video.mp4")
    m.duracion_total = 100
    m.crear_plan(url="u", config="c")
    assert m.paso(None, "descarga")["nota"] == "video.mp4"
    assert list(m._estado["chunks"]) == ["chunk_001"]


def test_estado_previo_sin_pasos_se_lee_con_pasos_pendientes(tmp_path):
    (tmp_path / "pipeline_estado.json").write_text(json.dumps({
        "url": "u", "config": "c",
        "chunks": {
            "chunk_001": {"inicio_segundos": 0, "fin_segundos": 1800, "inicio_ts": "00:00:00",
                          "fin_ts": "00:30:00", "estado": "completado"},
            "chunk_002": {"inicio_segundos": 1800, "fin_segundos": 2000, "inicio_ts": "00:30:00",
                          "fin_ts": "00:33:20", "estado": "fallido", "error": "viejo"},
        },
    }), encoding="utf-8")

    m = ChunkManager(tmp_path)
    m.cargar_estado()

    assert m.paso(None, "descarga")["estado"] == "pendiente"
    assert set(m._estado["chunks"]["chunk_001"]["pasos"]) == set(PASOS_CHUNK)
    # el completado viejo no se reprocesa; el fallido viejo sí (no tiene pasos en error)
    assert [c["id"] for c in m.get_pendientes()] == ["chunk_002"]


def test_chunk_cortado_antes_del_juez_recibe_juez_omitido(tmp_path):
    m = ChunkManager(tmp_path, duracion_total=100)
    m.iniciar(url="u", config="c")
    m.crear_plan(url="u", config="c")
    for p in PASOS_CHUNK:
        if p != "juez":
            m.actualizar_paso("chunk_001", p, estado="ok")
    estado = _leer_estado(m)
    del estado["chunks"]["chunk_001"]["pasos"]["juez"]
    estado["chunks"]["chunk_001"]["estado"] = "completado"
    m.estado_path.write_text(json.dumps(estado), encoding="utf-8")

    m.cargar_estado()

    juez = m.paso("chunk_001", "juez")
    assert juez["estado"] == "omitido"
    assert juez["nota"] == "sesión previa al juez"
    assert m.get_pendientes() == []  # no se reprocesa


def test_chunk_a_medias_sin_juez_lo_corre_al_reanudar(tmp_path):
    m = ChunkManager(tmp_path, duracion_total=100)
    m.iniciar(url="u", config="c")
    m.crear_plan(url="u", config="c")
    m.actualizar_paso("chunk_001", "agente3", estado="ok")
    estado = _leer_estado(m)
    del estado["chunks"]["chunk_001"]["pasos"]["juez"]
    m.estado_path.write_text(json.dumps(estado), encoding="utf-8")

    m.cargar_estado()

    assert m.paso("chunk_001", "juez")["estado"] == "pendiente"


def test_orden_buscar_amplio_decidir_estricto():
    # A2 da los bordes, el juez decide y recién después el A3 escribe el copy
    assert PASOS_CHUNK.index("agente2") < PASOS_CHUNK.index("juez") < PASOS_CHUNK.index("agente3") \
        < PASOS_CHUNK.index("corte")


def test_reintentar_desde_juez_resetea_copy_y_corte(mgr):
    for p in ("agente2", "juez", "agente3", "corte"):
        ejecutar_paso(mgr, "chunk_001", p, lambda: None)

    mgr.resetear_desde("juez", "chunk_001")

    assert mgr.paso("chunk_001", "agente2")["estado"] == "ok"
    assert [mgr.paso("chunk_001", p)["estado"] for p in ("juez", "agente3", "corte")] == ["pendiente"] * 3


def test_reemplazo_reintenta_si_windows_bloquea_el_archivo(tmp_path, monkeypatch):
    import core.chunk_manager as cm
    monkeypatch.setattr(cm.time, "sleep", lambda s: None)
    tmp, destino = tmp_path / "e.json.tmp", tmp_path / "e.json"
    tmp.write_text("nuevo", encoding="utf-8")
    original = type(tmp).replace
    fallos = {"n": 2}

    def replace_con_bloqueo(self, target):
        if fallos["n"]:
            fallos["n"] -= 1
            raise PermissionError(13, "Acceso denegado")
        return original(self, target)

    monkeypatch.setattr(type(tmp), "replace", replace_con_bloqueo)
    cm.reemplazar_con_reintentos(tmp, destino)
    assert destino.read_text(encoding="utf-8") == "nuevo"


def test_progreso_que_no_se_puede_guardar_no_tumba_el_paso(mgr, monkeypatch):
    sub = Subpasos(mgr, None, "descarga", DEF_SUB)
    monkeypatch.setattr(pasos_module.time, "time", lambda: 10_000.0)  # fuerza escritura
    monkeypatch.setattr(mgr, "actualizar_paso", lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "x")))
    sub.progreso("video", pct=50.0)  # no lanza
    assert sub._por_id["video"]["progreso"]["pct"] == 50.0


def test_paso_viejo_sin_historial_se_completa(tmp_path):
    m = ChunkManager(tmp_path, duracion_total=100)
    m.iniciar(url="u", config="c")
    m.crear_plan(url="u", config="c")
    estado = _leer_estado(m)
    del estado["chunks"]["chunk_001"]["pasos"]["agente1"]["historial"]
    m.estado_path.write_text(json.dumps(estado), encoding="utf-8")

    m.cargar_estado()

    assert m.paso("chunk_001", "agente1")["historial"] == []


# ─────────────────────────────────────────
#  historial de intentos
# ─────────────────────────────────────────

def _intentos(paso: dict) -> list[dict]:
    return [ev for ev in paso["historial"] if ev["tipo"] == "intento"]


def test_historial_un_intento_ok(mgr):
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: None)

    hist = _leer_estado(mgr)["chunks"]["chunk_001"]["pasos"]["agente1"]["historial"]
    assert len(hist) == 1
    assert hist[0]["tipo"] == "intento"
    assert hist[0]["n"] == 1
    assert hist[0]["origen"] == "inicial"
    assert hist[0]["resultado"] == "ok"
    assert hist[0]["espera_previa_s"] is None
    assert hist[0]["fin"] is not None


def test_historial_registra_cada_reintento_automatico(mgr, monkeypatch):
    monkeypatch.setenv("PIPELINE_ESPERAS_REINTENTO", "30,120,300")
    fallos = iter([AIRetryableError("límite"), AIRetryableError("límite")])

    def fn():
        e = next(fallos, None)
        if e:
            raise e

    ejecutar_paso(mgr, "chunk_001", "agente1", fn)

    paso = _leer_estado(mgr)["chunks"]["chunk_001"]["pasos"]["agente1"]
    intentos = _intentos(paso)
    assert paso["intentos"] == 3
    assert [i["origen"] for i in intentos] == ["inicial", "automatico", "automatico"]
    assert [i["espera_previa_s"] for i in intentos] == [None, 30, 120]
    assert [i["resultado"] for i in intentos] == ["error", "error", "ok"]
    assert intentos[0]["error"]["tipo"] == "AIRetryableError"
    assert "detalle" not in intentos[0]["error"]  # el traceback solo va en paso.error


def test_historial_no_reintentable_un_solo_intento(mgr):
    with pytest.raises(PasoFallido):
        ejecutar_paso(mgr, "chunk_001", "agente1", lambda: (_ for _ in ()).throw(AIFatalError("x")))

    intentos = _intentos(mgr.paso("chunk_001", "agente1"))
    assert len(intentos) == 1
    assert intentos[0]["resultado"] == "error"
    assert intentos[0]["error"]["reintentable"] is False


def test_reset_conserva_historial_y_el_siguiente_intento_es_relanzado(mgr):
    with pytest.raises(PasoFallido):
        ejecutar_paso(mgr, "chunk_001", "transcripcion",
                      lambda: (_ for _ in ()).throw(AIFatalError("url vieja")))
    ejecutar_paso(mgr, "chunk_001", "agente0", lambda: None)  # paso posterior con historia previa

    mgr.resetear_desde("transcripcion", "chunk_001")

    trans = mgr.paso("chunk_001", "transcripcion")
    assert trans["estado"] == "pendiente"
    assert trans["intentos"] == 1
    assert [ev["tipo"] for ev in trans["historial"]] == ["intento", "reinicio"]
    assert trans["historial"][-1]["desde"] == "transcripcion"
    # los pasos siguientes también registran el reinicio en cascada
    assert mgr.paso("chunk_001", "agente0")["historial"][-1]["tipo"] == "reinicio"
    # un paso sin historia no acumula eventos de reinicio vacíos
    assert mgr.paso("chunk_001", "corte")["historial"] == []

    ejecutar_paso(mgr, "chunk_001", "transcripcion", lambda: None)

    trans = mgr.paso("chunk_001", "transcripcion")
    assert trans["intentos"] == 2
    assert trans["historial"][-1]["origen"] == "relanzado"
    assert trans["historial"][-1]["n"] == 2


def test_trazas_se_conservan_y_cada_intento_apunta_a_las_suyas(mgr, tmp_path):
    trace_dir = tmp_path / "trazas" / "agente1"
    trace_dir.mkdir(parents=True)

    def llamar(n_llamadas, falla):
        def fn():
            base = len(list(trace_dir.glob("*_request.json")))
            for i in range(n_llamadas):
                (trace_dir / f"{base + i + 1:03d}_request.json").write_text("{}", encoding="utf-8")
            if falla:
                raise AIFatalError("x")
        return fn

    with pytest.raises(PasoFallido):
        ejecutar_paso(mgr, "chunk_001", "agente1", llamar(2, True), trace_dir=trace_dir)
    mgr.resetear_desde("agente1", "chunk_001")
    ejecutar_paso(mgr, "chunk_001", "agente1", llamar(1, False), trace_dir=trace_dir)

    assert len(list(trace_dir.glob("*_request.json"))) == 3  # no se borraron
    intentos = _intentos(mgr.paso("chunk_001", "agente1"))
    assert [i["llamadas"] for i in intentos] == [[1, 2], [3, 3]]


def test_intento_sin_llamadas_tiene_llamadas_none(mgr, tmp_path):
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: None, trace_dir=tmp_path / "trazas" / "a1")
    assert _intentos(mgr.paso("chunk_001", "agente1"))[0]["llamadas"] is None


# ─────────────────────────────────────────
#  Subpasos
# ─────────────────────────────────────────

DEF_SUB = [("metadata", "Información"), ("video", "Video")]


def test_subpasos_inician_pendientes(mgr):
    Subpasos(mgr, None, "descarga", DEF_SUB)
    subs = _leer_estado(mgr)["pasos"]["descarga"]["subpasos"]
    assert [(s["id"], s["estado"]) for s in subs] == [("metadata", "pendiente"), ("video", "pendiente")]


def test_subpaso_ok_y_error(mgr):
    sub = Subpasos(mgr, None, "descarga", DEF_SUB)
    with sub.paso("metadata"):
        sub.detalle("metadata", "Título")
    with pytest.raises(RuntimeError):
        with sub.paso("video"):
            raise RuntimeError("403")

    subs = {s["id"]: s for s in _leer_estado(mgr)["pasos"]["descarga"]["subpasos"]}
    assert subs["metadata"]["estado"] == "ok"
    assert subs["metadata"]["detalle"] == "Título"
    assert subs["video"]["estado"] == "error"


def test_subpasos_progreso_con_throttle(mgr, monkeypatch):
    reloj = {"t": 1000.0}
    monkeypatch.setattr(pasos_module.time, "time", lambda: reloj["t"])
    sub = Subpasos(mgr, None, "descarga", DEF_SUB)
    escrituras = []
    original = mgr.actualizar_paso
    monkeypatch.setattr(mgr, "actualizar_paso", lambda *a, **k: escrituras.append(1) or original(*a, **k))

    with sub.paso("video"):  # 1 escritura
        sub.progreso("video", pct=10.0, pista=1)  # cambia de pista → escribe
        sub.progreso("video", pct=11.0, pista=1)  # mismo segundo → no escribe
        reloj["t"] += 1.5
        sub.progreso("video", pct=40.0, pista=1)  # pasó 1 s → escribe
        assert mgr.paso(None, "descarga")["subpasos"][1]["progreso"]["pct"] == 40.0
    # al terminar: escribe y deja el porcentaje en 100
    assert len(escrituras) == 4
    assert mgr.paso(None, "descarga")["subpasos"][1]["progreso"]["pct"] == 100.0


def test_subpasos_se_reinician_en_cada_intento(mgr):
    intentos = {"n": 0}

    def fn():
        intentos["n"] += 1
        sub = Subpasos(mgr, None, "descarga", DEF_SUB)
        with sub.paso("metadata"):
            pass
        with sub.paso("video"):
            if intentos["n"] == 1:
                raise AIRetryableError("corte")

    ejecutar_paso(mgr, None, "descarga", fn)

    subs = mgr.paso(None, "descarga")["subpasos"]
    assert [s["estado"] for s in subs] == ["ok", "ok"]


def test_actualizar_sesion_sobrevive_al_plan(tmp_path):
    m = ChunkManager(tmp_path, duracion_total=100)
    m.iniciar(url="u", config="c")
    m.actualizar_sesion(video={"titulo": "T"})
    m.crear_plan(url="u", config="c")
    assert _leer_estado(m)["video"] == {"titulo": "T"}


# ─────────────────────────────────────────
#  clip_ids
# ─────────────────────────────────────────

def test_prefijo_chunk():
    assert prefijo_chunk("chunk_002") == "clip_c002"


def test_asignar_clip_ids_usa_el_guardado_y_cuenta_los_legacy():
    chunks = [
        ("viejo", [{"publicar": True}, {"publicar": False}, {"publicar": True}]),
        ("nuevo", [{"publicar": True, "clip_id": "clip_c002_01"}, {"revision_descartado": True, "clip_id": "clip_c002_02"}]),
    ]
    ids = asignar_clip_ids(chunks, lambda i: i.get("publicar") or i.get("revision_descartado"))
    assert ids == [
        ("viejo", 0, "clip_001"),
        ("viejo", 2, "clip_002"),
        ("nuevo", 0, "clip_c002_01"),
        ("nuevo", 1, "clip_c002_02"),
    ]
