"""
directos.py — CLIP-88/90 (épica L1, CLIP-86): API de la sección Directos.

Cuentas de directo por cliente (alta, pausa, baja), último chequeo, capturas en curso y recientes, y acciones:
revisar ahora, grabar ahora (sin verificar) y detener una captura.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.directos import vigilante
from app.paths import STREAM_DATA
from captura import directos, tipos_directo
from investigacion.negocio import nombre_cliente

router = APIRouter(prefix="/directos", tags=["directos"])

CAPTURAS_POR_CLIENTE = 8


def _cliente(nicho: str, chequeos: dict) -> dict:
    cuentas = []
    for c in directos.leer(nicho)["cuentas"]:
        clave = directos.clave_cuenta(nicho, c["plataforma"], c["usuario"])
        cuentas.append({**c, "chequeo": chequeos.get(clave), "grabando": vigilante.activa(nicho, c)})
    capturas = directos.capturas(STREAM_DATA, nicho)[:CAPTURAS_POR_CLIENTE]
    for cap in capturas:
        if cap.get("estado") == "grabando" and not vigilante._vivo(cap.get("pid"), cap.get("inicio")):
            cap["estado"], cap["motivo"] = "interrumpido", "el grabador se cerró sin terminar (¿se reinició la PC?)"
    return {"nicho": nicho, "cliente": nombre_cliente(nicho), "cuentas": cuentas, "capturas": capturas}


@router.get("")
def resumen():
    chequeos = directos.chequeos(STREAM_DATA)
    return {
        "plataformas": [t.describir() for t in tipos_directo.REGISTRO.values()],
        "vigilante": vigilante.estado(),
        "clientes": [_cliente(n, chequeos) for n in directos.clientes()],
    }


class CuentaNueva(BaseModel):
    plataforma: str = "tiktok"
    usuario: str
    trozo_min: int = directos.TROZO_MIN_DEFECTO
    procesar: bool = True


class CambiosCuenta(BaseModel):
    activo: bool | None = None
    procesar: bool | None = None
    trozo_min: int | None = None


def _error(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


@router.post("/{nicho}/cuentas")
def agregar(nicho: str, body: CuentaNueva):
    try:
        return directos.agregar(nicho, body.plataforma, body.usuario, body.trozo_min, body.procesar)
    except tipos_directo.DirectoError as e:
        raise _error(e)


@router.patch("/{nicho}/cuentas/{plataforma}/{usuario}")
def actualizar(nicho: str, plataforma: str, usuario: str, body: CambiosCuenta):
    try:
        return directos.actualizar(nicho, plataforma, usuario, **body.model_dump())
    except tipos_directo.DirectoError as e:
        raise _error(e)


@router.delete("/{nicho}/cuentas/{plataforma}/{usuario}")
def quitar(nicho: str, plataforma: str, usuario: str):
    try:
        directos.quitar(nicho, plataforma, usuario)
    except tipos_directo.DirectoError as e:
        raise _error(e)
    return {"ok": True}


@router.post("/revisar")
def revisar():
    """Vuelta del vigilante ya (en segundo plano: los chequeos van espaciados y pueden tardar)."""
    vigilante.revisar_en_segundo_plano()
    return {"ok": True}


@router.post("/{nicho}/cuentas/{plataforma}/{usuario}/grabar")
def grabar(nicho: str, plataforma: str, usuario: str):
    """Grabar ahora sin verificar (el operador ya vio que está en vivo)."""
    cuenta = next((c for c in directos.leer(nicho)["cuentas"]
                   if c["plataforma"] == plataforma and c["usuario"] == usuario), None)
    if not cuenta:
        raise HTTPException(404, f"@{usuario} no está en los directos de este cliente")
    if vigilante.activa(nicho, cuenta):
        raise HTTPException(409, f"@{usuario} ya se está grabando")
    try:
        tipos_directo.obtener(plataforma)
    except tipos_directo.DirectoError as e:
        raise _error(e)
    return {"pid": vigilante.lanzar_grabador(nicho, cuenta, verificar=False)}


@router.post("/capturas/{carpeta}/detener")
def detener(carpeta: str):
    try:
        vigilante.detener_captura(carpeta)
    except tipos_directo.DirectoError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}
