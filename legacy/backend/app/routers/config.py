from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.paths import PROJECT_ROOT  # noqa: F401 — parcha sys.path a legacy/
from app.services import config_scanner, env_manager
from ai_client import perfiles

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/canales")
def get_canales():
    return config_scanner.list_canales()


class EnvUpdateBody(BaseModel):
    values: dict[str, str]


@router.get("/env")
def get_env():
    return env_manager.list_env_status()


@router.put("/env")
def put_env(body: EnvUpdateBody):
    try:
        env_manager.update_env(body.values)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return env_manager.list_env_status()


# ── CLIP-83: cuenta de Claude por perfiles (carpetas de sesión de Claude Code) ──


def _perfil(nombre: str | None) -> dict:
    return {"nombre": nombre or "", **perfiles.estado(nombre),
            "comando_login": perfiles.comando_login(nombre) if nombre else "claude auth login"}


@router.get("/claude")
def get_claude():
    activo = perfiles.perfil_activo()
    nombres = perfiles.listar()
    return {
        "activo": activo,
        "activo_existe": not activo or activo in nombres,
        "carpeta": str(perfiles.carpeta_perfiles()),
        "perfiles": [_perfil(None)] + [_perfil(n) for n in nombres],
    }


class PerfilBody(BaseModel):
    nombre: str


@router.post("/claude/perfiles")
def crear_perfil(body: PerfilBody):
    try:
        nombre = perfiles.crear(body.nombre)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _perfil(nombre)


@router.put("/claude/activo")
def activar_perfil(body: PerfilBody):
    nombre = (body.nombre or "").strip()
    if nombre:
        try:
            nombre = perfiles.validar_nombre(nombre)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if nombre not in perfiles.listar():
            raise HTTPException(404, f"No existe el perfil '{nombre}'.")
    env_manager.escribir_clave_interna(perfiles.CLAVE_ACTIVO, nombre)
    return get_claude()
