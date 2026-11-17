"""
state_reader.py — Lectura de sesiones (stream_data/<session_id>/) sin mutar nada.

La vista de cada sesión sale de los pasos de pipeline_estado.json (ver core/pasos.py):
pasos de sesión (descarga, plan, revision, fin) y por chunk (transcripcion, agente0..3,
corte). Dos ajustes solo de lectura:
  - Sesiones previas a los pasos: sus chunks completados se muestran con todos los pasos
    'ok', y los fallidos con el primer paso en 'error' (mensaje viejo del chunk).
  - Un paso 'corriendo' sin corrida viva sobre la sesión (el proceso murió a mitad) se
    muestra como 'interrumpido' — se retoma con "reanudar".
"""

import copy
import json
from datetime import datetime
from pathlib import Path

from app.paths import PROJECT_ROOT  # noqa: F401 — parchea sys.path antes de importar core/
from app.paths import STREAM_DATA
from app.services import pipeline_runner
from core.chunk_manager import PASOS_CHUNK, PASOS_SESION, completar_juez_previo, paso_vacio

_TERMINADOS = ("ok", "omitido")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _normalizar(estado: dict, activa: bool) -> tuple[dict, dict]:
    """Devuelve (pasos_sesion, chunks) listos para mostrar, sin tocar el archivo."""
    pasos  = copy.deepcopy(estado.get("pasos") or {})
    chunks = copy.deepcopy(estado.get("chunks") or {})
    legacy = "pasos" not in estado

    for p in PASOS_SESION:
        pasos.setdefault(p, paso_vacio())
    if legacy and chunks:
        for p in ("descarga", "plan"):
            pasos[p].update(estado="ok", nota="sesión previa al seguimiento por pasos")

    for chunk in chunks.values():
        cp = chunk.setdefault("pasos", {})
        completar_juez_previo(cp)
        for p in PASOS_CHUNK:
            cp.setdefault(p, paso_vacio())
        sin_historia = all(cp[p]["estado"] == "pendiente" for p in PASOS_CHUNK)
        if sin_historia and chunk.get("estado") == "completado":
            for p in PASOS_CHUNK:
                cp[p].update(estado="ok", nota="sesión previa al seguimiento por pasos")
        elif sin_historia and chunk.get("estado") == "fallido":
            cp[PASOS_CHUNK[0]].update(estado="error", error={
                "tipo": "Desconocido", "mensaje": chunk.get("error", "error sin detalle"),
                "reintentable": True, "detalle": "", "fecha": None,
            })

    if not activa:
        for paso in [*pasos.values(), *(p for c in chunks.values() for p in c["pasos"].values())]:
            if paso["estado"] == "corriendo":
                paso["estado"] = "interrumpido"
            # El intento en curso de un proceso que murió tampoco va a terminar
            for ev in paso.get("historial") or []:
                if ev.get("tipo") == "intento" and ev.get("resultado") == "corriendo":
                    ev["resultado"] = "interrumpido"

    if (chunks and all(c.get("estado") == "completado" for c in chunks.values())
            and pasos["revision"]["estado"] == "pendiente" and legacy):
        pasos["revision"]["estado"] = "esperando"

    return pasos, chunks


def _todos_los_pasos(pasos: dict, chunks: dict):
    for p in ("descarga", "plan"):
        yield None, p, pasos[p]
    for cid, c in chunks.items():
        for p in PASOS_CHUNK:
            yield cid, p, c["pasos"][p]
    for p in ("revision", "fin"):
        yield None, p, pasos[p]


def _estado_general(pasos: dict, chunks: dict, activa: bool) -> tuple[str, dict | None]:
    """(estado, paso_actual) — paso_actual = primer paso no terminado."""
    actual = None
    hay_error = False
    for cid, nombre, paso in _todos_los_pasos(pasos, chunks):
        if paso["estado"] == "error":
            hay_error = True
        if actual is None and paso["estado"] not in _TERMINADOS:
            actual = {"chunk": cid, "paso": nombre, "estado": paso["estado"]}

    if activa:
        return "corriendo", actual
    if hay_error:
        return "error", actual
    if pasos["fin"]["estado"] == "ok":
        return "finalizado", None
    if pasos["revision"]["estado"] == "esperando":
        return "esperando_revision", actual
    return "incompleto", actual


def _lead_time_s(estado: dict, pasos: dict, chunks: dict) -> int | None:
    creado = estado.get("creado")
    if not creado:
        return None
    fines = [p["fin"] for _, _, p in _todos_los_pasos(pasos, chunks) if p.get("fin")]
    try:
        inicio = datetime.fromisoformat(creado)
        fin    = datetime.fromisoformat(max(fines)) if fines else inicio
    except ValueError:
        return None
    return max(0, int((fin - inicio).total_seconds()))


def _session_summary(session_dir: Path, activas: dict[str, str]) -> dict:
    estado          = _read_json(session_dir / "pipeline_estado.json") or {}
    contenido_final = _read_json(session_dir / "contenido_final.json")
    activa          = session_dir.name in activas

    pasos, chunks = _normalizar(estado, activa)
    if estado:
        estado_gral, actual = _estado_general(pasos, chunks, activa)
    else:
        # Carpeta sin pipeline_estado.json: ej. una grabación de live (tiktok_capture.py)
        # cuyos chunk_NNN.mp4 todavía no se procesaron.
        estado_gral, actual = ("corriendo" if activa else "sin_procesar"), None

    total       = len(chunks)
    completados = sum(1 for c in chunks.values() if c.get("estado") == "completado")
    fallidos    = sum(1 for c in chunks.values() if c.get("estado") == "fallido")

    # Campo histórico (frontend v1): se mantiene
    if total == 0:
        progreso = "sin_chunks"
    elif fallidos:
        progreso = "con_errores"
    elif total - completados - fallidos:
        progreso = "en_curso"
    else:
        progreso = "completado"

    clips_a_publicar = sum(
        1 for c in (contenido_final or {}).get("contenido", []) if c.get("publicar")
    )

    return {
        "session_id":            session_dir.name,
        "url":                   estado.get("url", ""),
        "config":                estado.get("config", ""),
        "modo":                  estado.get("modo", ""),
        "creado":                estado.get("creado"),
        "video":                 estado.get("video"),
        "estado":                estado_gral,
        "paso_actual":           actual,
        "run_activo":            activas.get(session_dir.name),
        "lead_time_s":           _lead_time_s(estado, pasos, chunks),
        "chunks_total":          total,
        "chunks_completados":    completados,
        "chunks_fallidos":       fallidos,
        "progreso":              progreso,
        "tiene_contenido_final": contenido_final is not None,
        "clips_a_publicar":      clips_a_publicar,
    }


def list_sessions() -> list[dict]:
    if not STREAM_DATA.exists():
        return []
    activas = pipeline_runner.sesiones_activas()
    dirs = sorted(
        (d for d in STREAM_DATA.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )
    return [_session_summary(d, activas) for d in dirs]


def _video_desde_metadata(session_dir: Path) -> dict | None:
    """Sesiones previas al bloque `video` del estado: lo arma desde metadata.json (solo en el
    detalle — el archivo pesa cientos de KB y el listado se consulta cada pocos segundos)."""
    meta = _read_json(session_dir / "metadata.json")
    if not meta:
        return None
    return {
        "titulo":     meta.get("title") or meta.get("fulltitle") or "",
        "canal":      meta.get("uploader") or meta.get("channel") or "",
        "duracion_s": meta.get("duration"),
        "miniatura":  meta.get("thumbnail"),
    }


def get_session_detail(session_id: str) -> dict:
    session_dir = STREAM_DATA / session_id
    if not session_dir.exists():
        raise FileNotFoundError(session_id)

    activas         = pipeline_runner.sesiones_activas()
    estado          = _read_json(session_dir / "pipeline_estado.json") or {}
    contenido_final = _read_json(session_dir / "contenido_final.json") or {"contenido": []}
    pasos, chunks   = _normalizar(estado, session_id in activas)

    resumen = _session_summary(session_dir, activas)
    if not resumen["video"]:
        resumen["video"] = _video_desde_metadata(session_dir)

    return {
        **resumen,
        "pasos":     pasos,
        "chunks":    chunks,
        "contenido": contenido_final.get("contenido", []),
    }


def list_errores() -> list[dict]:
    """Todos los pasos en error de todas las sesiones (vista "Instancias con error")."""
    if not STREAM_DATA.exists():
        return []
    activas = pipeline_runner.sesiones_activas()
    filas = []
    for session_dir in sorted((d for d in STREAM_DATA.iterdir() if d.is_dir()), reverse=True):
        estado = _read_json(session_dir / "pipeline_estado.json")
        if not estado:
            continue
        pasos, chunks = _normalizar(estado, session_dir.name in activas)
        for cid, nombre, paso in _todos_los_pasos(pasos, chunks):
            if paso["estado"] != "error":
                continue
            error = paso.get("error") or {}
            filas.append({
                "session_id":   session_dir.name,
                "config":       estado.get("config", ""),
                "chunk":        cid,
                "paso":         nombre,
                "tipo":         error.get("tipo", ""),
                "mensaje":      error.get("mensaje", ""),
                "reintentable": bool(error.get("reintentable")),
                "fecha":        error.get("fecha") or paso.get("fin"),
                "intentos":     paso.get("intentos", 0),
                "run_activo":   session_dir.name in activas,
            })
    return filas
