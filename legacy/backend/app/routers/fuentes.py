"""
fuentes.py — CLIP-63: página "Fuentes" del panel (fuentes estáticas por nicho, S14). Todo manual: sin cron.

GET  /fuentes                    nichos con fuentes.yaml
GET  /fuentes/{nicho}            canales, candidatos, historial reciente, última revisión y estado de Colab
POST /fuentes/{nicho}/ejecutar   {dias? | ultimos?} → revisa los canales y registra lo nuevo
POST /fuentes/{nicho}/procesar   {ids} → corre el pipeline en segundo plano (log en runs_logs/)

CLIP-66/67 (administrar fuentes):
GET    /fuentes/tipos                          tipos de fuente (implementados y "próximamente")
POST   /fuentes/{nicho}/canales/previsualizar  {plataforma, entrada} → canal + últimos 5 videos (no guarda)
POST   /fuentes/{nicho}/canales                {plataforma, entrada, rol, nombre?}
PATCH  /fuentes/{nicho}/canales                {url, activo?, rol?, nombre?}
DELETE /fuentes/{nicho}/canales?url=…          (el historial se conserva)
PUT    /fuentes/{nicho}/palabras               {palabras}
POST   /fuentes/{nicho}/manual                 {links, rol} → candidatos
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.paths import PROJECT_ROOT  # noqa: F401 — parcha sys.path
from investigacion import comun, fuentes_config as fc, fuentes_estaticas as fe, tipos_fuente as tf

router = APIRouter(prefix="/fuentes", tags=["fuentes"])
LOGS = PROJECT_ROOT / "backend" / "runs_logs"


class EjecutarBody(BaseModel):
    dias: int | None = None
    ultimos: int | None = None


class ProcesarBody(BaseModel):
    ids: list[str]


class CanalBody(BaseModel):
    plataforma: str = "youtube"
    entrada: str
    rol: str = "medios"
    nombre: str | None = None


class EditarCanalBody(BaseModel):
    url: str
    activo: bool | None = None
    rol: str | None = None
    nombre: str | None = None


class PalabrasBody(BaseModel):
    palabras: list[str]


class ManualBody(BaseModel):
    links: list[str]
    rol: str = "medios"


def _error_fuente(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


def _existe(nicho: str) -> None:
    if not (comun.carpeta_nicho(nicho) / "fuentes.yaml").exists():
        raise HTTPException(404, f"El nicho {nicho} no tiene fuentes.yaml")


def _cliente(nicho: str, config: dict) -> str:
    return config.get("cliente") or (config.get("sobre") or nicho).replace("_", " ").title()


@router.get("")
def nichos():
    """Clientes con fuentes: para el selector (nombre visible, canales y candidatos pendientes)."""
    base = comun.RAIZ / "investigacion"
    salida = []
    for nicho in sorted(p.parent.name for p in base.glob("*/fuentes.yaml")):
        config = fe.cargar_config(nicho)
        salida.append({"nicho": nicho, "cliente": _cliente(nicho, config),
                       "canales": len(config.get("canales") or []), "candidatos": len(fe.candidatos(nicho))})
    return salida


@router.get("/tipos")
def tipos():
    return tf.tipos()


@router.get("/{nicho}")
def detalle(nicho: str):
    _existe(nicho)
    config = fe.cargar_config(nicho)
    try:
        estado = json.loads((comun.carpeta_nicho(nicho) / "fuentes_estado.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        estado = {}
    aportes = fc.aportes(nicho)
    try:
        sugerencias = fe.descubrir(nicho)[:10]
    except Exception:  # noqa: BLE001 — sin búsqueda de medios previa no hay sugerencias
        sugerencias = []
    actual = fe.estado_actual(fe.leer_historial(nicho))
    historial = sorted(actual.values(), key=lambda f: f.get("detectado") or "", reverse=True)[:60]
    try:
        from transcripcion.video_transcriber import colab_vivo
        vivo, motivo = colab_vivo(timeout=5)
    except Exception as e:   # noqa: BLE001
        vivo, motivo = False, str(e)
    return {
        "nicho": nicho,
        "cliente": _cliente(nicho, config),
        "activo": config.get("activo", True),
        "ventana_inicial_dias": config.get("ventana_inicial_dias", 7),
        "canales": [{**c, "plataforma": c.get("plataforma", "youtube"), "ultima_revision": estado.get(c.get("url")),
                     "aportes": aportes.get(c.get("nombre"), {})} for c in config.get("canales") or []],
        "palabras_clave": config.get("palabras_clave") or [],
        "sugerencias": sugerencias,
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


# ── CLIP-66/67: administrar fuentes ─────────────────────────

@router.post("/{nicho}/canales/previsualizar")
def previsualizar(nicho: str, body: CanalBody):
    _existe(nicho)
    try:
        return fc.previsualizar(body.plataforma, body.entrada)
    except tf.FuenteError as e:
        raise _error_fuente(e)


@router.post("/{nicho}/canales")
def agregar_canal(nicho: str, body: CanalBody):
    _existe(nicho)
    try:
        return fc.agregar_canal(nicho, body.plataforma, body.entrada, body.rol, body.nombre)
    except tf.FuenteError as e:
        raise _error_fuente(e)


@router.patch("/{nicho}/canales")
def editar_canal(nicho: str, body: EditarCanalBody):
    _existe(nicho)
    try:
        return fc.editar_canal(nicho, body.url, activo=body.activo, rol=body.rol, nombre=body.nombre)
    except tf.FuenteError as e:
        raise _error_fuente(e)


@router.delete("/{nicho}/canales")
def quitar_canal(nicho: str, url: str):
    _existe(nicho)
    try:
        fc.quitar_canal(nicho, url)
    except tf.FuenteError as e:
        raise _error_fuente(e)
    return {"ok": True}


@router.put("/{nicho}/palabras")
def palabras(nicho: str, body: PalabrasBody):
    _existe(nicho)
    return {"palabras": fc.guardar_palabras(nicho, body.palabras)}


@router.post("/{nicho}/manual")
def manual(nicho: str, body: ManualBody):
    _existe(nicho)
    try:
        return {"resultados": fc.agregar_links(nicho, body.links, body.rol)}
    except tf.FuenteError as e:
        raise _error_fuente(e)
