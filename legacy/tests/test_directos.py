"""
test_directos.py — CLIP-88 (épica L1, CLIP-86): tipos de directo, cuentas por cliente, grabador y vigilante.

Sin red ni procesos: la detección de "en vivo" y yt-dlp se simulan.
"""

import json
import os
import sys
from pathlib import Path

import pytest

os.environ["DIRECTOS_MOTOR"] = "0"
os.environ["PUBLICACION_MOTOR"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from captura import directos, grabador, tipos_directo  # noqa: E402
from investigacion import comun  # noqa: E402


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    """investigacion/ y stream_data/ temporales (nunca los reales)."""
    monkeypatch.setattr(comun, "RAIZ", tmp_path)
    (tmp_path / "investigacion" / "zapatillas_peru").mkdir(parents=True)
    (tmp_path / "investigacion" / "zapatillas_peru" / "fuentes.yaml").write_text("cliente: Tío Fritz\n", encoding="utf-8")
    stream = tmp_path / "stream_data"
    stream.mkdir()
    return tmp_path, stream


# ── tipos de directo ──

def test_tiktok_normaliza_usuario_y_url():
    t = tipos_directo.obtener("tiktok")
    assert t.normalizar_usuario("@FritzSport") == "fritzsport"
    assert t.normalizar_usuario("https://www.tiktok.com/@fritz.sport/live") == "fritz.sport"
    assert t.url("fritzsport") == "https://www.tiktok.com/@fritzsport/live"
    with pytest.raises(tipos_directo.DirectoError):
        t.normalizar_usuario("no vale con espacios")


def test_plataformas_proximamente_no_se_pueden_usar():
    assert tipos_directo.REGISTRO["kick"].disponible is False
    with pytest.raises(tipos_directo.DirectoError):
        tipos_directo.obtener("kick")
    with pytest.raises(tipos_directo.DirectoError):
        tipos_directo.obtener("inventada")


def test_tiktok_no_concluyente_nunca_es_no_en_vivo(monkeypatch):
    from captura import tiktok_capture

    def bloqueado(url):
        raise RuntimeError("bloqueado por el WAF")
    monkeypatch.setattr(tiktok_capture, "verificar_live_activo", bloqueado)
    assert tipos_directo.obtener("tiktok").en_vivo("fritzsport") is None
    monkeypatch.setattr(tiktok_capture, "verificar_live_activo", lambda url: False)
    assert tipos_directo.obtener("tiktok").en_vivo("fritzsport") is False


# ── cuentas por cliente ──

def test_agregar_pausar_y_quitar_cuenta(raiz):
    tmp, _ = raiz
    c = directos.agregar("zapatillas_peru", "tiktok", "@FritzSport", trozo_min=20)
    assert c == {"plataforma": "tiktok", "usuario": "fritzsport", "activo": True, "trozo_min": 20, "procesar": True}
    assert (tmp / "investigacion" / "zapatillas_peru" / "directos.yaml").exists()
    with pytest.raises(tipos_directo.DirectoError):
        directos.agregar("zapatillas_peru", "tiktok", "fritzsport")         # repetida
    assert directos.cuentas_activas() == [("zapatillas_peru", c)]

    directos.actualizar("zapatillas_peru", "tiktok", "fritzsport", activo=False, procesar=None, trozo_min=None)
    assert directos.cuentas_activas() == []
    with pytest.raises(tipos_directo.DirectoError):
        directos.actualizar("zapatillas_peru", "tiktok", "fritzsport", trozo_min=500)

    directos.quitar("zapatillas_peru", "tiktok", "fritzsport")
    assert directos.leer("zapatillas_peru")["cuentas"] == []
    assert directos.clientes() == ["zapatillas_peru"]


def test_chequeos_se_anotan_por_cuenta(raiz):
    _, stream = raiz
    directos.anotar_chequeo(stream, "zapatillas_peru", "tiktok", "fritzsport", None, "bloqueo")
    ch = directos.chequeos(stream)["zapatillas_peru/tiktok/fritzsport"]
    assert ch["en_vivo"] is None and ch["detalle"] == "bloqueo"


# ── grabador ──

class _ProcesoFalso:
    """yt-dlp simulado: escribe el archivo destino y termina solo después de `dura` sondeos (None = nunca)."""
    def __init__(self, destino: Path, dura):
        self.destino, self.dura, self.sondeos, self.matado = destino, dura, 0, False
        destino.write_bytes(b"\x00" * 1024)

    def poll(self):
        self.sondeos += 1
        if self.matado:
            return -9
        return 0 if self.dura is not None and self.sondeos > self.dura else None


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _grabador(stream, monkeypatch, duraciones, en_vivo, trozo_min=1):
    reloj = _Reloj()
    procesos = []

    def lanzar(cmd, **kw):
        p = _ProcesoFalso(Path(cmd[cmd.index("-o") + 1]), duraciones[len(procesos)] if len(procesos) < len(duraciones) else 0)
        procesos.append(p)
        return p

    def dormir(s):
        reloj.t += s

    respuestas = list(en_vivo)
    t = tipos_directo.obtener("tiktok")
    monkeypatch.setattr(t, "en_vivo", lambda u: respuestas.pop(0))
    monkeypatch.setattr(grabador.Grabador, "_detener_proceso", lambda self, proc: setattr(proc, "matado", True))
    g = grabador.Grabador("zapatillas_peru", "tiktok", "fritzsport", stream, trozo_min,
                          lanzar=lanzar, dormir=dormir, reloj=reloj)
    return g, procesos


def test_graba_trozos_por_tiempo_hasta_que_el_directo_termina(raiz, monkeypatch):
    _, stream = raiz
    # trozo 1 y 2 se cortan por tiempo (nunca terminan solos); el 3 termina solo y el directo ya no está
    g, procesos = _grabador(stream, monkeypatch, [None, None, 3], en_vivo=[True, False])
    estado = g.correr(verificar=True)
    assert estado["estado"] == "terminado"
    assert [t["id"] for t in estado["trozos"]] == ["trozo_001", "trozo_002", "trozo_003"]
    assert all(t["estado"] == "listo" and t["sesion"] is None for t in estado["trozos"])
    guardado = json.loads((g.carpeta / directos.ARCHIVO_ESTADO).read_text(encoding="utf-8"))
    assert guardado["estado"] == "terminado" and len(guardado["trozos"]) == 3


def test_corte_con_directo_activo_reintenta(raiz, monkeypatch):
    _, stream = raiz
    g, procesos = _grabador(stream, monkeypatch, [2, 2], en_vivo=[True, False])
    estado = g.correr(verificar=False)
    assert len(procesos) == 2 and estado["estado"] == "terminado"


def test_no_concluyente_tras_un_corte_termina_con_error(raiz, monkeypatch):
    _, stream = raiz
    g, _ = _grabador(stream, monkeypatch, [2], en_vivo=[None])
    assert g.correr(verificar=False)["estado"] == "error"


def test_detener_desde_el_panel_deja_el_trozo_parcial(raiz, monkeypatch):
    _, stream = raiz
    g, procesos = _grabador(stream, monkeypatch, [None], en_vivo=[])
    (g.carpeta / grabador.FLAG_DETENER).write_text("ya", encoding="utf-8")
    estado = g.correr(verificar=False)
    assert estado["estado"] == "detenido" and estado["trozos"][0]["estado"] == "parcial"
    assert procesos[0].matado


def test_sin_directo_no_graba(raiz, monkeypatch):
    _, stream = raiz
    g, procesos = _grabador(stream, monkeypatch, [], en_vivo=[False])
    assert g.correr(verificar=True)["estado"] == "sin_directo" and procesos == []


# ── vigilante y API ──

@pytest.fixture
def vig(raiz, monkeypatch):
    from app.directos import vigilante
    _, stream = raiz
    monkeypatch.setattr(vigilante, "STREAM_DATA", stream)
    lanzados = []
    monkeypatch.setattr(vigilante, "lanzar_grabador", lambda nicho, cuenta, verificar=False: lanzados.append(
        (nicho, cuenta["usuario"], verificar)) or 4242)
    return vigilante, lanzados


def test_vigilante_graba_solo_si_esta_en_vivo(vig, monkeypatch):
    vigilante, lanzados = vig
    directos.agregar("zapatillas_peru", "tiktok", "fritzsport")
    directos.agregar("zapatillas_peru", "tiktok", "otro")
    t = tipos_directo.obtener("tiktok")
    monkeypatch.setattr(t, "en_vivo", lambda u: {"fritzsport": True, "otro": None}[u])
    resumen = vigilante.tick()
    assert lanzados == [("zapatillas_peru", "fritzsport", False)]
    assert "no concluyente" in resumen
    ch = directos.chequeos(vigilante.STREAM_DATA)
    assert ch["zapatillas_peru/tiktok/fritzsport"]["en_vivo"] is True
    assert ch["zapatillas_peru/tiktok/otro"]["en_vivo"] is None


def test_vigilante_no_relanza_una_captura_en_curso(vig, monkeypatch):
    vigilante, lanzados = vig
    directos.agregar("zapatillas_peru", "tiktok", "fritzsport")
    carpeta = vigilante.STREAM_DATA / directos.nombre_captura("zapatillas_peru", "fritzsport")
    directos.escribir_json(carpeta / directos.ARCHIVO_ESTADO, {
        "nicho": "zapatillas_peru", "plataforma": "tiktok", "usuario": "fritzsport", "estado": "grabando",
        "pid": 123, "inicio": "2026-11-25T01:00:00", "trozos": []})
    monkeypatch.setattr(vigilante, "_vivo", lambda pid, inicio: True)
    monkeypatch.setattr(tipos_directo.obtener("tiktok"), "en_vivo", lambda u: pytest.fail("no debía chequear"))
    assert "ya se está grabando" in vigilante.tick()
    assert lanzados == []


def test_api_cuentas_y_detener(vig, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import directos as router
    vigilante, lanzados = vig
    monkeypatch.setattr(router, "STREAM_DATA", vigilante.STREAM_DATA)
    c = TestClient(app)

    assert c.post("/directos/zapatillas_peru/cuentas", json={"usuario": "@FritzSport"}).status_code == 200
    assert c.post("/directos/zapatillas_peru/cuentas", json={"usuario": "fritzsport"}).status_code == 400
    r = c.get("/directos").json()
    cliente = next(x for x in r["clientes"] if x["nicho"] == "zapatillas_peru")
    assert cliente["cliente"] == "Tío Fritz" and cliente["cuentas"][0]["usuario"] == "fritzsport"
    assert any(p["clave"] == "tiktok" and p["disponible"] for p in r["plataformas"])

    assert c.patch("/directos/zapatillas_peru/cuentas/tiktok/fritzsport", json={"activo": False}).json()["activo"] is False
    assert c.post("/directos/zapatillas_peru/cuentas/tiktok/fritzsport/grabar").json() == {"pid": 4242}
    assert lanzados == [("zapatillas_peru", "fritzsport", False)]

    carpeta = directos.nombre_captura("zapatillas_peru", "fritzsport")
    directos.escribir_json(vigilante.STREAM_DATA / carpeta / directos.ARCHIVO_ESTADO, {"nicho": "zapatillas_peru"})
    assert c.post(f"/directos/capturas/{carpeta}/detener").status_code == 200
    assert (vigilante.STREAM_DATA / carpeta / "detener.flag").exists()
    assert c.post("/directos/capturas/otra_cosa/detener").status_code == 404

    assert c.delete("/directos/zapatillas_peru/cuentas/tiktok/fritzsport").status_code == 200


# ── CLIP-89: cada trozo entra solo al pipeline ──

def _captura_con_trozos(stream, trozos, usuario="fritzsport"):
    carpeta = directos.nombre_captura("zapatillas_peru", usuario)
    directos.escribir_json(stream / carpeta / directos.ARCHIVO_ESTADO, {
        "nicho": "zapatillas_peru", "plataforma": "tiktok", "usuario": usuario, "estado": "terminado",
        "pid": 1, "inicio": "2026-11-25T01:00:00", "trozos": trozos})
    return carpeta


def _trozo(n, bytes_=5_000_000, estado="listo"):
    return {"id": f"trozo_{n:03d}", "archivo": f"trozo_{n:03d}.mp4", "bytes": bytes_, "estado": estado, "sesion": None}


@pytest.fixture
def pipeline(monkeypatch):
    from app.services import pipeline_runner
    lanzadas, activas = [], {}
    monkeypatch.setattr(pipeline_runner, "launch_trozo",
                        lambda video, sesion, canal: lanzadas.append((Path(video).name, sesion, canal)) or f"run{len(lanzadas)}")
    monkeypatch.setattr(pipeline_runner, "sesiones_activas", lambda: activas)
    return lanzadas, activas


def test_trozos_listos_van_al_pipeline_una_sola_vez(vig, pipeline):
    vigilante, _ = vig
    lanzadas, _ = pipeline
    directos.agregar("zapatillas_peru", "tiktok", "fritzsport")
    carpeta = _captura_con_trozos(vigilante.STREAM_DATA, [_trozo(1), _trozo(2, estado="parcial"), _trozo(3, bytes_=100)])
    vigilante.procesar_trozos()
    assert lanzadas == [("trozo_001.mp4", f"{carpeta}_c001", "zapatillas_peru"),
                        ("trozo_002.mp4", f"{carpeta}_c002", "zapatillas_peru")]
    marcas = vigilante.procesados(carpeta)
    assert marcas["trozo_001"]["sesion"] == f"{carpeta}_c001" and "omitido" in marcas["trozo_003"]
    vigilante.procesar_trozos()                     # segunda vuelta: nada nuevo
    assert len(lanzadas) == 2


def test_respeta_el_maximo_de_procesos_y_la_opcion_de_no_procesar(vig, pipeline, monkeypatch):
    vigilante, _ = vig
    lanzadas, activas = pipeline
    monkeypatch.setattr(vigilante, "MAX_PROCESOS", 1)
    directos.agregar("zapatillas_peru", "tiktok", "fritzsport")
    _captura_con_trozos(vigilante.STREAM_DATA, [_trozo(1), _trozo(2)])
    vigilante.procesar_trozos()
    assert len(lanzadas) == 1                       # el segundo espera
    activas.clear()
    vigilante.procesar_trozos()
    assert len(lanzadas) == 2

    directos.agregar("zapatillas_peru", "tiktok", "solograbar", procesar=False)
    _captura_con_trozos(vigilante.STREAM_DATA, [_trozo(1)], usuario="solograbar")
    vigilante.procesar_trozos()
    assert len(lanzadas) == 2


def test_api_muestra_la_sesion_de_cada_trozo(vig, pipeline, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import directos as router
    vigilante, _ = vig
    monkeypatch.setattr(router, "STREAM_DATA", vigilante.STREAM_DATA)
    monkeypatch.setattr(vigilante, "_vivo", lambda pid, inicio: False)
    directos.agregar("zapatillas_peru", "tiktok", "fritzsport")
    carpeta = _captura_con_trozos(vigilante.STREAM_DATA, [_trozo(1)])
    vigilante.procesar_trozos()
    cliente = next(x for x in TestClient(app).get("/directos").json()["clientes"] if x["nicho"] == "zapatillas_peru")
    assert cliente["capturas"][0]["trozos"][0]["sesion"] == f"{carpeta}_c001"


def test_si_yt_dlp_dice_que_no_esta_en_vivo_termina_sin_otra_consulta(raiz, monkeypatch):
    """Prueba real (CLIP-89): con el WAF bloqueando la consulta, un "not currently live" de yt-dlp ya es concluyente."""
    _, stream = raiz
    g, _ = _grabador(stream, monkeypatch, [2], en_vivo=[])
    (g.carpeta / "yt-dlp.log").write_text(
        "\n--- trozo_001.mp4 x ---\nERROR: [tiktok:live] fritzsport: The channel is not currently live\n", encoding="utf-8")
    monkeypatch.setattr(grabador.Grabador, "_grabar_trozo", lambda self, ruta: ("termino", 1))
    assert g.correr(verificar=False)["estado"] == "terminado"
