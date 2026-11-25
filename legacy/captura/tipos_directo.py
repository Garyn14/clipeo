"""
tipos_directo.py — CLIP-88 (épica L1, CLIP-86): tipos de directo desacoplados (registro de plataformas).

Mismo patrón que `investigacion/tipos_fuente.py`: cada plataforma sabe decir si una cuenta está en vivo y cómo grabar
su directo; el vigilante y el grabador no saben de plataformas. Para sumar Kick, YouTube o Twitch se registra un tipo
nuevo y nada más cambia.

`en_vivo` devuelve True / False / None. None = NO CONCLUYENTE (bloqueo del WAF, error técnico, red): nunca se toma
como "no en vivo", porque ese falso negativo ya costó una sesión completa (ver tiktok_capture._diagnosticar_live).
"""

from __future__ import annotations

import re

REGISTRO: dict[str, "TipoDirecto"] = {}


class DirectoError(ValueError):
    """Error explicable al operador (usuario inválido, plataforma no disponible...)."""


class TipoDirecto:
    clave = ""
    nombre = ""
    disponible = True

    def normalizar_usuario(self, texto: str) -> str:
        raise NotImplementedError

    def url(self, usuario: str) -> str:
        raise NotImplementedError

    def en_vivo(self, usuario: str) -> bool | None:
        raise NotImplementedError

    def comando_grabacion(self, usuario: str, destino: str) -> list[str]:
        """Comando que graba el directo en `destino` hasta que se lo detenga o el directo termine."""
        raise NotImplementedError

    def describir(self) -> dict:
        return {"clave": self.clave, "nombre": self.nombre, "disponible": self.disponible}


def registrar(tipo: TipoDirecto) -> TipoDirecto:
    REGISTRO[tipo.clave] = tipo
    return tipo


def obtener(clave: str) -> TipoDirecto:
    tipo = REGISTRO.get(clave)
    if not tipo:
        raise DirectoError(f"Plataforma de directo desconocida: {clave}")
    if not tipo.disponible:
        raise DirectoError(f"Los directos de {tipo.nombre} todavía no están disponibles")
    return tipo


class TikTok(TipoDirecto):
    clave = "tiktok"
    nombre = "TikTok Live"

    def normalizar_usuario(self, texto: str) -> str:
        texto = (texto or "").strip()
        m = re.search(r"tiktok\.com/@([\w.]+)", texto)
        usuario = (m.group(1) if m else texto).lstrip("@").strip().lower()
        if not re.fullmatch(r"[\w.]{2,40}", usuario):
            raise DirectoError("Usuario de TikTok inválido: pega el @usuario o el enlace de su perfil")
        return usuario

    def url(self, usuario: str) -> str:
        return f"https://www.tiktok.com/@{usuario}/live"

    def en_vivo(self, usuario: str) -> bool | None:
        from captura import tiktok_capture

        try:
            return tiktok_capture.verificar_live_activo(self.url(usuario))
        except RuntimeError:
            return None   # bloqueo o error técnico: no concluyente

    def comando_grabacion(self, usuario: str, destino: str) -> list[str]:
        from captura import tiktok_capture

        # Mismas opciones probadas de tiktok_capture._grabar_chunk: sin DVR (--no-live-from-start), H.264.
        return ["yt-dlp", "--no-live-from-start", "--no-part", "--format-sort", "vcodec:h264",
                *tiktok_capture._cookies_args(), "-o", destino, "--max-downloads", "1", self.url(usuario)]


class Proximamente(TipoDirecto):
    disponible = False

    def __init__(self, clave: str, nombre: str):
        self.clave, self.nombre = clave, nombre


registrar(TikTok())
for _clave, _nombre in (("kick", "Kick"), ("youtube", "YouTube Live"), ("twitch", "Twitch")):
    registrar(Proximamente(_clave, _nombre))
