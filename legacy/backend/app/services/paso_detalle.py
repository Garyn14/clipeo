"""
paso_detalle.py — Detalle de un paso para el modal de la web: estado, error, salidas y las
llamadas de IA (REQUEST/RESPONSE) que el pipeline dejó en trazas/<paso>/ (ver
ai_client/client.py, PIPELINE_TRACE_DIR).
"""

import json
from pathlib import Path

from app.paths import STREAM_DATA
from app.services import pipeline_runner
from app.services.state_reader import _normalizar, _read_json
from core.chunk_manager import PASOS_CHUNK, PASOS_SESION

_MAX_TEXTO = 60_000  # caracteres por bloque mostrado (una transcripción de 30 min ronda 30k)


class PasoNoEncontradoError(Exception):
    pass


def _recortar(texto: str) -> str:
    if len(texto) <= _MAX_TEXTO:
        return texto
    return texto[:_MAX_TEXTO] + f"\n\n… [recortado: {len(texto) - _MAX_TEXTO:,} caracteres más]"


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    partes = []
    for bloque in contenido or []:
        if isinstance(bloque, dict) and bloque.get("type") == "text":
            partes.append(bloque.get("text", ""))
    return "\n\n".join(partes)


def _llamadas(trace_dir: Path) -> list[dict]:
    if not trace_dir.exists():
        return []
    llamadas = []
    for req_path in sorted(trace_dir.glob("*_request.json")):
        n   = req_path.name.split("_", 1)[0]
        req = _read_json(req_path) or {}
        res = _read_json(trace_dir / f"{n}_response.json")
        err = _read_json(trace_dir / f"{n}_error.json")
        llamadas.append({
            "n":        int(n),
            "request": {
                "modelo":   req.get("model"),
                "system":   _recortar(_texto(req.get("system"))),
                "mensajes": _recortar("\n\n".join(_texto(m.get("content")) for m in req.get("messages", []))),
            },
            "response": None if res is None else {
                "texto":      _recortar(res.get("text", "")),
                "duracion_s": res.get("duracion_s"),
                "meta":       res.get("meta"),
            },
            "error": err,
        })
    return llamadas


def _salidas(session_dir: Path, rutas: list[str]) -> list[dict]:
    resultado = []
    for rel in rutas:
        p = session_dir / rel
        resultado.append({
            "ruta":   rel,
            "existe": p.exists(),
            "bytes":  p.stat().st_size if p.exists() and p.is_file() else None,
        })
    return resultado


def get_paso(session_id: str, chunk_id: str | None, nombre: str) -> dict:
    session_dir = STREAM_DATA / session_id
    estado = _read_json(session_dir / "pipeline_estado.json")
    if estado is None:
        raise PasoNoEncontradoError(f"Sesión sin estado: {session_id}")

    activa = pipeline_runner.run_activa(session_id) is not None
    pasos, chunks = _normalizar(estado, activa)

    if chunk_id is None:
        if nombre not in PASOS_SESION:
            raise PasoNoEncontradoError(nombre)
        paso, trace_dir = pasos[nombre], None
    else:
        if chunk_id not in chunks or nombre not in PASOS_CHUNK:
            raise PasoNoEncontradoError(f"{chunk_id}/{nombre}")
        paso = chunks[chunk_id]["pasos"][nombre]
        chunk_dir = session_dir if estado.get("modo") == "test" else session_dir / "chunks" / chunk_id
        trace_dir = chunk_dir / "trazas" / nombre

    detalle = {
        "session_id": session_id,
        "chunk":      chunk_id,
        "paso":       nombre,
        **paso,
        "salidas":    _salidas(session_dir, paso.get("salidas", [])),
        "llamadas":   _llamadas(trace_dir) if trace_dir else [],
        "run_activo": activa,
    }
    if nombre == "juez" and trace_dir is not None:
        # Veredicto por candidato (agentes/juez.py) para la tabla del modal
        detalle["decisiones"] = (_read_json(trace_dir.parent.parent / "juez.json") or {}).get("decisiones", [])
    return detalle
