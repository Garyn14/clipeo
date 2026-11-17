"""
simulado.py — Publicador que imita el flujo de una plataforma (TikTok o YouTube) sin red,
para probar cola, horarios, pantalla y recuperación antes de tener la app registrada.

Fallas inyectables con PUBLICACION_SIMULAR_FALLA en .env (se relee en cada envío, no hace
falta reiniciar): red | token | pendientes | formato | sin_confirmar. Vacío = todo bien.
PUBLICACION_SIMULADO_DEMORA = segundos que tarda la "subida" (default 2).
"""

import os
import time
import uuid
from pathlib import Path
from typing import Callable

from dotenv import dotenv_values

from app.publicacion.base import (
    ENTREGADO, ERROR, FALLO, PAUSAR, RECONECTAR, REINTENTABLE, SIN_CONFIRMAR, ErrorEnvio, Recuperacion, Registrar,
)
from app.services.env_manager import ENV_PATH

_dormir = time.sleep

_NOMBRES = {"tiktok": "TikTok", "youtube": "YouTube"}
_ENTREGA = {"tiktok": "SEND_TO_USER_INBOX — el borrador está en la bandeja",
            "youtube": "processed — el video está subido y procesado"}


def _opcion(clave: str, default: str = "") -> str:
    valores = dotenv_values(str(ENV_PATH)) if ENV_PATH.exists() else {}
    return (os.environ.get(clave) or valores.get(clave) or default).strip()


class PublicadorSimulado:
    def __init__(self, plataforma: str = "tiktok"):
        self.plataforma = plataforma
        self.nombre = _NOMBRES.get(plataforma, plataforma)

    def enviar(self, ruta: Path, cuenta: dict, pub: dict, on_publish_id: Callable[[str], None],
               registrar: Registrar, on_sesion: Callable[[str], None] | None = None) -> None:
        falla = _opcion("PUBLICACION_SIMULAR_FALLA")
        demora = float(_opcion("PUBLICACION_SIMULADO_DEMORA", "2") or 0)
        n = self.nombre

        if falla == "red":
            raise ErrorEnvio(REINTENTABLE, "red", f"(simulado) no hubo conexión con {n}")
        if falla == "token":
            raise ErrorEnvio(RECONECTAR, "access_token_invalid", f"(simulado) el token de {n} es inválido",
                             {"http": 401})
        if falla == "pendientes":
            raise ErrorEnvio(PAUSAR, "spam_risk_too_many_pending_share",
                             f"(simulado) {n}: límite de envíos en 24 h", {"http": 403})

        size = ruta.stat().st_size
        publish_id = f"sim_{uuid.uuid4().hex[:16]}"
        registrar("init", f"(simulado) {n} aceptó el envío — id {publish_id}",
                  {"http": 200, "publish_id": publish_id, "bytes": size, "partes": 1})
        on_publish_id(publish_id)
        _dormir(demora)
        registrar("chunk", "(simulado) parte 1/1 subida", {"http": 201, "bytes": size, "subida_completa": True})

        if falla == "formato":
            registrar("status", f"(simulado) {n}: FAILED", {"status": "FAILED", "fail_reason": "file_format_check_failed"})
            raise ErrorEnvio(ERROR, "file_format_check_failed", f"(simulado) {n} rechazó el formato del video")
        if falla == "sin_confirmar":
            raise ErrorEnvio(SIN_CONFIRMAR, "sin_respuesta",
                             f"(simulado) el video se subió pero {n} no confirmó la entrega")
        registrar("status", f"(simulado) {n}: {_ENTREGA.get(self.plataforma, 'entregado')}",
                  {"status": "entregado"})

    def recuperar(self, pub: dict, cuenta: dict, registrar: Registrar) -> Recuperacion:
        if (pub.get("publish_id") or "").startswith("sim_"):
            registrar("status", f"(simulado) consulta de estado: entregado", {"status": "entregado"})
            return Recuperacion(ENTREGADO, f"(simulado) {self.nombre} confirmó tras la interrupción")
        registrar("status", "(simulado) consulta de estado: FAILED", {"status": "FAILED"})
        return Recuperacion(FALLO, "(simulado) el envío fue cancelado",
                            ErrorEnvio(ERROR, "publish_cancelled", "(simulado) el envío fue cancelado"))
