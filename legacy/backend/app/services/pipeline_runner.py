"""
pipeline_runner.py — Lanza pipeline.py como subproceso y trackea sus corridas.

Siempre se lanza SIN --revisar (la revisión pasa por review_actions.py, post-hoc) y, en
modo --video, siempre con --colab (ver DECISIONES.md: se descartó WhisperX local para el
frontend).

El backend decide el session_id y se lo pasa al pipeline (--session-id): no hay que
descubrirlo después. Cada corrida queda registrada en runs_logs/runs.json (pid, sesión,
log), así que un reinicio del backend no pierde el rastro de una corrida en curso: el
subproceso sigue vivo (va en su propio grupo de procesos, un Ctrl+C a uvicorn no lo
alcanza) y se reconoce por pid al volver.

Una sesión admite una sola corrida viva a la vez (RunEnCursoError): dos procesos
escribiendo el mismo pipeline_estado.json se pisarían.
"""

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from app.paths import PROJECT_ROOT, STREAM_DATA
from core.chunk_manager import reemplazar_con_reintentos

RUNS_LOG_DIR = PROJECT_ROOT / "backend" / "runs_logs"
RUNS_LOG_DIR.mkdir(parents=True, exist_ok=True)
RUNS_FILE = RUNS_LOG_DIR / "runs.json"

_procs: dict[str, subprocess.Popen] = {}   # handles de corridas lanzadas por ESTE proceso
_lock = threading.Lock()


class RunEnCursoError(Exception):
    def __init__(self, session_id: str, run_id: str):
        super().__init__(f"La sesión {session_id} ya tiene una corrida en curso ({run_id})")
        self.session_id = session_id
        self.run_id     = run_id


# ── Registro persistente ─────────────────────────────────────

def _cargar_runs() -> dict[str, dict]:
    if not RUNS_FILE.exists():
        return {}
    try:
        return json.loads(RUNS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _guardar_runs(runs: dict[str, dict]) -> None:
    tmp = RUNS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    reemplazar_con_reintentos(tmp, RUNS_FILE)


# Margen entre que el backend crea el proceso y anota la hora de inicio de la corrida
_MARGEN_INICIO_S = 60


def _inicio_proceso_win(pid: int) -> datetime | None:
    """Hora de creación del proceso (Windows), o None si no existe / no se puede consultar."""
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        if code.value != 259:  # STILL_ACTIVE
            return None
        creado, salida, kern, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(creado), ctypes.byref(salida),
                                        ctypes.byref(kern), ctypes.byref(user)):
            return None
        ticks = (creado.dwHighDateTime << 32) | creado.dwLowDateTime  # 100 ns desde 1601-01-01 UTC
        return datetime.fromtimestamp((ticks - 116444736000000000) / 1e7)
    finally:
        kernel32.CloseHandle(handle)


def _pid_vivo(pid: int, inicio_run: str | None = None) -> bool:
    """
    ¿Sigue vivo el proceso de la corrida? Windows reutiliza los PID: un pid guardado hace
    días puede ser hoy otro programa (pasó con OpenConsole.exe de VS Code). Si el proceso
    con ese pid se creó bastante después de que empezó la corrida, no es el nuestro.
    """
    if sys.platform == "win32":
        # os.kill(pid, 0) en Windows manda CTRL_C_EVENT — no sirve para sondear.
        creado = _inicio_proceso_win(pid)
        if creado is None:
            return False
        if inicio_run:
            try:
                if (creado - datetime.fromisoformat(inicio_run)).total_seconds() > _MARGEN_INICIO_S:
                    return False  # pid reutilizado por otro proceso
            except ValueError:
                pass
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _returncode(run_id: str, run: dict) -> int | None:
    """None si sigue corriendo; el código de salida si terminó (o -1 si no se conoce)."""
    proc = _procs.get(run_id)
    if proc is not None:
        return proc.poll()
    if run.get("returncode") is not None:
        return run["returncode"]
    return None if _pid_vivo(run["pid"], run.get("inicio")) else -1


# ── Lanzar ───────────────────────────────────────────────────

def _nuevo_session_id() -> str:
    """
    Reserva un session_id nuevo creando su carpeta. Bajo el candado y con mkdir sin
    exist_ok: dos lanzamientos en el mismo segundo (ej. doble click) reciben ids distintos
    en vez de compartir uno (el segundo fallaba con 409).
    """
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id, n = base, 2
    with _lock:
        while True:
            try:
                (STREAM_DATA / session_id).mkdir(parents=True)
                return session_id
            except FileExistsError:
                session_id = f"{base}_{n}"
                n += 1


def _estado_sesion(session_id: str) -> dict:
    path = STREAM_DATA / session_id / "pipeline_estado.json"
    if not path.exists():
        raise FileNotFoundError(session_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _cmd_sesion(session_id: str, estado: dict) -> list[str]:
    """Comando que retoma una sesión existente, con los mismos datos con que se lanzó."""
    cmd = [sys.executable, "-u", str(PROJECT_ROOT / "pipeline.py")]
    if estado.get("modo") == "test":
        cmd += ["--test", str(STREAM_DATA / session_id)]
    else:
        cmd += ["--video", estado.get("url", ""), "--session-id", session_id, "--colab"]
    if estado.get("config") and estado["config"] != "default":
        cmd += ["--config", estado["config"]]
    return cmd


def _lanzar(cmd: list[str], session_id: str, accion: str) -> str:
    with _lock:
        activa = run_activa(session_id)
        if activa:
            raise RunEnCursoError(session_id, activa)

        run_id   = uuid.uuid4().hex[:12]
        log_path = RUNS_LOG_DIR / f"{run_id}.log"
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0

        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT),
                stdin=subprocess.DEVNULL,  # nunca esperar un input() de terminal
                stdout=log_file, stderr=subprocess.STDOUT,
                env=env, creationflags=flags,
            )
        _procs[run_id] = proc

        runs = _cargar_runs()
        runs[run_id] = {
            "run_id":     run_id,
            "pid":        proc.pid,
            "session_id": session_id,
            "accion":     accion,
            "cmd":        cmd,
            "log_path":   str(log_path),
            "inicio":     datetime.now().isoformat(timespec="seconds"),
            "returncode": None,
        }
        _guardar_runs(runs)
        return run_id


def launch_run(modo: str, url_o_path: str, canal_id: str | None) -> dict:
    """Corrida nueva. Devuelve {run_id, session_id}."""
    cmd = [sys.executable, "-u", str(PROJECT_ROOT / "pipeline.py")]
    if modo == "test":
        test_dir   = Path(url_o_path)
        session_id = test_dir.name
        cmd += ["--test", str(test_dir)]
    else:
        # La carpeta existe desde ya (la crea _nuevo_session_id): el frontend navega al
        # detalle de inmediato, y el pipeline tarda ~1 s en arrancar.
        session_id = _nuevo_session_id()
        cmd += ["--video", url_o_path, "--session-id", session_id, "--colab"]
    if canal_id:
        cmd += ["--config", canal_id]
    return {"run_id": _lanzar(cmd, session_id, "nueva"), "session_id": session_id}


def relaunch(session_id: str, reintentar: str | None = None, chunks: list[str] | None = None) -> str:
    """Retoma una sesión: reanudar pendientes, o --reintentar un paso (y los siguientes)."""
    estado = _estado_sesion(session_id)
    cmd    = _cmd_sesion(session_id, estado)
    if reintentar:
        cmd += ["--reintentar", reintentar]
        if chunks:
            cmd += ["--chunk", ",".join(chunks)]
    accion = f"reintentar {reintentar}" + (f" ({', '.join(chunks)})" if chunks else "") if reintentar else "reanudar"
    return _lanzar(cmd, session_id, accion)


# ── Consultar ────────────────────────────────────────────────

def sesiones_activas() -> dict[str, str]:
    """{session_id: run_id} de todas las corridas vivas."""
    return {
        run["session_id"]: run_id
        for run_id, run in _cargar_runs().items()
        if run.get("session_id") and _returncode(run_id, run) is None
    }


def run_activa(session_id: str) -> str | None:
    """run_id de la corrida viva sobre esta sesión, si hay una."""
    for run_id, run in _cargar_runs().items():
        if run.get("session_id") == session_id and _returncode(run_id, run) is None:
            return run_id
    return None


def _tail(log_path: Path, n: int = 40) -> str:
    if not log_path.exists():
        return ""
    lineas = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lineas[-n:])


def get_run(run_id: str, lineas_log: int = 40) -> dict:
    runs = _cargar_runs()
    run  = runs.get(run_id)
    if run is None:
        raise KeyError(run_id)

    retcode = _returncode(run_id, run)
    if retcode is not None and run.get("returncode") is None and retcode != -1:
        run["returncode"] = retcode
        runs[run_id] = run
        _guardar_runs(runs)

    if retcode is None:
        estado = "corriendo"
    elif retcode == 0:
        estado = "completado"
    elif retcode == -1:
        estado = "terminado"   # el backend se reinició y no vio el código de salida
    else:
        estado = "fallido"

    return {
        "run_id":     run_id,
        "estado":     estado,
        "session_id": run.get("session_id"),
        "accion":     run.get("accion", ""),
        "inicio":     run.get("inicio"),
        "tail_log":   _tail(Path(run["log_path"]), lineas_log),
    }


def list_runs(session_id: str | None = None) -> list[dict]:
    runs = _cargar_runs()
    ids  = [rid for rid, r in runs.items() if session_id is None or r.get("session_id") == session_id]
    ids.sort(key=lambda rid: runs[rid].get("inicio") or "", reverse=True)
    return [get_run(rid) for rid in ids]
