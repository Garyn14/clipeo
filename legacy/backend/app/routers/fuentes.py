"""
fuentes.py — CLIP-63: página "Fuentes" del panel (fuentes estáticas por nicho, S14). Todo manual: sin cron.

GET  /fuentes                    nichos con fuentes.yaml
GET  /fuentes/{nicho}            canales, candidatos, historial reciente, última revisión y estado de Colab
POST /fuentes/{nicho}/ejecutar   {dias? | ultimos?} → revisa los canales y registra lo nuevo
POST /fuentes/{nicho}/procesar   {ids} → corre el pipeline en segundo plano (log en runs_logs/)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.paths import PROJECT_ROOT  # noqa: F401 — parcha sys.path
from investigacion import comun, fuentes_estaticas as fe

router = APIRouter(prefix="/fuentes", tags=["fuentes"])
LOGS = PROJECT_ROOT / "backend" / "runs_logs"


class EjecutarBody(BaseModel):
    dias: int | None = None
    ultimos: int | None = None


class ProcesarBody(BaseModel):
    ids: list[str]


def _existe(nicho: str) -> None:
    if not (comun.carpeta_nicho(nicho) / "fuentes.yaml").exists():
        raise HTTPException(404, f"El nicho {nicho} no tiene fuentes.yaml")


@router.get("")
def nichos():
    base = comun.RAIZ / "investigacion"
    return sorted(p.parent.name for p in base.glob("*/fuentes.yaml"))


@router.get("/{nicho}")
def detalle(nicho: str):
    _existe(nicho)
    config = fe.cargar_config(nicho)
    try:
        estado = json.loads((comun.carpeta_nicho(nicho) / "fuentes_estado.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        estado = {}
    actual = fe.estado_actual(fe.leer_historial(nicho))
    historial = sorted(actual.values(), key=lambda f: f.get("detectado") or "", reverse=True)[:60]
    try:
        from transcripcion.video_transcriber import colab_vivo
        vivo, motivo = colab_vivo(timeout=5)
    except Exception as e:   # noqa: BLE001
        vivo, motivo = False, str(e)
    return {
        "nicho": nicho,
        "activo": config.get("activo", True),
        "ventana_inicial_dias": config.get("ventana_inicial_dias", 7),
        "canales": [{**c, "ultima_revision": estado.get(c.get("url"))} for c in config.get("canales") or []],
        "candidatos": sorted(fe.candidatos(nicho), key=lambda f: f.get("publicado") or "", reverse=True),
        "historial": historial,
        "colab": {"vivo": vivo, "motivo": motivo},
    }


@router.post("/{nicho}/ejecutar")
def ejecutar(nicho: str, body: EjecutarBody):
    _existe(nicho)
    return fe.ejecutar(nicho, dias=body.dias, ultimos=body.ultimos)


@router.post("/{nicho}/procesar")
def procesar(nicho: str, body: ProcesarBody):
    _existe(nicho)
    validos = {f["id"] for f in fe.candidatos(nicho)} | {
        i for i, f in fe.estado_actual(fe.leer_historial(nicho)).items() if f.get("estado") == "error"}
    ids = [i for i in body.ids if i in validos]
    if not ids:
        raise HTTPException(400, "Ningún candidato válido para procesar")
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"fuentes_{nicho}_{datetime.now():%Y%m%d_%H%M%S}.log"
    with log.open("w", encoding="utf-8") as salida:
        subprocess.Popen([sys.executable, "-u", "-m", "investigacion.fuentes_estaticas", "procesar", nicho, *ids],
                         cwd=str(PROJECT_ROOT), stdout=salida, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    return {"iniciado": ids, "log": log.name}
