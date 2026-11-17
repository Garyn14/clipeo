"""
motor.py — La revisión periódica: al arrancar el backend y cada 10 min.

Las revisiones van alineadas al reloj (xx:00, xx:10, xx:20...) salvo la del arranque, para
que la hora de cada envío sea predecible (horarios.estimar, lo que muestra el panel).

Cada revisión (tick):
  1. Recupera envíos que quedaron "enviando" porque el proceso que los enviaba murió
     (reinicio del backend, --reload, PC apagada). Nunca reenvía a ciegas: si hay algo
     del lado de la plataforma (publish_id / sesión de subida) le pregunta en qué quedó.
  2. Reanuda cuentas cuya pausa venció.
  3. Por cada cuenta conectada, de cada plataforma, decide con horarios.decidir() y, si
     toca, envía UN clip. Cada (plataforma, nicho) es una cola independiente.
  4. Deja anotada la decisión (tabla revisiones) para que el panel muestre que el motor
     está vivo y por qué no envió.

Concurrencia: un candado en memoria serializa los ticks de este proceso (automático,
"Revisar ahora", "Enviar ahora"); entre procesos, cola.reclamar() + el índice único
parcial impiden que dos tomen el mismo clip o el mismo horario.
"""

import os
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.publicacion import cola, cuentas, db, horarios, tiktok, youtube
from app.publicacion.base import (
    ENTREGADO, FALLO, NO_SUBIDO, PAUSAR, RECONECTAR, REINTENTABLE, SIN_CONFIRMAR, ErrorEnvio,
)
from app.publicacion.simulado import PublicadorSimulado

# Cada módulo expone: Publicador*, necesita_renovar, renovar, NOMBRE, MENSAJE_ENTREGA
MODULOS = {"tiktok": tiktok, "youtube": youtube}
_PUBLICADORES = {"tiktok": tiktok.PublicadorTikTok, "youtube": youtube.PublicadorYouTube}

INTERVALO_S = horarios.REVISION_CADA_MIN * 60
MAX_REVISIONES = 500

_lock = threading.Lock()
_detener = threading.Event()
_hilo: threading.Thread | None = None


class EnvioNoPosible(Exception):
    pass


def _publicador(cuenta: dict):
    if cuenta["modo"] == "simulado":
        return PublicadorSimulado(cuenta["plataforma"])
    return _PUBLICADORES[cuenta["plataforma"]]()


def _nombre(plataforma: str) -> str:
    return MODULOS[plataforma].NOMBRE if plataforma in MODULOS else plataforma


def _registrador(conn, pub_id: int):
    def registrar(tipo: str, mensaje: str, detalle: dict | None = None) -> None:
        cola.registrar_evento(conn, pub_id, tipo, mensaje, detalle)
        if tipo == "chunk" and (detalle or {}).get("subida_completa"):
            cola.marcar_subida_completa(conn, pub_id)
    return registrar


def _proceso_vivo(pid: int | None, inicio: str | None) -> bool:
    if not pid or pid == os.getpid():
        return False   # este proceso tiene el candado: si figura como suyo, es de un intento anterior
    from app.services.pipeline_runner import _pid_vivo
    return _pid_vivo(pid, inicio)


def _anotar_revision(conn, plataforma: str, nicho: str, decision: str, envio: bool = False) -> None:
    momento = horarios.iso(horarios.ahora())
    ultima = conn.execute("SELECT * FROM revisiones WHERE plataforma = ? AND nicho = ? ORDER BY id DESC LIMIT 1",
                          (plataforma, nicho)).fetchone()
    if ultima and ultima["decision"] == decision and not envio and not ultima["envio"]:
        conn.execute("UPDATE revisiones SET hasta = ?, veces = veces + 1 WHERE id = ?", (momento, ultima["id"]))
        return
    conn.execute("INSERT INTO revisiones (plataforma, nicho, desde, hasta, decision, envio) VALUES (?,?,?,?,?,?)",
                 (plataforma, nicho, momento, momento, decision, int(envio)))
    conn.execute("DELETE FROM revisiones WHERE id <= (SELECT MAX(id) FROM revisiones) - ?", (MAX_REVISIONES,))


def _aplicar_error(conn, pub: dict, cuenta: dict, e: ErrorEnvio) -> None:
    detalle = {"codigo": e.codigo, **e.detalle}
    if e.tipo == PAUSAR:
        cuentas.pausar(conn, cuenta["id"], e.mensaje)
        cola.resolver(conn, pub["id"], "devolver", f"{e.mensaje} — la cuenta queda pausada", e.codigo, detalle)
    elif e.tipo == RECONECTAR:
        cuentas.requiere_reconexion(conn, cuenta["id"], e.mensaje)
        cola.resolver(conn, pub["id"], "devolver", f"{e.mensaje} — vuelve a la cola", e.codigo, detalle)
    elif e.tipo == REINTENTABLE:
        cola.resolver(conn, pub["id"], "reintentable", e.mensaje, e.codigo, detalle)
    elif e.tipo == SIN_CONFIRMAR:
        cola.resolver(conn, pub["id"], "sin_confirmar", e.mensaje, e.codigo, detalle)
    else:
        cola.resolver(conn, pub["id"], "error", e.mensaje, e.codigo, detalle)


def _asegurar_token(conn, cuenta: dict) -> dict:
    """Cuenta real: renueva el access token si está por vencer. Lanza ErrorEnvio."""
    modulo = MODULOS[cuenta["plataforma"]]
    if cuenta["modo"] != "real" or not modulo.necesita_renovar(cuenta):
        return cuenta
    if not cuenta.get("refresh_token"):
        raise ErrorEnvio(RECONECTAR, "sin_token", "La cuenta no tiene token — conectala desde el panel")
    try:
        tokens = modulo.renovar(cuenta["refresh_token"])
    except ValueError as e:   # faltan credenciales en Configuración
        raise ErrorEnvio(RECONECTAR, "sin_credenciales", str(e)) from e
    cola.registrar_evento(conn, None, "cuenta", "token de acceso renovado", cuenta_id=cuenta["id"])
    return cuentas.guardar_tokens(conn, cuenta["id"], tokens)


def _enviar(conn, pub: dict, cuenta: dict) -> dict:
    """Envía una publicación ya reclamada (estado enviando) y la deja resuelta."""
    registrar = _registrador(conn, pub["id"])
    ruta = Path(pub["ruta_video"])
    if not ruta.exists():
        return cola.resolver(conn, pub["id"], "error", f"No existe el archivo del clip: {ruta}", "archivo_no_existe")
    try:
        cuenta = _asegurar_token(conn, cuenta)
        _publicador(cuenta).enviar(
            ruta, cuenta, pub,
            on_publish_id=lambda publish_id: cola.guardar_publish_id(conn, pub["id"], publish_id),
            registrar=registrar,
            on_sesion=lambda url: cola.guardar_sesion_subida(conn, pub["id"], url),
        )
    except ErrorEnvio as e:
        _aplicar_error(conn, cola.obtener(conn, pub["id"]), cuenta, e)
    except Exception as e:  # bug o falla inesperada: decidir según si pudo haber llegado
        actual = cola.obtener(conn, pub["id"])
        detalle = {"excepcion": f"{type(e).__name__}: {e}"[:500], "traza": traceback.format_exc()[-1500:]}
        if actual["subida_completa"]:
            cola.resolver(conn, pub["id"], "sin_confirmar", f"Falla inesperada después de subir: {type(e).__name__}",
                          "excepcion", detalle)
        else:
            cola.resolver(conn, pub["id"], "reintentable", f"Falla inesperada antes de subir: {type(e).__name__}",
                          "excepcion", detalle)
    else:
        cola.resolver(conn, pub["id"], "en_bandeja", MODULOS[pub["plataforma"]].MENSAJE_ENTREGA)
    return cola.obtener(conn, pub["id"])


def recuperar(conn) -> None:
    """Envíos huérfanos (estado enviando cuyo proceso ya no existe)."""
    filas = conn.execute("SELECT * FROM publicaciones WHERE estado = 'enviando'").fetchall()
    for fila in filas:
        pub = dict(fila)
        if _proceso_vivo(pub["proceso_pid"], pub["proceso_inicio"]):
            continue
        nombre = _nombre(pub["plataforma"])
        cola.registrar_evento(conn, pub["id"], "recuperacion",
                              "el proceso que enviaba se interrumpió — verificando en qué quedó")
        if not pub["publish_id"] and not pub["sesion_subida"]:
            cola.resolver(conn, pub["id"], "reintentable",
                          f"se interrumpió antes de que {nombre} aceptara el envío (no llegó nada) — vuelve a la cola",
                          "interrumpido")
            continue
        cuenta = cuentas.por_nicho(conn, pub["nicho"], pub["plataforma"])
        if not cuenta:
            cola.resolver(conn, pub["id"], "sin_confirmar", "se interrumpió y la cuenta ya no existe", "interrumpido")
            continue
        try:
            cuenta = _asegurar_token(conn, cuenta)
            rec = _publicador(cuenta).recuperar(pub, cuenta, _registrador(conn, pub["id"]))
        except ErrorEnvio as e:
            cola.resolver(conn, pub["id"], "sin_confirmar",
                          f"se interrumpió y no se pudo consultar a {nombre}: {e.mensaje}", e.codigo)
            continue
        if rec.publish_id and rec.publish_id != pub["publish_id"]:
            cola.guardar_publish_id(conn, pub["id"], rec.publish_id)
        if rec.resultado == ENTREGADO:
            cola.resolver(conn, pub["id"], "en_bandeja", rec.mensaje)
        elif rec.resultado == FALLO:
            _aplicar_error(conn, pub, cuenta, rec.error)
        elif rec.resultado == NO_SUBIDO:
            cola.resolver(conn, pub["id"], "reintentable", f"{rec.mensaje} — vuelve a la cola", "interrumpido")
        else:
            cola.resolver(conn, pub["id"], "sin_confirmar", f"se interrumpió después de subir: {rec.mensaje}",
                          rec.error.codigo if rec.error else "interrumpido")


def _inicio_naive() -> str:
    # pipeline_runner._pid_vivo compara contra la hora local sin zona
    return datetime.now().isoformat(timespec="seconds")


def _revisar_cuenta(conn, cuenta: dict, momento: datetime) -> None:
    plataforma, nicho = cuenta["plataforma"], cuenta["nicho"]

    def anotar(decision: str, envio: bool = False) -> None:
        _anotar_revision(conn, plataforma, nicho, decision, envio)

    if cuenta["estado"] == "pausada":
        anotar(f"cuenta pausada hasta {cuenta['pausada_hasta']}: {cuenta['motivo']}")
        return
    if cuenta["estado"] != "conectada":
        anotar(f"cuenta sin enviar ({cuenta['estado']}): {cuenta['motivo'] or ''}".strip())
        return

    primero = cola.primero_en_cola(conn, nicho, plataforma)
    d = horarios.decidir(momento, cuenta["horarios"], cola.slots_ocupados(conn, nicho, plataforma),
                         cola.ultimo_envio(conn, nicho, plataforma), primero is not None)
    if not d.enviar:
        anotar(d.motivo)
        return
    if not cola.reclamar(conn, primero["id"], horarios.clave_slot(d.slot), _inicio_naive()):
        anotar("otro proceso tomó este horario — nada que hacer")
        return
    anotar(f"{d.motivo}: enviando {primero['clip_id']} ({primero['session_id']})", envio=True)
    _enviar(conn, cola.obtener(conn, primero["id"]), cuenta)


def tick() -> None:
    with _lock:
        conn = db.conectar()
        try:
            momento = horarios.ahora()
            recuperar(conn)
            cuentas.reanudar_vencidas(conn, momento)
            lista = cuentas.listar(conn)
            for cuenta in lista:
                # cada cuenta por separado: un error en una plataforma no frena a la otra
                try:
                    _revisar_cuenta(conn, cuenta, momento)
                except Exception as e:
                    traceback.print_exc()
                    _anotar_revision(conn, cuenta["plataforma"], cuenta["nicho"],
                                     f"error interno del motor: {type(e).__name__}: {e}")
            con_cuenta = {(c["plataforma"], c["nicho"]) for c in lista}
            for fila in conn.execute("SELECT plataforma, nicho, COUNT(*) AS n FROM publicaciones "
                                     "WHERE estado = 'en_cola' GROUP BY plataforma, nicho").fetchall():
                if (fila["plataforma"], fila["nicho"]) not in con_cuenta:
                    _anotar_revision(conn, fila["plataforma"], fila["nicho"],
                                     f"sin cuenta conectada: {fila['n']} clip(s) esperando en la cola")
        finally:
            conn.close()


def enviar_ahora(nicho: str, plataforma: str = "tiktok") -> dict:
    """Envío de prueba: el primero de la cola, sin esperar horario (respeta pausa/reconexión)."""
    with _lock:
        conn = db.conectar()
        try:
            recuperar(conn)
            cuenta = cuentas.por_nicho(conn, nicho, plataforma)
            if not cuenta:
                raise EnvioNoPosible(f"El nicho {nicho} no tiene cuenta de {_nombre(plataforma)} conectada")
            if cuenta["estado"] != "conectada":
                raise EnvioNoPosible(f"La cuenta está {cuenta['estado']}: {cuenta['motivo'] or ''}".strip())
            primero = cola.primero_en_cola(conn, nicho, plataforma)
            if not primero:
                raise EnvioNoPosible("La cola está vacía")
            if not cola.reclamar(conn, primero["id"], None, _inicio_naive()):
                raise EnvioNoPosible("Otro proceso tomó ese clip — probá de nuevo")
            _anotar_revision(conn, plataforma, nicho, f"envío de prueba a mano: {primero['clip_id']}", envio=True)
            return _enviar(conn, cola.obtener(conn, primero["id"]), cuenta)
        finally:
            conn.close()

# ── Hilo de fondo ────────────────────────────────────────────

def _bucle() -> None:
    # Revisión inmediata al arrancar (ponerse al día) y después alineada al reloj
    # (xx:00, xx:10...): así la hora de cada envío es predecible (horarios.estimar).
    while not _detener.is_set():
        try:
            tick()
        except Exception:
            traceback.print_exc()
        ahora = horarios.ahora()
        espera = (horarios.proxima_revision(ahora) - ahora).total_seconds() + 1
        _detener.wait(espera)


def iniciar() -> None:
    global _hilo
    if os.environ.get("PUBLICACION_MOTOR", "1") == "0" or (_hilo and _hilo.is_alive()):
        return
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, name="motor-publicacion", daemon=True)
    _hilo.start()


def detener() -> None:
    _detener.set()
