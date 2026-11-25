"""
vigilante.py — CLIP-88/89 (épica L1, CLIP-86): hilo del backend que vigila los directos de cada cliente.

En cada vuelta (al arrancar y cada DIRECTOS_INTERVALO_S, por defecto 600 s):
1. Revisa las cuentas activas de `investigacion/<nicho>/directos.yaml` que no se estén grabando. El chequeo pasa por
   tipos_directo (TikTok: Colab o local con cookies, con el espaciado global anti-bloqueo de tiktok_capture). Si una
   está en vivo, lanza `captura/grabador.py` en un proceso aparte (sin volver a verificar).
2. (CLIP-89) Procesa los trozos listos de cada captura: lanza el pipeline con la configuración del cliente, una sesión
   por trozo, y lo anota en el estado de la captura para no procesarlo dos veces.

DIRECTOS_MOTOR=0 lo apaga (tests, o si el operador no quiere vigilar).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from app.paths import PROJECT_ROOT, STREAM_DATA
from captura import directos, tipos_directo

INTERVALO_S = int(os.environ.get("DIRECTOS_INTERVALO_S", "600"))
LOG_DIR = PROJECT_ROOT / "backend" / "runs_logs" / "directos"

_hilo: threading.Thread | None = None
_detener = threading.Event()
_candado = threading.Lock()
_ultima_vuelta: dict = {"inicio": None, "fin": None, "resumen": ""}


def _vivo(pid, inicio) -> bool:
    if not pid:
        return False
    from app.services.pipeline_runner import _pid_vivo
    return _pid_vivo(int(pid), inicio)


def lanzar_grabador(nicho: str, cuenta: dict, verificar: bool = False) -> int:
    """Lanza el grabador de esa cuenta en un proceso aparte. Devuelve el pid."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", "-m", "captura.grabador", "--nicho", nicho,
           "--plataforma", cuenta["plataforma"], "--usuario", cuenta["usuario"],
           "--stream-data", str(STREAM_DATA), "--trozo-min", str(cuenta.get("trozo_min", directos.TROZO_MIN_DEFECTO))]
    if not verificar:
        cmd.append("--sin-verificar")
    log = LOG_DIR / f"{nicho}_{cuenta['usuario']}_{datetime.now():%Y%m%d_%H%M%S}.log"
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    with open(log, "w", encoding="utf-8") as salida:
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), stdin=subprocess.DEVNULL, stdout=salida,
                                stderr=subprocess.STDOUT, env=env, creationflags=flags)
    return proc.pid


def activa(nicho: str, cuenta: dict) -> dict | None:
    return directos.captura_activa(STREAM_DATA, nicho, cuenta["plataforma"], cuenta["usuario"], _vivo)


def revisar_cuenta(nicho: str, cuenta: dict) -> str:
    """Chequea una cuenta y graba si está en vivo. Devuelve lo que pasó (para el resumen de la vuelta)."""
    usuario, plataforma = cuenta["usuario"], cuenta["plataforma"]
    if activa(nicho, cuenta):
        return f"@{usuario}: ya se está grabando"
    try:
        tipo = tipos_directo.obtener(plataforma)
    except tipos_directo.DirectoError as e:
        directos.anotar_chequeo(STREAM_DATA, nicho, plataforma, usuario, None, str(e))
        return f"@{usuario}: {e}"
    en_vivo = tipo.en_vivo(usuario)
    detalle = {True: "en vivo", False: "no está en vivo", None: "no concluyente (bloqueo o error)"}[en_vivo]
    directos.anotar_chequeo(STREAM_DATA, nicho, plataforma, usuario, en_vivo, detalle)
    if en_vivo is True:
        pid = lanzar_grabador(nicho, cuenta)
        return f"@{usuario}: en vivo, grabando (pid {pid})"
    return f"@{usuario}: {detalle}"


def detener_captura(carpeta: str) -> None:
    ruta = STREAM_DATA / carpeta
    if not carpeta.startswith(directos.PREFIJO) or not (ruta / directos.ARCHIVO_ESTADO).exists():
        raise tipos_directo.DirectoError("Captura desconocida")
    (ruta / "detener.flag").write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")


def tick() -> str:
    """Una vuelta completa. Devuelve el resumen (también queda en estado())."""
    if not _candado.acquire(blocking=False):
        return "ya hay una vuelta en curso"
    try:
        _ultima_vuelta.update(inicio=datetime.now().isoformat(timespec="seconds"), fin=None)
        partes = []
        for nicho, cuenta in directos.cuentas_activas():
            try:
                partes.append(revisar_cuenta(nicho, cuenta))
            except Exception as e:  # noqa: BLE001 — una cuenta con problemas no frena a las demás
                traceback.print_exc()
                partes.append(f"@{cuenta.get('usuario')}: error {type(e).__name__}")
        partes += procesar_trozos()
        resumen = " · ".join(partes) or "sin cuentas de directo activas"
        _ultima_vuelta.update(fin=datetime.now().isoformat(timespec="seconds"), resumen=resumen)
        return resumen
    finally:
        _candado.release()


ARCHIVO_PROCESADOS = "procesados.json"   # lo escribe solo el vigilante (el grabador reescribe captura_estado.json)
MAX_PROCESOS = int(os.environ.get("DIRECTOS_MAX_PROCESOS", "2"))
BYTES_MINIMOS = 512 * 1024                # un trozo más chico no alcanza para un clip


def _procesar_activado(nicho: str, plataforma: str, usuario: str) -> bool:
    cuenta = next((c for c in directos.leer(nicho)["cuentas"]
                   if c.get("plataforma") == plataforma and c.get("usuario") == usuario), None)
    return True if cuenta is None else bool(cuenta.get("procesar", True))


def procesados(carpeta: str) -> dict:
    return directos.leer_json(STREAM_DATA / carpeta / ARCHIVO_PROCESADOS) or {}


def sesion_trozo(carpeta: str, trozo_id: str) -> str:
    """trozo_003 de directo_x_y_fecha → directo_x_y_fecha_c003 (una sesión por trozo)."""
    return f"{carpeta}_c{trozo_id.rsplit('_', 1)[-1]}"


def procesar_trozos() -> list[str]:
    """CLIP-89: lanza el pipeline de cada trozo listo que todavía no se procesó (a lo sumo MAX_PROCESOS a la vez).

    Las marcas van en procesados.json de la captura: un trozo se procesa una sola vez aunque el backend se reinicie."""
    from app.services import pipeline_runner

    en_curso = sum(1 for s in pipeline_runner.sesiones_activas() if s.startswith(directos.PREFIJO))
    partes = []
    for cap in sorted(directos.capturas(STREAM_DATA), key=lambda e: e.get("inicio") or ""):
        nicho, carpeta = cap.get("nicho"), cap["carpeta"]
        if not nicho or not _procesar_activado(nicho, cap.get("plataforma"), cap.get("usuario")):
            continue
        marcas = procesados(carpeta)
        for trozo in cap.get("trozos") or []:
            if trozo["id"] in marcas or trozo.get("estado") not in ("listo", "parcial"):
                continue
            if (trozo.get("bytes") or 0) < BYTES_MINIMOS:
                marcas[trozo["id"]] = {"omitido": "trozo demasiado corto", "ts": datetime.now().isoformat(timespec="seconds")}
                directos.escribir_json(STREAM_DATA / carpeta / ARCHIVO_PROCESADOS, marcas)
                continue
            if en_curso >= MAX_PROCESOS:
                partes.append("trozos en espera: ya hay suficientes procesándose")
                return partes
            sesion = sesion_trozo(carpeta, trozo["id"])
            run_id = pipeline_runner.launch_trozo(STREAM_DATA / carpeta / trozo["archivo"], sesion, nicho)
            marcas[trozo["id"]] = {"sesion": sesion, "run_id": run_id, "ts": datetime.now().isoformat(timespec="seconds")}
            directos.escribir_json(STREAM_DATA / carpeta / ARCHIVO_PROCESADOS, marcas)
            en_curso += 1
            partes.append(f"{trozo['id']} de @{cap.get('usuario')} al pipeline ({sesion})")
    return partes


def estado() -> dict:
    return {"activo": bool(_hilo and _hilo.is_alive()), "intervalo_s": INTERVALO_S, "ultima_vuelta": dict(_ultima_vuelta)}


def revisar_en_segundo_plano() -> None:
    threading.Thread(target=tick, name="directos-revision", daemon=True).start()


def _bucle() -> None:
    while not _detener.is_set():
        try:
            tick()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        _detener.wait(INTERVALO_S)


def iniciar() -> None:
    global _hilo
    if os.environ.get("DIRECTOS_MOTOR", "1") == "0" or (_hilo and _hilo.is_alive()):
        return
    _detener.clear()
    _hilo = threading.Thread(target=_bucle, name="vigilante-directos", daemon=True)
    _hilo.start()


def detener() -> None:
    _detener.set()


def ruta_captura(carpeta: str) -> Path:
    return STREAM_DATA / carpeta
