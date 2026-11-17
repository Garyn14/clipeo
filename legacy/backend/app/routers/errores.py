from fastapi import APIRouter

from app.services import state_reader

router = APIRouter(prefix="/errores", tags=["errores"])


@router.get("")
def get_errores(
    paso: str | None = None,
    reintentable: bool | None = None,
    config: str | None = None,
    desde: str | None = None,   # YYYY-MM-DD, sobre la fecha del error
    hasta: str | None = None,
):
    filas = state_reader.list_errores()
    if paso:
        filas = [f for f in filas if f["paso"] == paso]
    if reintentable is not None:
        filas = [f for f in filas if f["reintentable"] is reintentable]
    if config:
        filas = [f for f in filas if f["config"] == config]
    if desde:
        filas = [f for f in filas if (f["fecha"] or "")[:10] >= desde]
    if hasta:
        filas = [f for f in filas if (f["fecha"] or "")[:10] <= hasta]
    return filas
