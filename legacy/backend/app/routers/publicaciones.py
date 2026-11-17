import os
import secrets
import threading
from datetime import datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.publicacion import cola, cuentas, db, horarios, motor, tiktok, youtube
from app.publicacion.base import ErrorEnvio
from app.publicacion.db import PLATAFORMAS

router = APIRouter(prefix="/publicaciones", tags=["publicaciones"])

ESTADO_OAUTH_VIGENCIA = timedelta(minutes=30)


class MoverBody(BaseModel):
    direccion: str            # "arriba" | "abajo"


class NichoBody(BaseModel):
    nicho: str
    plataforma: str = "tiktok"


class ConectarTikTokBody(BaseModel):
    nicho: str
    url_pegada: str


class HorariosBody(BaseModel):
    horarios: str             # "8,12,16,20"


def _publica(pub: dict) -> dict:
    """La publicación tal como la ve el panel: sin la URL de la sesión de subida (sirve para subir)."""
    return {k: v for k, v in pub.items() if k != "sesion_subida"}


def _con_eventos(conn, pub: dict) -> dict:
    return {**_publica(pub), "eventos": cola.eventos(conn, pub["id"])}


def _plataforma_valida(plataforma: str) -> str:
    if plataforma not in PLATAFORMAS:
        raise HTTPException(400, f"Plataforma desconocida: {plataforma}")
    return plataforma


def _estimaciones(conn, plataforma: str, nicho: str, cuenta: dict | None, momento: datetime) -> dict:
    """
    Cuándo sale cada clip de la cola, con las mismas reglas del motor (horarios.estimar):
      por_pub:        {pub_id: {"sale", "horario"}}
      motivo:         por qué no se puede estimar (sin cuenta / reconectar), o None
      siguiente_libre: si la cola está vacía, cuándo saldría un clip aprobado ahora
    """
    vacio = {"por_pub": {}, "motivo": None, "siguiente_libre": None}
    if cuenta is None:
        return {**vacio, "motivo": "sin cuenta conectada: los clips esperan en la cola"}
    if cuenta["estado"] == "requiere_reconexion":
        return {**vacio, "motivo": "hay que reconectar la cuenta para que se envíe algo"}
    en_cola = cola.listar(conn, nicho, "en_cola", plataforma=plataforma)
    pausa = (datetime.fromisoformat(cuenta["pausada_hasta"])
             if cuenta["estado"] == "pausada" and cuenta["pausada_hasta"] else None)
    salidas = horarios.estimar(momento, cuenta["horarios"], cola.slots_ocupados(conn, nicho, plataforma),
                               cola.ultimo_envio(conn, nicho, plataforma), max(len(en_cola), 1), pausa)
    if not en_cola:
        return {**vacio, "siguiente_libre": horarios.iso(salidas[0][0]) if salidas else None}
    return {**vacio, "por_pub": {
        p["id"]: {"sale": horarios.iso(sale), "horario": horarios.iso(slot)}
        for p, (sale, slot) in zip(en_cola, salidas)
    }}


_DONDE_VERIFICAR = {"tiktok": "verificá la bandeja en la app", "youtube": "verificá en YouTube Studio"}


def _alertas(plataforma: str, cuenta: dict | None, conteos: dict[str, int], dias_cola: float | None) -> list[dict]:
    alertas = []
    if cuenta is None:
        if conteos.get("en_cola"):
            alertas.append({"nivel": "warn", "texto": "Sin cuenta conectada: los clips esperan en la cola"})
    elif cuenta["estado"] == "requiere_reconexion":
        alertas.append({"nivel": "error", "texto": f"Hay que reconectar la cuenta: {cuenta['motivo']}"})
    elif cuenta["estado"] == "pausada":
        alertas.append({"nivel": "warn",
                        "texto": f"Cuenta pausada hasta {cuenta['pausada_hasta']}: {cuenta['motivo']}"})
    if conteos.get("error"):
        alertas.append({"nivel": "error", "texto": f"{conteos['error']} envío(s) con error sin resolver"})
    if conteos.get("sin_confirmar"):
        alertas.append({"nivel": "error",
                        "texto": f"{conteos['sin_confirmar']} envío(s) sin confirmar: {_DONDE_VERIFICAR[plataforma]}"})
    if cuenta and dias_cola is not None and dias_cola < 1:
        alertas.append({"nivel": "warn", "texto": "Queda menos de un día de clips en la cola"})
    return alertas


@router.get("/resumen")
def resumen():
    conn = db.conectar()
    try:
        momento = horarios.ahora()
        lista_cuentas = {(c["plataforma"], c["nicho"]): c for c in cuentas.listar(conn)}
        claves = set(lista_cuentas) | {
            (f["plataforma"], f["nicho"])
            for f in conn.execute("SELECT DISTINCT plataforma, nicho FROM publicaciones").fetchall()
        }
        salida = []
        # orden: por plataforma (como PLATAFORMAS) y nicho
        for plataforma, nicho in sorted(claves, key=lambda k: (PLATAFORMAS.index(k[0]) if k[0] in PLATAFORMAS else 99, k[1])):
            cuenta = lista_cuentas.get((plataforma, nicho))
            conteos = {f["estado"]: f["n"] for f in conn.execute(
                "SELECT estado, COUNT(*) AS n FROM publicaciones WHERE plataforma = ? AND nicho = ? GROUP BY estado",
                (plataforma, nicho))}
            horas = horarios.parsear_horarios(cuenta["horarios"]) if cuenta else None
            dias_cola = round(conteos.get("en_cola", 0) / len(horas), 1) if horas else None
            ultima = conn.execute("SELECT * FROM revisiones WHERE plataforma = ? AND nicho = ? ORDER BY id DESC LIMIT 1",
                                  (plataforma, nicho)).fetchone()
            est = _estimaciones(conn, plataforma, nicho, cuenta, momento)
            primero = cola.primero_en_cola(conn, nicho, plataforma)
            proximo = None
            if primero and primero["id"] in est["por_pub"]:
                proximo = {**est["por_pub"][primero["id"]], "id": primero["id"],
                           "clip_id": primero["clip_id"], "titulo": primero["titulo"]}
            salida.append({
                "plataforma": plataforma,
                "nicho": nicho,
                "cuenta": cuentas.publica(cuenta) if cuenta else None,
                "proximo_envio": proximo,
                "proximo_envio_motivo": est["motivo"],
                "siguiente_libre": est["siguiente_libre"],
                "proximo_horario": horarios.iso(horarios.proximo_slot(momento, horas)) if horas else None,
                "conteos": conteos,
                "dias_cola": dias_cola,
                "ultima_revision": dict(ultima) if ultima else None,
                "alertas": _alertas(plataforma, cuenta, conteos, dias_cola),
            })
        return {"ahora": horarios.iso(momento), "intervalo_s": motor.INTERVALO_S, "nichos": salida}
    finally:
        conn.close()


@router.get("")
def listar(nicho: str | None = None, estado: str | None = None, plataforma: str = "tiktok"):
    """Las publicaciones en cola traen sale_aprox / horario_estimado (ver _estimaciones)."""
    _plataforma_valida(plataforma)
    conn = db.conectar()
    try:
        pubs = cola.listar(conn, nicho, estado, plataforma=plataforma)
        momento = horarios.ahora()
        estimado: dict[int, dict] = {}
        for n in {p["nicho"] for p in pubs if p["estado"] == "en_cola"}:
            estimado.update(_estimaciones(conn, plataforma, n, cuentas.por_nicho(conn, n, plataforma),
                                          momento)["por_pub"])
        return [{**_publica(p), "sale_aprox": estimado.get(p["id"], {}).get("sale"),
                 "horario_estimado": estimado.get(p["id"], {}).get("horario")} for p in pubs]
    finally:
        conn.close()


@router.get("/revisiones")
def revisiones(nicho: str | None = None, plataforma: str = "tiktok", limite: int = 30):
    conn = db.conectar()
    try:
        sql, args = "SELECT * FROM revisiones WHERE plataforma = ?", [plataforma]
        if nicho:
            sql += " AND nicho = ?"
            args.append(nicho)
        sql += " ORDER BY id DESC LIMIT ?"
        return [dict(f) for f in conn.execute(sql, (*args, limite)).fetchall()]
    finally:
        conn.close()


@router.get("/{pub_id}")
def detalle(pub_id: int):
    conn = db.conectar()
    try:
        return _con_eventos(conn, cola.obtener(conn, pub_id))
    except cola.PublicacionNoEncontrada:
        raise HTTPException(404, "Publicación no encontrada")
    finally:
        conn.close()


def _accion(fn, pub_id: int, *args):
    conn = db.conectar()
    try:
        return _con_eventos(conn, fn(conn, pub_id, *args))
    except cola.PublicacionNoEncontrada:
        raise HTTPException(404, "Publicación no encontrada")
    except (cola.TransicionInvalida, ValueError) as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


@router.post("/{pub_id}/mover")
def mover(pub_id: int, body: MoverBody):
    return _accion(cola.mover, pub_id, body.direccion)


@router.post("/{pub_id}/quitar")
def quitar(pub_id: int):
    return _accion(cola.quitar, pub_id)


@router.post("/{pub_id}/reintentar")
def reintentar(pub_id: int):
    return _accion(cola.reintentar, pub_id)


@router.post("/{pub_id}/marcar-recibido")
def marcar_recibido(pub_id: int):
    return _accion(cola.marcar_recibido, pub_id)


@router.post("/acciones/revisar-ahora")
def revisar_ahora():
    """Lanza una revisión ya (en segundo plano: si hay un envío en curso, espera su turno)."""
    threading.Thread(target=motor.tick, name="revision-manual", daemon=True).start()
    return {"ok": True}


@router.post("/acciones/enviar-ahora")
def enviar_ahora(body: NichoBody):
    conn = db.conectar()
    try:
        pub = motor.enviar_ahora(body.nicho, _plataforma_valida(body.plataforma))
        return _con_eventos(conn, pub)
    except motor.EnvioNoPosible as e:
        raise HTTPException(409, str(e))
    finally:
        conn.close()


# ── Cuentas ──────────────────────────────────────────────────

@router.post("/cuentas/simulada")
def conectar_simulada(body: NichoBody):
    conn = db.conectar()
    try:
        return cuentas.publica(cuentas.conectar(conn, body.nicho, "simulado", nombre="Cuenta de prueba (simulada)",
                                                plataforma=_plataforma_valida(body.plataforma)))
    finally:
        conn.close()


@router.get("/cuentas/tiktok/autorizar")
def autorizar_tiktok(nicho: str):
    """URL para autorizar la app en TikTok. El state queda guardado para validar la vuelta."""
    state = secrets.token_urlsafe(24)
    try:
        url = tiktok.url_autorizacion(state)
    except ValueError as e:
        raise HTTPException(409, str(e))
    conn = db.conectar()
    try:
        conn.execute("INSERT INTO oauth_estados (state, nicho, creado) VALUES (?,?,?)",
                     (state, nicho, horarios.iso(horarios.ahora())))
        return {"url": url}
    finally:
        conn.close()


@router.post("/cuentas/tiktok/conectar")
def conectar_tiktok(body: ConectarTikTokBody):
    try:
        code, state = tiktok.leer_url_de_vuelta(body.url_pegada)
    except ValueError as e:
        raise HTTPException(400, str(e))
    conn = db.conectar()
    try:
        fila = conn.execute("SELECT * FROM oauth_estados WHERE state = ?", (state,)).fetchone()
        if not fila or fila["nicho"] != body.nicho:
            raise HTTPException(400, "La URL no corresponde a una autorización pedida desde este panel para este nicho")
        conn.execute("DELETE FROM oauth_estados WHERE state = ?", (state,))
        if horarios.ahora() - datetime.fromisoformat(fila["creado"]) > ESTADO_OAUTH_VIGENCIA:
            raise HTTPException(400, "La autorización venció (más de 30 min) — volvé a empezar")
        try:
            tokens = tiktok.canjear_codigo(code)
        except ErrorEnvio as e:
            raise HTTPException(502, e.mensaje)
        except ValueError as e:
            raise HTTPException(400, str(e))
        nombre = tiktok.nombre_usuario(tokens["access_token"])
        return cuentas.publica(cuentas.conectar(conn, body.nicho, "real", nombre=nombre, tokens=tokens))
    finally:
        conn.close()


FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")


@router.get("/cuentas/youtube/autorizar")
def autorizar_youtube(nicho: str):
    """URL para autorizar la app en Google. Google devuelve directo a /cuentas/youtube/callback."""
    state = "yt_" + secrets.token_urlsafe(24)
    try:
        url = youtube.url_autorizacion(state)
    except ValueError as e:
        raise HTTPException(409, str(e))
    conn = db.conectar()
    try:
        conn.execute("INSERT INTO oauth_estados (state, nicho, creado) VALUES (?,?,?)",
                     (state, nicho, horarios.iso(horarios.ahora())))
        return {"url": url}
    finally:
        conn.close()


def _conectar_youtube(code: str | None, state: str | None, error: str | None) -> None:
    """Valida la vuelta de Google y conecta la cuenta. ValueError con el motivo si algo falla."""
    if error:
        raise ValueError(f"Google no autorizó: {error}")
    if not code or not state or not state.startswith("yt_"):
        raise ValueError("La vuelta de Google no trae code/state válidos")
    conn = db.conectar()
    try:
        fila = conn.execute("SELECT * FROM oauth_estados WHERE state = ?", (state,)).fetchone()
        if not fila:
            raise ValueError("La autorización no corresponde a una pedida desde este panel")
        conn.execute("DELETE FROM oauth_estados WHERE state = ?", (state,))
        if horarios.ahora() - datetime.fromisoformat(fila["creado"]) > ESTADO_OAUTH_VIGENCIA:
            raise ValueError("La autorización venció (más de 30 min) — volvé a empezar")
        try:
            tokens = youtube.canjear_codigo(code)
        except ErrorEnvio as e:
            raise ValueError(e.mensaje) from e
        canal_id, nombre = youtube.canal(tokens["access_token"])
        cuentas.conectar(conn, fila["nicho"], "real", nombre=nombre, tokens={**tokens, "open_id": canal_id},
                         plataforma="youtube")
    finally:
        conn.close()


@router.get("/cuentas/youtube/callback")
def callback_youtube(code: str | None = None, state: str | None = None, error: str | None = None):
    """Vuelta de Google: conecta la cuenta y regresa al panel con el resultado."""
    try:
        _conectar_youtube(code, state, error)
        query = {"conexion": "ok"}
    except ValueError as e:
        query = {"conexion": "error", "motivo": str(e)}
    return RedirectResponse(f"{FRONTEND_URL}/publicaciones/youtube?{urlencode(query)}", status_code=303)


@router.post("/cuentas/{cuenta_id}/reanudar")
def reanudar(cuenta_id: int):
    conn = db.conectar()
    try:
        return cuentas.publica(cuentas.reanudar(conn, cuenta_id))
    except cuentas.CuentaNoEncontrada:
        raise HTTPException(404, "Cuenta no encontrada")
    finally:
        conn.close()


@router.post("/cuentas/{cuenta_id}/horarios")
def cambiar_horarios(cuenta_id: int, body: HorariosBody):
    conn = db.conectar()
    try:
        return cuentas.publica(cuentas.cambiar_horarios(conn, cuenta_id, body.horarios))
    except cuentas.CuentaNoEncontrada:
        raise HTTPException(404, "Cuenta no encontrada")
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()
