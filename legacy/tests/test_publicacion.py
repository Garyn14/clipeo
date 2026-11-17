"""Cola de publicación (backend/app/publicacion): horarios, cola, motor simulado y cliente TikTok."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ["PUBLICACION_MOTOR"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.publicacion import base, cola, cuentas, db, horarios, motor, simulado, tiktok  # noqa: E402
from app.publicacion.texto import texto_tiktok  # noqa: E402

Z = horarios.ZONA
API = tiktok.API


def t(dia: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, dia, h, m, tzinfo=Z)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "pub.db")
    c = db.conectar()
    yield c
    c.close()


@pytest.fixture
def reloj(monkeypatch):
    """Fija la hora del motor/cola: reloj.ahora = t(...)."""
    class Reloj:
        ahora = t(9, 10)
    r = Reloj()
    monkeypatch.setattr(horarios, "ahora", lambda: r.ahora)
    monkeypatch.setattr(cola, "ahora", lambda: r.ahora)
    monkeypatch.setattr(cuentas, "ahora", lambda: r.ahora)
    monkeypatch.setattr(tiktok, "ahora", lambda: r.ahora)
    return r


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "clip_c001_01.mp4"
    p.write_bytes(b"\x00" * 2048)
    return p


@pytest.fixture(autouse=True)
def simulado_rapido(monkeypatch):
    monkeypatch.setenv("PUBLICACION_SIMULADO_DEMORA", "0")
    monkeypatch.setenv("PUBLICACION_SIMULAR_FALLA", "")
    monkeypatch.setattr(tiktok, "_dormir", lambda s: None)


def encolar(conn, video, clip_id="clip_c001_01", nicho="zapatillas_peru"):
    return cola.encolar(conn, "20261009_100000", clip_id, nicho, str(video), "Título")


# ── Horarios ─────────────────────────────────────────────────

def decidir(momento, ocupados=(), ultimo=None, hay_cola=True):
    return horarios.decidir(momento, "8,12,16,20", set(ocupados), ultimo, hay_cola)


def test_slot_ya_cubierto_no_envia():
    d = decidir(t(9, 9), ocupados=[horarios.clave_slot(t(9, 8))])
    assert not d.enviar and "ya cubierto" in d.motivo


def test_atrasado_dentro_de_la_ventana_envia_el_slot():
    d = decidir(t(9, 10))
    assert d.enviar and d.slot == t(9, 8)


def test_silencio_nocturno():
    assert not decidir(t(9, 22, 30)).enviar
    d = decidir(t(9, 2))
    assert not d.enviar and "silencio" in d.motivo


def test_slot_de_las_20_vale_hasta_las_22():
    assert decidir(t(9, 21, 30)).enviar
    assert not decidir(t(9, 22, 0)).enviar


def test_separacion_minima_tras_un_envio_atrasado():
    ultimo = t(9, 11, 30)  # se cubrió tarde el horario de las 8
    ocup = [horarios.clave_slot(t(9, 8))]
    d = decidir(t(9, 12, 10), ocupados=ocup, ultimo=ultimo)
    assert not d.enviar and "13:30" in d.motivo
    d = decidir(t(9, 13, 35), ocupados=ocup, ultimo=ultimo)
    assert d.enviar and d.slot == t(9, 12)


def test_cola_vacia():
    d = decidir(t(9, 12, 5), hay_cola=False)
    assert not d.enviar and "vacía" in d.motivo


def test_prender_tras_la_noche_cubre_solo_el_slot_vigente():
    d = decidir(t(10, 9, 0))   # la PC estuvo apagada desde ayer a la tarde
    assert d.enviar and d.slot == t(10, 8)


def estimar(momento, n, ocupados=(), ultimo=None, pausa=None):
    return horarios.estimar(momento, "8,12,16,20", set(ocupados), ultimo, n, pausa)


def test_estimacion_caso_real():
    # 12:40, el de las 8 se cubrió a las 11:16:09 (revisión de las 11:10): 3 clips en cola
    sal = estimar(t(10, 12, 40), 4, ocupados=[horarios.clave_slot(t(10, 8))],
                  ultimo=datetime(2026, 10, 10, 11, 16, 9, tzinfo=Z))
    assert sal == [(t(10, 13, 10), t(10, 12)), (t(10, 16), t(10, 16)),
                   (t(10, 20), t(10, 20)), (t(11, 8), t(11, 8))]


def test_estimacion_de_noche_va_a_las_8():
    assert estimar(t(10, 23), 1) == [(t(11, 8), t(11, 8))]


def test_estimacion_separacion_empuja_dentro_de_la_ventana():
    sal = estimar(t(10, 15, 30), 1, ocupados=[horarios.clave_slot(t(10, 12))], ultimo=t(10, 15))
    assert sal == [(t(10, 17), t(10, 16))]


def test_estimacion_con_cuenta_pausada():
    sal = estimar(t(10, 20, 30), 2, pausa=datetime(2026, 10, 11, 10, 30, 5, tzinfo=Z))
    assert sal == [(t(11, 10, 40), t(11, 8)), (t(11, 12, 40), t(11, 12))]


def test_estimacion_coincide_con_lo_que_decide_el_motor():
    ocup = [horarios.clave_slot(t(10, 8))]
    ultimo = datetime(2026, 10, 10, 11, 16, 9, tzinfo=Z)
    (sale, slot), = estimar(t(10, 12, 40), 1, ocupados=ocup, ultimo=ultimo)
    momento = t(10, 12, 40)
    while momento <= t(10, 14):          # el motor revisa en la grilla del reloj
        d = decidir(momento, ocupados=ocup, ultimo=ultimo)
        if d.enviar:
            break
        momento = horarios.proxima_revision(momento)
    assert d.enviar and momento == sale and d.slot == slot


def test_proxima_revision_alineada_al_reloj():
    assert horarios.proxima_revision(datetime(2026, 10, 10, 13, 16, 20, tzinfo=Z)) == t(10, 13, 20)
    assert horarios.proxima_revision(t(10, 13, 20)) == t(10, 13, 30)
    assert horarios.revision_desde(t(10, 13, 20)) == t(10, 13, 20)


def test_horarios_invalidos():
    with pytest.raises(ValueError):
        horarios.parsear_horarios("8,23")


# ── Cola ─────────────────────────────────────────────────────

def test_encolar_es_idempotente(conn, video):
    a = encolar(conn, video)
    b = encolar(conn, video)
    assert a["id"] == b["id"]
    assert len(cola.listar(conn)) == 1


def test_descartar_cancela_y_reaprobar_vuelve_a_la_cola(conn, video):
    pub = encolar(conn, video)
    cola.cancelar_por_clip(conn, pub["session_id"], pub["clip_id"], "descartado")
    assert cola.obtener(conn, pub["id"])["estado"] == "cancelado"
    assert encolar(conn, video)["estado"] == "en_cola"


def test_mover_intercambia_lugares(conn, video):
    a = encolar(conn, video, "clip_c001_01")
    b = encolar(conn, video, "clip_c001_02")
    cola.mover(conn, b["id"], "arriba")
    assert cola.primero_en_cola(conn, "zapatillas_peru")["id"] == b["id"]


def test_un_horario_no_se_ocupa_dos_veces(conn, video):
    a = encolar(conn, video, "clip_c001_01")
    b = encolar(conn, video, "clip_c001_02")
    slot = horarios.clave_slot(t(9, 8))
    assert cola.reclamar(conn, a["id"], slot, "x")
    assert not cola.reclamar(conn, a["id"], slot, "x")      # ya no está en cola
    assert not cola.reclamar(conn, b["id"], slot, "x")      # índice único parcial
    assert cola.obtener(conn, b["id"])["estado"] == "en_cola"


def test_reaprobar_un_cancelado_actualiza_el_texto(conn, video):
    pub = cola.encolar(conn, "s", "clip_c001_01", "zapatillas_peru", str(video), "t", "viejo")
    cola.cancelar_por_clip(conn, "s", "clip_c001_01", "editado")
    cola.encolar(conn, "s", "clip_c001_01", "zapatillas_peru", str(video), "t", "nuevo")
    assert cola.obtener(conn, pub["id"])["texto"] == "nuevo"


def test_base_vieja_gana_la_columna_texto(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.executescript(db._ESQUEMA.replace(
        "    texto           TEXT,                      -- descripción + # para pegar al activar el borrador (se congela al encolar)\n", ""))
    vieja.execute("INSERT INTO publicaciones (plataforma, session_id, clip_id, nicho, ruta_video, orden, estado, "
                  "encolada_en, actualizada_en) VALUES ('tiktok','s','c','n','r',1,'en_cola','x','x')")
    vieja.commit()
    assert "texto" not in {f[1] for f in vieja.execute("PRAGMA table_info(publicaciones)")}
    vieja.close()

    monkeypatch.setattr(db, "DB_PATH", ruta)
    c = db.conectar()
    fila = c.execute("SELECT * FROM publicaciones").fetchone()
    assert fila["clip_id"] == "c" and fila["texto"] is None
    c.close()


@pytest.mark.parametrize("clip,esperado", [
    ({"publicacion": {"tiktok": {"descripcion": "Hola #fyp #parati", "hashtags": ["#fyp", "#parati"]}}},
     "Hola #fyp #parati"),
    ({"publicacion": {"tiktok": {"descripcion": " Hola #fyp ", "hashtags": ["#fyp", "#zapatillasperu"]}}},
     "Hola #fyp #zapatillasperu"),
    ({"publicacion": {"tiktok": {"descripcion": "Hola #FritzSport", "hashtags": ["#fritzsport"]}}},
     "Hola #FritzSport"),
    ({"publicacion": {"tiktok": {"descripcion": "Hola #fypage", "hashtags": ["#fyp"]}}},
     "Hola #fypage #fyp"),
    ({"publicacion": {"tiktok": {"descripcion": "", "hashtags": ["#fyp", "#parati"]}}}, "#fyp #parati"),
    ({"publicacion": {"tiktok": {"descripcion": "", "hashtags": []}}}, None),
    ({"hashtags": ["#kickperu"]}, None),
    ({}, None),
])
def test_texto_tiktok(clip, esperado):
    assert texto_tiktok(clip) == esperado


def test_se_agotan_los_reintentos(conn, video):
    pub = encolar(conn, video)
    for i in range(cola.MAX_INTENTOS):
        assert cola.reclamar(conn, pub["id"], None, "x")
        estado = cola.resolver(conn, pub["id"], "reintentable", "sin red", "red")["estado"]
    assert estado == "error"
    assert cola.reintentar(conn, pub["id"])["estado"] == "en_cola"


# ── Motor con el publicador simulado ─────────────────────────

def cuenta_simulada(conn):
    return cuentas.conectar(conn, "zapatillas_peru", "simulado", nombre="prueba")


def test_tick_envia_un_clip_y_queda_en_bandeja(conn, reloj, video):
    cuenta_simulada(conn)
    a = encolar(conn, video, "clip_c001_01")
    encolar(conn, video, "clip_c001_02")
    reloj.ahora = t(9, 8, 5)
    motor.tick()
    pub = cola.obtener(conn, a["id"])
    assert pub["estado"] == "en_bandeja"
    assert pub["slot"] == horarios.clave_slot(t(9, 8))
    tipos = [e["tipo"] for e in cola.eventos(conn, a["id"])]
    assert {"init", "chunk", "status"} <= set(tipos)

    reloj.ahora = t(9, 8, 15)
    motor.tick()   # mismo horario: no envía el segundo
    assert cola.primero_en_cola(conn, "zapatillas_peru")["clip_id"] == "clip_c001_02"


@pytest.mark.parametrize("falla,estado_pub,estado_cuenta", [
    ("pendientes", "en_cola", "pausada"),
    ("token", "en_cola", "requiere_reconexion"),
    ("red", "en_cola", "conectada"),
    ("formato", "error", "conectada"),
    ("sin_confirmar", "sin_confirmar", "conectada"),
])
def test_fallas_simuladas(conn, reloj, video, monkeypatch, falla, estado_pub, estado_cuenta):
    monkeypatch.setenv("PUBLICACION_SIMULAR_FALLA", falla)
    c = cuenta_simulada(conn)
    pub = encolar(conn, video)
    reloj.ahora = t(9, 12, 1)
    motor.tick()
    assert cola.obtener(conn, pub["id"])["estado"] == estado_pub
    assert cuentas.obtener(conn, c["id"])["estado"] == estado_cuenta


def test_cuenta_pausada_se_reanuda_sola(conn, reloj, video, monkeypatch):
    monkeypatch.setenv("PUBLICACION_SIMULAR_FALLA", "pendientes")
    c = cuenta_simulada(conn)
    encolar(conn, video)
    reloj.ahora = t(9, 12, 1)
    motor.tick()
    monkeypatch.setenv("PUBLICACION_SIMULAR_FALLA", "")
    reloj.ahora = t(10, 12, 2)    # 24 h después
    motor.tick()
    assert cuentas.obtener(conn, c["id"])["estado"] == "conectada"
    assert cola.listar(conn, estado="en_bandeja")


def test_archivo_faltante_es_error(conn, reloj, tmp_path):
    cuenta_simulada(conn)
    pub = encolar(conn, tmp_path / "no_existe.mp4")
    reloj.ahora = t(9, 8, 1)
    motor.tick()
    assert cola.obtener(conn, pub["id"])["error_codigo"] == "archivo_no_existe"


def test_recuperacion_sin_publish_id_vuelve_a_la_cola(conn, reloj, video):
    cuenta_simulada(conn)
    pub = encolar(conn, video)
    cola.reclamar(conn, pub["id"], horarios.clave_slot(t(9, 8)), "x")
    conn.execute("UPDATE publicaciones SET proceso_pid = NULL WHERE id = ?", (pub["id"],))
    reloj.ahora = t(9, 7)          # antes del horario: el tick solo recupera
    motor.tick()
    assert cola.obtener(conn, pub["id"])["estado"] == "en_cola"


def test_recuperacion_con_publish_id_consulta_a_la_plataforma(conn, reloj, video):
    cuenta_simulada(conn)
    pub = encolar(conn, video)
    cola.reclamar(conn, pub["id"], horarios.clave_slot(t(9, 8)), "x")
    cola.guardar_publish_id(conn, pub["id"], "sim_abc")
    conn.execute("UPDATE publicaciones SET proceso_pid = NULL WHERE id = ?", (pub["id"],))
    reloj.ahora = t(9, 7)
    motor.tick()
    assert cola.obtener(conn, pub["id"])["estado"] == "en_bandeja"


def test_nicho_sin_cuenta_espera(conn, reloj, video):
    pub = encolar(conn, video, nicho="streamers_peru")
    reloj.ahora = t(9, 8, 1)
    motor.tick()
    assert cola.obtener(conn, pub["id"])["estado"] == "en_cola"
    rev = conn.execute("SELECT decision FROM revisiones WHERE nicho = 'streamers_peru'").fetchone()
    assert "sin cuenta" in rev["decision"]


def test_revisiones_iguales_se_agrupan(conn, reloj, video):
    cuenta_simulada(conn)
    reloj.ahora = t(9, 2)
    motor.tick()
    reloj.ahora = t(9, 2, 10)
    motor.tick()
    filas = conn.execute("SELECT * FROM revisiones").fetchall()
    assert len(filas) == 1 and filas[0]["veces"] == 2


# ── Enganche con la revisión ─────────────────────────────────

def sesion(tmp_path):
    d = tmp_path / "20261009_100000"
    d.mkdir()
    (d / "pipeline_estado.json").write_text('{"config": "zapatillas_peru"}', encoding="utf-8")
    return d


def test_aprobar_encola_con_el_nicho_de_la_sesion(conn, tmp_path):
    from app.services import review_actions
    d = sesion(tmp_path)
    review_actions._encolar_publicacion(d, "clip_c001_01", {"texto_linea1": "Fritz reta", "texto_linea2": "a un tico"})
    pub = cola.primero_en_cola(conn, "zapatillas_peru")
    assert pub["clip_id"] == "clip_c001_01" and pub["titulo"] == "Fritz reta / a un tico"
    assert pub["ruta_video"].endswith("clip_c001_01.mp4")

    review_actions._sacar_de_cola(d, "clip_c001_01", "descartado")
    assert cola.obtener(conn, pub["id"])["estado"] == "cancelado"


COPY = {"publicacion": {"tiktok": {
    "descripcion": "Fritz no perdona ni una venta 😂 #fritzsport #fyp",
    "hashtags": ["#zapatillasperu", "#fyp", "#fritzsport"],
}}}


def test_aprobar_guarda_el_texto_para_tiktok(conn, tmp_path):
    from app.services import review_actions
    review_actions._encolar_publicacion(sesion(tmp_path), "clip_c001_01", {"texto_linea1": "x", **COPY})
    pub = cola.primero_en_cola(conn, "zapatillas_peru")
    assert pub["texto"] == "Fritz no perdona ni una venta 😂 #fritzsport #fyp #zapatillasperu"


def test_completar_textos_de_lo_ya_encolado(conn, tmp_path, monkeypatch, video):
    from app.services import review_actions
    d = sesion(tmp_path)
    (d / "contenido_chunks").mkdir()
    (d / "contenido_chunks" / "chunk_001.json").write_text(json.dumps({"contenido": [
        {"publicar": True, "clip_id": "clip_c001_01", **COPY},
        {"publicar": True, "clip_id": "clip_c001_02"},          # flujo viejo: sin copy
    ]}), encoding="utf-8")
    monkeypatch.setattr(review_actions, "STREAM_DATA", tmp_path)
    a = cola.encolar(conn, d.name, "clip_c001_01", "zapatillas_peru", str(video), "t")
    b = cola.encolar(conn, d.name, "clip_c001_02", "zapatillas_peru", str(video), "t")
    c = cola.encolar(conn, d.name, "clip_c001_03", "zapatillas_peru", str(video), "t", "ya tenía texto")

    assert review_actions.completar_textos_publicacion() == 1
    assert cola.obtener(conn, a["id"])["texto"].endswith("#zapatillasperu")
    assert cola.obtener(conn, b["id"])["texto"] is None
    assert cola.obtener(conn, c["id"])["texto"] == "ya tenía texto"
    assert review_actions.completar_textos_publicacion() == 0     # idempotente


def test_una_falla_de_la_cola_no_rompe_la_aprobacion(tmp_path, monkeypatch):
    from app.services import review_actions

    def roto():
        raise OSError("disco lleno")
    monkeypatch.setattr(db, "conectar", roto)
    review_actions._encolar_publicacion(sesion(tmp_path), "clip_c001_01", {})   # no lanza


# ── Cliente TikTok (HTTP mockeado) ───────────────────────────

MB = tiktok.MB


@pytest.mark.parametrize("size,esperado", [
    (1 * MB, (1 * MB, 1)),
    (50 * MB, (50 * MB, 1)),
    (64 * MB, (64 * MB, 1)),
    (64 * MB + 1, (10 * MB, 6)),
])
def test_plan_partes(size, esperado):
    assert tiktok.plan_partes(size) == esperado
    rangos = tiktok.rangos_partes(size)
    assert rangos[-1][1] == size - 1
    assert rangos[-1][1] - rangos[-1][0] + 1 <= 128 * MB


def cuenta_real(conn):
    return cuentas.conectar(conn, "zapatillas_peru", "real", nombre="@zapas", tokens={
        "open_id": "oid", "access_token": "TOKEN_SECRETO", "access_vence": horarios.iso(t(20, 0)),
        "refresh_token": "REFRESH_SECRETO", "refresh_vence": horarios.iso(t(30, 0)),
    })


def mock_init(requests_mock, **kw):
    cuerpo = kw.pop("json", {"data": {"publish_id": "v_inbox_1", "upload_url": "https://up.tiktok/u1"},
                             "error": {"code": "ok", "message": "", "log_id": "L1"}})
    requests_mock.post(f"{API}/v2/post/publish/inbox/video/init/", json=cuerpo, **kw)


def mock_status(requests_mock, *estados):
    requests_mock.post(f"{API}/v2/post/publish/status/fetch/", [
        {"json": {"data": {"status": s, "fail_reason": fr}, "error": {"code": "ok", "log_id": "L2"}}}
        for s, fr in estados
    ])


def test_envio_real_completo_sin_tokens_en_eventos(conn, reloj, video, requests_mock):
    cuenta_real(conn)
    pub = encolar(conn, video)
    mock_init(requests_mock)
    requests_mock.put("https://up.tiktok/u1", status_code=201)
    mock_status(requests_mock, ("PROCESSING_UPLOAD", None), ("SEND_TO_USER_INBOX", None))
    reloj.ahora = t(9, 8, 1)
    motor.tick()

    final = cola.obtener(conn, pub["id"])
    assert final["estado"] == "en_bandeja" and final["publish_id"] == "v_inbox_1"
    put = [r for r in requests_mock.request_history if r.method == "PUT"][0]
    assert put.headers["Content-Range"] == f"bytes 0-2047/2048"
    init = requests_mock.request_history[0]
    assert init.json()["source_info"] == {"source": "FILE_UPLOAD", "video_size": 2048,
                                          "chunk_size": 2048, "total_chunk_count": 1}
    volcado = str(conn.execute("SELECT * FROM eventos").fetchall() and
                  [tuple(f) for f in conn.execute("SELECT mensaje, detalle FROM eventos")])
    assert "TOKEN_SECRETO" not in volcado and "REFRESH_SECRETO" not in volcado


def registro():
    eventos = []
    return eventos, lambda tipo, mensaje, detalle=None: eventos.append((tipo, mensaje, detalle))


@pytest.mark.parametrize("http,codigo,tipo", [
    (403, "spam_risk_too_many_pending_share", base.PAUSAR),
    (401, "access_token_invalid", base.RECONECTAR),
    (403, "spam_risk_user_banned_from_posting", base.ERROR),
    (429, "rate_limit_exceeded", base.REINTENTABLE),
    (503, "internal_error", base.REINTENTABLE),
])
def test_errores_de_init(video, requests_mock, http, codigo, tipo):
    mock_init(requests_mock, status_code=http,
              json={"error": {"code": codigo, "message": "x", "log_id": "L9"}})
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        tiktok.PublicadorTikTok().enviar(video, {"access_token": "T"}, {}, lambda p: None, reg)
    assert e.value.tipo == tipo and e.value.detalle["log_id"] == "L9"


def test_status_failed_es_definitivo(video, requests_mock):
    mock_init(requests_mock)
    requests_mock.put("https://up.tiktok/u1", status_code=201)
    mock_status(requests_mock, ("FAILED", "file_format_check_failed"))
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        tiktok.PublicadorTikTok().enviar(video, {"access_token": "T"}, {}, lambda p: None, reg)
    assert e.value.tipo == base.ERROR and e.value.codigo == "file_format_check_failed"


def test_sin_confirmacion_tras_subir(video, requests_mock, monkeypatch):
    monkeypatch.setattr(tiktok, "SONDEO_MAX_S", 15)
    mock_init(requests_mock)
    requests_mock.put("https://up.tiktok/u1", status_code=201)
    mock_status(requests_mock, ("PROCESSING_UPLOAD", None))
    eventos, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        tiktok.PublicadorTikTok().enviar(video, {"access_token": "T"}, {}, lambda p: None, reg)
    assert e.value.tipo == base.SIN_CONFIRMAR
    assert sum(1 for ev in eventos if ev[0] == "status") == 1   # solo se registran los cambios


def test_subida_que_falla_es_reintentable(video, requests_mock):
    mock_init(requests_mock)
    requests_mock.put("https://up.tiktok/u1", status_code=500)
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        tiktok.PublicadorTikTok().enviar(video, {"access_token": "T"}, {}, lambda p: None, reg)
    assert e.value.tipo == base.REINTENTABLE
    assert len([r for r in requests_mock.request_history if r.method == "PUT"]) == tiktok.REINTENTOS_PARTE


def test_leer_url_de_vuelta():
    code, state = tiktok.leer_url_de_vuelta("https://ejemplo.com/cb?code=abc%2A1&scopes=video.upload&state=s1")
    assert (code, state) == ("abc*1", "s1")
    with pytest.raises(ValueError):
        tiktok.leer_url_de_vuelta("https://ejemplo.com/cb?error=access_denied&state=s1")


def test_canje_y_renovacion_de_token(requests_mock, monkeypatch):
    monkeypatch.setattr(tiktok, "credenciales",
                        lambda: {"client_key": "ck", "client_secret": "cs", "redirect_uri": "https://x/cb"})
    requests_mock.post(f"{API}/v2/oauth/token/", json={
        "access_token": "A", "expires_in": 86400, "open_id": "o", "refresh_token": "R",
        "refresh_expires_in": 31536000, "scope": "user.info.basic,video.upload", "token_type": "Bearer",
    })
    tokens = tiktok.canjear_codigo("code1")
    assert tokens["access_token"] == "A" and "scope" not in tokens
    assert "grant_type=authorization_code" in requests_mock.last_request.text

    requests_mock.post(f"{API}/v2/oauth/token/", status_code=400,
                       json={"error": "invalid_grant", "error_description": "expired", "log_id": "L"})
    with pytest.raises(base.ErrorEnvio) as e:
        tiktok.renovar("R")
    assert e.value.tipo == base.RECONECTAR


def test_token_por_vencer_se_renueva_antes_de_enviar(conn, reloj, video, requests_mock, monkeypatch):
    c = cuenta_real(conn)
    conn.execute("UPDATE cuentas SET access_vence = ? WHERE id = ?", (horarios.iso(t(9, 8, 30)), c["id"]))
    monkeypatch.setattr(tiktok, "credenciales",
                        lambda: {"client_key": "ck", "client_secret": "cs", "redirect_uri": "https://x/cb"})
    requests_mock.post(f"{API}/v2/oauth/token/", json={
        "access_token": "NUEVO", "expires_in": 86400, "refresh_token": "R2", "refresh_expires_in": 100,
    })
    mock_init(requests_mock)
    requests_mock.put("https://up.tiktok/u1", status_code=201)
    mock_status(requests_mock, ("SEND_TO_USER_INBOX", None))
    pub = encolar(conn, video)
    reloj.ahora = t(9, 8, 1)
    motor.tick()
    assert cola.obtener(conn, pub["id"])["estado"] == "en_bandeja"
    init = [r for r in requests_mock.request_history if r.url.endswith("/inbox/video/init/")][0]
    assert init.headers["Authorization"] == "Bearer NUEVO"
