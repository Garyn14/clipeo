"""Publicación en YouTube Shorts: colas independientes por plataforma, texto y cliente (HTTP mockeado)."""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

os.environ["PUBLICACION_MOTOR"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.publicacion import base, cola, cuentas, db, horarios, motor, youtube  # noqa: E402
from app.publicacion.texto import metadatos_youtube, texto_youtube  # noqa: E402

Z = horarios.ZONA
NICHO = "zapatillas_peru"
SESION = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=XYZ"


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
    class Reloj:
        ahora = t(9, 10)
    r = Reloj()
    for modulo in (horarios, cola, cuentas, youtube):
        monkeypatch.setattr(modulo, "ahora", lambda: r.ahora)
    return r


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "clip_c001_01.mp4"
    p.write_bytes(b"\x00" * 2048)
    return p


@pytest.fixture(autouse=True)
def rapido(monkeypatch):
    monkeypatch.setenv("PUBLICACION_SIMULADO_DEMORA", "0")
    monkeypatch.setenv("PUBLICACION_SIMULAR_FALLA", "")
    monkeypatch.setattr(youtube, "_dormir", lambda s: None)


META = {"titulo": "Tío Fritz reta a un cliente", "descripcion": "Reto de dominadas #Shorts", "tags": ["tio fritz"]}


def encolar(conn, video, clip_id="clip_c001_01", plataforma="youtube"):
    meta = META if plataforma == "youtube" else None
    return cola.encolar(conn, "20261009_100000", clip_id, NICHO, str(video), "Título", "texto",
                        plataforma=plataforma, metadatos=meta)


# ── Texto ────────────────────────────────────────────────────

def clip_con(yt: dict, **extra) -> dict:
    return {"texto_linea1": "El tío Fritz reta", "texto_linea2": "a un cliente", **extra,
            "publicacion": {"youtube_shorts": yt}}


def test_metadatos_youtube_completos():
    m = metadatos_youtube(clip_con({"titulo_alt": "Fritz y las dominadas", "descripcion": "Reto #Shorts",
                                    "hashtags": ["#Shorts", "#Peru"], "tags_backend": ["tio fritz", "reto"]}))
    assert m == {"titulo": "Fritz y las dominadas", "descripcion": "Reto #Shorts #Peru", "tags": ["tio fritz", "reto"]}


def test_metadatos_youtube_titulo_de_respaldo_y_limites():
    m = metadatos_youtube(clip_con({"titulo_alt": "", "descripcion": "a <b> c", "tags_backend": ["x" * 300] * 3}))
    assert m["titulo"] == "El tío Fritz reta a un cliente"
    assert m["descripcion"] == "a b c"
    assert m["tags"] == ["x" * 300]                  # el segundo pasaría de 500 caracteres
    largo = metadatos_youtube(clip_con({"titulo_alt": "<" + "y" * 150}))
    assert len(largo["titulo"]) == 100 and "<" not in largo["titulo"]


def test_metadatos_youtube_sin_nada():
    assert metadatos_youtube({}) is None
    assert texto_youtube(None) is None
    assert texto_youtube(META).startswith("Título: Tío Fritz")


# ── Colas independientes ─────────────────────────────────────

def sesion_dir(tmp_path):
    d = tmp_path / "20261009_100000"
    d.mkdir()
    (d / "pipeline_estado.json").write_text(json.dumps({"config": NICHO}), encoding="utf-8")
    return d


CLIP = {"texto_linea1": "Fritz reta", "texto_linea2": "a un tico", "publicacion": {
    "tiktok": {"descripcion": "TikTok #fyp", "hashtags": ["#fyp"]},
    "youtube_shorts": {"titulo_alt": "Fritz reta a un tico", "descripcion": "YT #Shorts", "hashtags": ["#Shorts"],
                       "tags_backend": ["tio fritz"]},
}}


def test_aprobar_encola_en_las_dos_plataformas(conn, tmp_path):
    from app.services import review_actions
    d = sesion_dir(tmp_path)
    review_actions._encolar_publicacion(d, "clip_c001_01", CLIP)
    tk = cola.primero_en_cola(conn, NICHO, "tiktok")
    yt = cola.primero_en_cola(conn, NICHO, "youtube")
    assert tk["texto"] == "TikTok #fyp" and tk["metadatos"] is None
    assert json.loads(yt["metadatos"])["titulo"] == "Fritz reta a un tico"
    assert "Título: Fritz reta a un tico" in yt["texto"]

    review_actions._sacar_de_cola(d, "clip_c001_01", "descartado")      # sale de las dos
    assert cola.obtener(conn, tk["id"])["estado"] == "cancelado"
    assert cola.obtener(conn, yt["id"])["estado"] == "cancelado"


def test_si_una_cola_falla_la_otra_entra_igual(conn, tmp_path, monkeypatch):
    from app.services import review_actions
    original = cola.encolar

    def falla_youtube(*a, **kw):
        if kw.get("plataforma") == "youtube":
            raise RuntimeError("boom")
        return original(*a, **kw)
    monkeypatch.setattr(cola, "encolar", falla_youtube)
    review_actions._encolar_publicacion(sesion_dir(tmp_path), "clip_c001_01", CLIP)
    assert cola.primero_en_cola(conn, NICHO, "tiktok")
    assert cola.primero_en_cola(conn, NICHO, "youtube") is None


def test_mover_en_una_cola_no_toca_la_otra(conn, video):
    a_tk, b_tk = encolar(conn, video, "c1", "tiktok"), encolar(conn, video, "c2", "tiktok")
    a_yt, b_yt = encolar(conn, video, "c1"), encolar(conn, video, "c2")
    cola.mover(conn, b_yt["id"], "arriba")
    assert cola.primero_en_cola(conn, NICHO, "youtube")["id"] == b_yt["id"]
    assert cola.primero_en_cola(conn, NICHO, "tiktok")["id"] == a_tk["id"]


def test_tick_envia_uno_por_plataforma_en_el_mismo_horario(conn, reloj, video):
    for p in ("tiktok", "youtube"):
        cuentas.conectar(conn, NICHO, "simulado", plataforma=p)
        encolar(conn, video, "c1", p)
        encolar(conn, video, "c2", p)
    reloj.ahora = t(9, 8, 5)
    motor.tick()
    slot = horarios.clave_slot(t(9, 8))
    for p in ("tiktok", "youtube"):
        enviadas = cola.listar(conn, NICHO, "en_bandeja", plataforma=p)
        assert len(enviadas) == 1 and enviadas[0]["slot"] == slot
    decisiones = conn.execute("SELECT plataforma, envio FROM revisiones").fetchall()
    assert {(f["plataforma"], f["envio"]) for f in decisiones} == {("tiktok", 1), ("youtube", 1)}


def test_tiktok_pausada_no_frena_youtube(conn, reloj, video):
    tk = cuentas.conectar(conn, NICHO, "simulado", plataforma="tiktok")
    cuentas.conectar(conn, NICHO, "simulado", plataforma="youtube")
    cuentas.pausar(conn, tk["id"], "límite")
    encolar(conn, video, "c1", "tiktok")
    encolar(conn, video, "c1", "youtube")
    reloj.ahora = t(9, 12, 1)
    motor.tick()
    assert cola.listar(conn, NICHO, "en_bandeja", plataforma="youtube")
    assert cola.primero_en_cola(conn, NICHO, "tiktok")


def test_sin_cuenta_de_youtube_espera_y_lo_anota(conn, reloj, video):
    cuentas.conectar(conn, NICHO, "simulado", plataforma="tiktok")
    encolar(conn, video, "c1", "youtube")
    reloj.ahora = t(9, 8, 1)
    motor.tick()
    rev = conn.execute("SELECT decision FROM revisiones WHERE plataforma = 'youtube'").fetchone()
    assert "sin cuenta" in rev["decision"]


def test_copiar_cola_de_tiktok_a_youtube(conn, tmp_path, monkeypatch, video):
    from app.services import review_actions
    d = sesion_dir(tmp_path)
    (d / "contenido_chunks").mkdir()
    (d / "contenido_chunks" / "chunk_001.json").write_text(json.dumps({"contenido": [
        {"publicar": True, "clip_id": "clip_c001_01", **CLIP},
        {"publicar": True, "clip_id": "clip_c001_02", **CLIP},
    ]}), encoding="utf-8")
    monkeypatch.setattr(review_actions, "STREAM_DATA", tmp_path)
    a = cola.encolar(conn, d.name, "clip_c001_01", NICHO, str(video), "t")
    b = cola.encolar(conn, d.name, "clip_c001_02", NICHO, str(video), "t")
    cola.mover(conn, b["id"], "arriba")

    assert review_actions.copiar_cola_a_youtube(NICHO) == 2
    assert review_actions.copiar_cola_a_youtube(NICHO) == 0              # idempotente
    yt = cola.listar(conn, NICHO, "en_cola", plataforma="youtube")
    assert [p["clip_id"] for p in yt] == ["clip_c001_02", "clip_c001_01"]  # mismo orden
    assert json.loads(yt[0]["metadatos"])["titulo"] == "Fritz reta a un tico"
    assert [p["id"] for p in cola.listar(conn, NICHO, "en_cola")] == [b["id"], a["id"]]   # TikTok igual


def test_base_vieja_gana_las_columnas_nuevas(tmp_path, monkeypatch):
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.executescript("""
        CREATE TABLE publicaciones (id INTEGER PRIMARY KEY, plataforma TEXT NOT NULL, session_id TEXT NOT NULL,
            clip_id TEXT NOT NULL, nicho TEXT NOT NULL, ruta_video TEXT NOT NULL, titulo TEXT, orden REAL NOT NULL,
            estado TEXT NOT NULL, slot TEXT, publish_id TEXT, subida_completa INTEGER NOT NULL DEFAULT 0,
            intentos INTEGER NOT NULL DEFAULT 0, error_codigo TEXT, error_mensaje TEXT, proceso_pid INTEGER,
            proceso_inicio TEXT, encolada_en TEXT NOT NULL, enviada_en TEXT, confirmada_en TEXT,
            actualizada_en TEXT NOT NULL, UNIQUE (plataforma, session_id, clip_id));
        CREATE TABLE revisiones (id INTEGER PRIMARY KEY, nicho TEXT NOT NULL, desde TEXT NOT NULL,
            hasta TEXT NOT NULL, veces INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL,
            envio INTEGER NOT NULL DEFAULT 0);
        INSERT INTO revisiones (nicho, desde, hasta, decision) VALUES ('n', 'x', 'x', 'vieja');
    """)
    vieja.close()
    monkeypatch.setattr(db, "DB_PATH", ruta)
    c = db.conectar()
    cols = {f["name"] for f in c.execute("PRAGMA table_info(publicaciones)")}
    assert {"texto", "metadatos", "sesion_subida"} <= cols
    assert c.execute("SELECT plataforma FROM revisiones").fetchone()["plataforma"] == "tiktok"
    c.close()


# ── Cliente de YouTube (HTTP mockeado) ───────────────────────

def registro():
    eventos = []
    return eventos, lambda tipo, mensaje, detalle=None: eventos.append((tipo, mensaje, detalle))


PUB = {"metadatos": json.dumps(META)}
CUENTA = {"access_token": "TOKEN_SECRETO"}


def mock_init(rm, **kw):
    rm.post(f"{youtube.UPLOAD}/videos", headers={"Location": SESION}, status_code=200, **kw)


def mock_estado(rm, *estados):
    rm.get(f"{youtube.API}/videos", [
        {"json": {"items": [{"status": {"uploadStatus": e, **({"rejectionReason": m} if m else {})}}] if e else []}}
        for e, m in estados
    ])


def enviar(video, registrar, pub=PUB):
    ids, sesiones = [], []
    youtube.PublicadorYouTube().enviar(video, CUENTA, pub, ids.append, registrar, sesiones.append)
    return ids, sesiones


def test_envio_completo(video, requests_mock):
    mock_init(requests_mock)
    requests_mock.put(SESION, status_code=201, json={"id": "VID123"})
    mock_estado(requests_mock, ("uploaded", None), ("processed", None))
    eventos, reg = registro()
    ids, sesiones = enviar(video, reg)

    assert sesiones == [SESION] and ids == ["VID123"]
    init = requests_mock.request_history[0]
    cuerpo = init.json()
    assert cuerpo["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    assert cuerpo["snippet"]["title"] == META["titulo"] and cuerpo["snippet"]["tags"] == META["tags"]
    assert init.headers["X-Upload-Content-Length"] == "2048"
    assert any(e[0] == "chunk" and e[2]["subida_completa"] for e in eventos)
    texto = json.dumps(eventos)
    assert "TOKEN_SECRETO" not in texto and "upload_id" not in texto      # ni tokens ni la sesión


@pytest.mark.parametrize("visibilidad,avisa", [("public", False), ("private", True)])
def test_avisa_si_youtube_no_respeta_la_visibilidad(video, requests_mock, visibilidad, avisa):
    mock_init(requests_mock)
    requests_mock.put(SESION, status_code=201, json={"id": "VID123"})
    requests_mock.get(f"{youtube.API}/videos",
                      json={"items": [{"status": {"uploadStatus": "processed", "privacyStatus": visibilidad}}]})
    eventos, reg = registro()
    enviar(video, reg)                                   # el video llegó: no es una falla del envío
    avisos = [e for e in eventos if e[0] == "error" and "dejó el video como" in e[1]]
    assert bool(avisos) == avisa


def test_sin_metadatos_es_error(video):
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        enviar(video, reg, pub={"metadatos": None})
    assert e.value.tipo == base.ERROR


@pytest.mark.parametrize("http,razon,tipo", [
    (403, "quotaExceeded", base.PAUSAR),
    (403, "uploadLimitExceeded", base.PAUSAR),
    (401, "authError", base.RECONECTAR),
    (403, "youtubeSignupRequired", base.ERROR),
    (400, "invalidTitle", base.ERROR),
    (503, "backendError", base.REINTENTABLE),
])
def test_errores_de_init(video, requests_mock, http, razon, tipo):
    requests_mock.post(f"{youtube.UPLOAD}/videos", status_code=http,
                       json={"error": {"code": http, "message": "m", "errors": [{"reason": razon}]}})
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        enviar(video, reg)
    assert e.value.tipo == tipo


def test_subida_cortada_pero_completa_no_reenvia(video, requests_mock):
    import requests as rq
    mock_init(requests_mock)
    requests_mock.put(SESION, [{"exc": rq.ConnectionError("corte")}, {"status_code": 201, "json": {"id": "VID9"}}])
    mock_estado(requests_mock, ("processed", None))
    _, reg = registro()
    ids, _ = enviar(video, reg)
    assert ids == ["VID9"]
    consulta = requests_mock.request_history[2]
    assert consulta.headers["Content-Range"] == "bytes */2048"
    assert sum(1 for r in requests_mock.request_history if r.method == "POST") == 1   # una sola sesión


def test_subida_cortada_e_incompleta_es_reintentable(video, requests_mock):
    mock_init(requests_mock)
    requests_mock.put(SESION, [{"status_code": 503}, {"status_code": 308, "headers": {"Range": "bytes=0-1023"}}])
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        enviar(video, reg)
    assert e.value.tipo == base.REINTENTABLE


def test_subida_cortada_sin_poder_consultar_queda_sin_confirmar(video, requests_mock):
    import requests as rq
    mock_init(requests_mock)
    requests_mock.put(SESION, exc=rq.ConnectionError("sin red"))
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        enviar(video, reg)
    assert e.value.tipo == base.SIN_CONFIRMAR


def test_rechazo_por_duplicado_es_error(video, requests_mock):
    mock_init(requests_mock)
    requests_mock.put(SESION, status_code=201, json={"id": "VID1"})
    mock_estado(requests_mock, ("rejected", "duplicate"))
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        enviar(video, reg)
    assert e.value.tipo == base.ERROR and "duplicado" in e.value.mensaje


def test_procesado_que_no_termina_queda_sin_confirmar(video, requests_mock, monkeypatch):
    monkeypatch.setattr(youtube, "SONDEO_MAX_S", 30)
    mock_init(requests_mock)
    requests_mock.put(SESION, status_code=201, json={"id": "VID1"})
    mock_estado(requests_mock, ("uploaded", None))
    _, reg = registro()
    with pytest.raises(base.ErrorEnvio) as e:
        enviar(video, reg)
    assert e.value.tipo == base.SIN_CONFIRMAR


# ── Motor + recuperación con YouTube real (mockeado) ─────────

def cuenta_youtube(conn):
    return cuentas.conectar(conn, NICHO, "real", nombre="Canal", plataforma="youtube", tokens={
        "access_token": "AT", "access_vence": horarios.iso(t(9, 23)), "refresh_token": "RT", "refresh_vence": None})


def test_envio_real_por_el_motor(conn, reloj, video, requests_mock):
    cuenta_youtube(conn)
    pub = encolar(conn, video)
    mock_init(requests_mock)
    requests_mock.put(SESION, status_code=201, json={"id": "VIDM"})
    mock_estado(requests_mock, ("processed", None))
    reloj.ahora = t(9, 8, 1)
    motor.tick()
    final = cola.obtener(conn, pub["id"])
    assert final["estado"] == "en_bandeja" and final["publish_id"] == "VIDM" and final["subida_completa"] == 1
    assert final["sesion_subida"] == SESION
    assert "procesado" in cola.eventos(conn, pub["id"])[-1]["mensaje"]


def huerfana(conn, pub, **campos):
    cola.reclamar(conn, pub["id"], horarios.clave_slot(t(9, 8)), "x")
    sets = ", ".join(f"{k} = ?" for k in campos)
    conn.execute(f"UPDATE publicaciones SET proceso_pid = NULL, {sets} WHERE id = ?", (*campos.values(), pub["id"]))


def test_recuperacion_con_sesion_completa(conn, reloj, video, requests_mock):
    cuenta_youtube(conn)
    pub = encolar(conn, video)
    huerfana(conn, pub, sesion_subida=SESION)
    requests_mock.put(SESION, status_code=200, json={"id": "VIDR"})
    mock_estado(requests_mock, ("processed", None))
    reloj.ahora = t(9, 7)
    motor.tick()
    final = cola.obtener(conn, pub["id"])
    assert final["estado"] == "en_bandeja" and final["publish_id"] == "VIDR"


def test_recuperacion_con_sesion_incompleta_vuelve_a_la_cola(conn, reloj, video, requests_mock):
    cuenta_youtube(conn)
    pub = encolar(conn, video)
    huerfana(conn, pub, sesion_subida=SESION)
    requests_mock.put(SESION, status_code=308)
    reloj.ahora = t(9, 7)
    motor.tick()
    final = cola.obtener(conn, pub["id"])
    assert final["estado"] == "en_cola" and final["sesion_subida"] is None


def test_recuperacion_con_id_rechazado(conn, reloj, video, requests_mock):
    cuenta_youtube(conn)
    pub = encolar(conn, video)
    huerfana(conn, pub, sesion_subida=SESION, publish_id="VIDX", subida_completa=1)
    mock_estado(requests_mock, ("rejected", "duplicate"))
    reloj.ahora = t(9, 7)
    motor.tick()
    assert cola.obtener(conn, pub["id"])["estado"] == "error"


def test_token_vencido_se_renueva_y_refresh_invalido_pide_reconectar(conn, reloj, video, requests_mock, monkeypatch):
    monkeypatch.setattr(youtube, "credenciales", lambda: {"client_id": "C", "client_secret": "S",
                                                          "redirect_uri": youtube.REDIRECT_DEFAULT})
    c = cuenta_youtube(conn)
    encolar(conn, video)
    requests_mock.post(youtube.URL_TOKEN, status_code=400, json={"error": "invalid_grant"})
    reloj.ahora = t(10, 8, 1)        # el token venció a las 23:00 del 9 → hay que renovar
    motor.tick()
    assert cuentas.obtener(conn, c["id"])["estado"] == "requiere_reconexion"
    assert cola.primero_en_cola(conn, NICHO, "youtube")      # el clip vuelve a la cola


# ── OAuth ────────────────────────────────────────────────────

@pytest.fixture
def cred(monkeypatch):
    monkeypatch.setattr(youtube, "credenciales", lambda: {"client_id": "CID", "client_secret": "S",
                                                          "redirect_uri": youtube.REDIRECT_DEFAULT})


def test_url_de_autorizacion(cred):
    q = parse_qs(urlparse(youtube.url_autorizacion("yt_abc")).query)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"] and q["state"] == ["yt_abc"]
    assert "youtube.upload" in q["scope"][0]


def test_callback_conecta_la_cuenta(conn, cred, requests_mock):
    from fastapi.testclient import TestClient
    from app.main import app
    requests_mock.post(youtube.URL_TOKEN, json={
        "access_token": "AT", "expires_in": 3599, "refresh_token": "RT",
        "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"})
    requests_mock.get(f"{youtube.API}/channels", json={"items": [{"id": "UC1", "snippet": {"title": "Fritz Clips"}}]})
    conn.execute("INSERT INTO oauth_estados (state, nicho, creado) VALUES ('yt_ok', ?, ?)",
                 (NICHO, horarios.iso(horarios.ahora())))
    client = TestClient(app)
    r = client.get("/publicaciones/cuentas/youtube/callback", params={"code": "C", "state": "yt_ok"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/publicaciones/youtube?conexion=ok")
    cuenta = cuentas.por_nicho(conn, NICHO, "youtube")
    assert cuenta["nombre"] == "Fritz Clips" and cuenta["open_id"] == "UC1" and cuenta["refresh_token"] == "RT"

    r = client.get("/publicaciones/cuentas/youtube/callback", params={"code": "C", "state": "yt_ok"},
                   follow_redirects=False)                 # el state ya se usó
    assert "conexion=error" in r.headers["location"]


def test_callback_con_state_vencido(conn, cred):
    from fastapi.testclient import TestClient
    from app.main import app
    conn.execute("INSERT INTO oauth_estados (state, nicho, creado) VALUES ('yt_viejo', ?, ?)",
                 (NICHO, horarios.iso(horarios.ahora().replace(year=2020))))
    r = TestClient(app).get("/publicaciones/cuentas/youtube/callback", params={"code": "C", "state": "yt_viejo"},
                            follow_redirects=False)
    assert "conexion=error" in r.headers["location"] and "venci" in r.headers["location"]


def test_la_api_no_expone_la_sesion_de_subida(conn, video):
    from fastapi.testclient import TestClient
    from app.main import app
    pub = encolar(conn, video)
    conn.execute("UPDATE publicaciones SET sesion_subida = ? WHERE id = ?", (SESION, pub["id"]))
    client = TestClient(app)
    lista = client.get("/publicaciones", params={"plataforma": "youtube"}).json()
    detalle = client.get(f"/publicaciones/{pub['id']}").json()
    assert lista and "sesion_subida" not in lista[0] and "sesion_subida" not in detalle
