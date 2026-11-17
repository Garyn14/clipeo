"""
base.py — Contrato de un publicador (TikTok, YouTube, simulado).

El publicador no toca la base de datos: avisa lo que identifica el envío apenas lo tiene
(on_publish_id / on_sesion, el motor lo guarda ANTES de subir) y deja rastro de cada
llamada con `registrar(tipo, mensaje, detalle)`; el evento "chunk" que cierra la subida
lleva {"subida_completa": True}. Termina normal solo cuando la plataforma confirmó la
entrega (TikTok: borrador en la bandeja; YouTube: video procesado); cualquier otra
salida es un ErrorEnvio.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

Registrar = Callable[[str, str, "dict | None"], None]

# Qué hace el motor con cada tipo de error
REINTENTABLE  = "reintentable"   # no llegó nada; volver a la cola (gasta un intento)
ERROR         = "error"          # no reintentar (formato, cuenta baneada, archivo faltante...)
RECONECTAR    = "reconectar"     # token inválido: la cuenta pide reconexión, el clip vuelve a la cola
PAUSAR        = "pausar"         # demasiados borradores pendientes: pausa la cuenta, el clip vuelve a la cola
SIN_CONFIRMAR = "sin_confirmar"  # el video se subió pero no se pudo confirmar que llegó


class ErrorEnvio(Exception):
    def __init__(self, tipo: str, codigo: str, mensaje: str, detalle: dict | None = None):
        super().__init__(mensaje)
        self.tipo = tipo
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalle = detalle or {}


# Estados de la plataforma que cuentan como "llegó a la bandeja" (nuestro fin)
ESTADOS_EN_BANDEJA = ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE")


# Resultado de preguntarle a la plataforma por un envío interrumpido (motor.recuperar)
ENTREGADO   = "entregado"     # llegó: la publicación se cierra como entregada
NO_SUBIDO   = "no_subido"     # no existe nada del lado de la plataforma: es seguro volver a la cola
FALLO       = "fallo"         # la plataforma lo rechazó: se aplica `error`
DESCONOCIDO = "desconocido"   # no se puede saber: sin_confirmar (acción manual)


@dataclass
class Recuperacion:
    resultado: str
    mensaje: str
    error: ErrorEnvio | None = None
    publish_id: str | None = None   # id que se supo recién al recuperar (YouTube: id del video)


class Publicador(Protocol):
    def enviar(self, ruta: Path, cuenta: dict, pub: dict, on_publish_id: Callable[[str], None],
               registrar: Registrar, on_sesion: Callable[[str], None] | None = None) -> None: ...

    def recuperar(self, pub: dict, cuenta: dict, registrar: Registrar) -> Recuperacion:
        """En qué quedó un envío cuyo proceso se interrumpió (nunca reenvía)."""
        ...
