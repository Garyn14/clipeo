"""
negocio.py — S17 · CLIP-74: sección Negocio del panel (reporte por cliente y mes, sin seguidores todavía: CLIP-75).

GET  /negocio?mes=AAAA-MM            vista global: una fila por cliente (de su última foto; no lee cuentas)
GET  /negocio/{nicho}?mes=AAAA-MM    minidashboard del cliente sobre la última foto
POST /negocio/{nicho}/actualizar     lee todas las cuentas del cliente (CLIP-73), guarda la foto y devuelve el reporte
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app.paths import PROJECT_ROOT  # noqa: F401 — parcha sys.path
from investigacion import negocio as ng

router = APIRouter(prefix="/negocio", tags=["negocio"])


def _validar_mes(mes: str | None) -> str | None:
    if mes and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise HTTPException(400, "mes inválido: usa AAAA-MM")
    return mes


def _existe(nicho: str) -> None:
    if nicho not in ng.clientes():
        raise HTTPException(404, f"{nicho} no tiene cuentas configuradas")


@router.get("")
def global_(mes: str | None = None):
    return ng.global_(_validar_mes(mes))


@router.get("/{nicho}")
def detalle(nicho: str, mes: str | None = None):
    _existe(nicho)
    return ng.reporte(nicho, _validar_mes(mes))


@router.post("/{nicho}/actualizar")
def actualizar(nicho: str, mes: str | None = None):
    _existe(nicho)
    mes = _validar_mes(mes)
    foto = ng.actualizar(nicho)
    return ng.reporte(nicho, mes, foto=foto)
