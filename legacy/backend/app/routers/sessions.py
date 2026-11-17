from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import paso_detalle, pipeline_runner, review_actions, state_reader
from core.chunk_manager import PASOS_CHUNK, PASOS_SESION

router = APIRouter(prefix="/sessions", tags=["sessions"])

# En la URL un paso de sesión va con chunk "_" (ej. /pasos/_/descarga)
_SIN_CHUNK = "_"


class ReintentarBody(BaseModel):
    paso: str
    chunks: list[str] | None = None   # None/[] = todos los chunks con ese paso en error


class ReintentoLoteItem(BaseModel):
    session_id: str
    paso: str
    chunk: str | None = None


class ReintentoLoteBody(BaseModel):
    items: list[ReintentoLoteItem]


def _validar_paso(paso: str) -> None:
    if paso not in PASOS_SESION + PASOS_CHUNK:
        raise HTTPException(400, f"Paso desconocido: {paso}")
    if paso in ("revision", "fin"):
        raise HTTPException(400, "Revisión y Fin no se reintentan: se cierran desde la revisión de clips")


@router.get("")
def get_sessions():
    return state_reader.list_sessions()


@router.post("/reintentar-lote")
def reintentar_lote(body: ReintentoLoteBody):
    """
    Agrupa por (sesión, paso) y lanza una corrida por grupo. Dos grupos de la misma sesión
    no pueden correr a la vez: el segundo vuelve con error y se reintenta después.
    """
    grupos: dict[tuple[str, str], list[str]] = {}
    for item in body.items:
        _validar_paso(item.paso)
        chunks = grupos.setdefault((item.session_id, item.paso), [])
        if item.chunk:
            chunks.append(item.chunk)

    resultados = []
    for (session_id, paso), chunks in grupos.items():
        try:
            run_id = pipeline_runner.relaunch(session_id, paso, chunks or None)
            resultados.append({"session_id": session_id, "paso": paso, "run_id": run_id})
        except pipeline_runner.RunEnCursoError as e:
            resultados.append({"session_id": session_id, "paso": paso, "error": str(e)})
        except FileNotFoundError:
            resultados.append({"session_id": session_id, "paso": paso, "error": "Sesión no encontrada"})
    return resultados


@router.get("/{session_id}")
def get_session(session_id: str):
    try:
        return state_reader.get_session_detail(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")


@router.get("/{session_id}/runs")
def get_session_runs(session_id: str):
    return pipeline_runner.list_runs(session_id)


@router.get("/{session_id}/pasos/{chunk}/{paso}")
def get_paso(session_id: str, chunk: str, paso: str):
    try:
        return paso_detalle.get_paso(session_id, None if chunk == _SIN_CHUNK else chunk, paso)
    except paso_detalle.PasoNoEncontradoError as e:
        raise HTTPException(404, f"Paso no encontrado: {e}")


@router.post("/{session_id}/reintentar")
def reintentar(session_id: str, body: ReintentarBody):
    _validar_paso(body.paso)
    try:
        run_id = pipeline_runner.relaunch(session_id, body.paso, body.chunks or None)
    except pipeline_runner.RunEnCursoError as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError:
        raise HTTPException(404, "Sesión no encontrada")
    return {"run_id": run_id, "session_id": session_id}


@router.post("/{session_id}/reanudar")
def reanudar(session_id: str):
    """Retoma los pasos pendientes/interrumpidos sin resetear nada."""
    try:
        run_id = pipeline_runner.relaunch(session_id)
    except pipeline_runner.RunEnCursoError as e:
        raise HTTPException(409, str(e))
    except FileNotFoundError:
        raise HTTPException(404, "Sesión no encontrada")
    return {"run_id": run_id, "session_id": session_id}


@router.post("/{session_id}/revision/finalizar")
def finalizar_revision(session_id: str):
    try:
        review_actions.finalizar_revision(session_id)
    except review_actions.RevisionIncompletaError as e:
        raise HTTPException(409, {"mensaje": str(e), "pendientes": e.pendientes})
    except review_actions.RevisionNoDisponibleError as e:
        raise HTTPException(409, str(e))
    return state_reader.get_session_detail(session_id)
