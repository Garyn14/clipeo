"""
estado.py — CLIP-84: estado de la operación para el pie de la barra lateral del panel.

Resume en una sola llamada lo que hoy había que ir a buscar a cada página: si el túnel de Colab responde, qué cuenta
de Claude usa el pipeline y cuántos pasos hay en error. Lo caro (Colab por red, `claude auth status`) se guarda en
memoria unos segundos para que el panel pueda refrescarlo seguido sin castigar a nadie.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter

from app.paths import PROJECT_ROOT  # noqa: F401 — parcha sys.path a legacy/
from app.services import state_reader
from ai_client import perfiles

router = APIRouter(prefix="/estado", tags=["estado"])

_TTL_COLAB_S = 60
_TTL_CLAUDE_S = 300
_cache: dict[str, tuple[float, object]] = {}
_candado = threading.Lock()


def _cacheado(clave: str, ttl: float, calcular):
    ahora = time.monotonic()
    with _candado:
        guardado = _cache.get(clave)
        if guardado and ahora - guardado[0] < ttl:
            return guardado[1]
    valor = calcular()
    with _candado:
        _cache[clave] = (time.monotonic(), valor)
    return valor


def _colab() -> dict:
    from transcripcion.video_transcriber import colab_vivo

    vivo, motivo = colab_vivo(timeout=4)
    return {"vivo": vivo, "motivo": motivo}


def _claude() -> dict:
    activo = perfiles.perfil_activo()
    try:
        info = perfiles.estado(activo or None, timeout=15)
    except ValueError:
        info = {"sesion": False, "error": f"perfil inválido: {activo}"}
    return {"perfil": activo, "cuenta": info.get("cuenta") or "", "sesion": bool(info.get("sesion")),
            "plan": info.get("plan") or ""}


@router.get("")
def get_estado(refrescar: bool = False):
    if refrescar:
        with _candado:
            _cache.clear()
    errores = state_reader.list_errores()
    return {
        "colab": _cacheado("colab", _TTL_COLAB_S, _colab),
        "claude": _cacheado(f"claude:{perfiles.perfil_activo()}", _TTL_CLAUDE_S, _claude),
        "errores": len(errores),
    }
