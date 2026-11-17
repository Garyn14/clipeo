from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import config_scanner, env_manager

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
