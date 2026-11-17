from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import pipeline_runner

router = APIRouter(prefix="/runs", tags=["runs"])


class LaunchBody(BaseModel):
    modo: str            # "video" | "test"
    url_o_path: str
    canal_id: str | None = None


@router.post("")
def launch(body: LaunchBody):
    if body.modo not in ("video", "test"):
        raise HTTPException(400, "modo debe ser 'video' o 'test'")
    try:
        return pipeline_runner.launch_run(body.modo, body.url_o_path, body.canal_id)
    except pipeline_runner.RunEnCursoError as e:
        raise HTTPException(409, str(e))


@router.get("")
def list_all():
    return pipeline_runner.list_runs()


@router.get("/{run_id}")
def get(run_id: str, lineas: int = 40):
    try:
        return pipeline_runner.get_run(run_id, lineas_log=min(max(lineas, 10), 2000))
    except KeyError:
        raise HTTPException(404, "Corrida no encontrada")
