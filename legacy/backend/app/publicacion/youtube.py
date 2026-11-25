"""
youtube.py — Publicador real: YouTube Data API v3, subida reanudable (videos.insert).

Flujo:
  1. POST {UPLOAD}/videos?uploadType=resumable&part=snippet,status con título, descripción,
     tags, categoría, idioma, público y "no es para niños" → Location = URL de la sesión de
     subida. Se guarda (on_sesion) ANTES de subir; nunca va a los eventos ni al panel.
  2. PUT de la sesión con el archivo entero → 200/201 con el recurso del video (id).
  3. GET videos?part=status,processingDetails hasta status.uploadStatus = processed (nuestro
     fin). failed / rejected / deleted → error con el motivo de YouTube.
  Un video vertical de hasta 3 min se clasifica solo como Short.

Nunca reenviar a ciegas: si el PUT se corta o responde 5xx, el video pudo haberse creado.
Se le pregunta a la sesión (PUT vacío con Content-Range: bytes */<size>): 200/201 = la
subida terminó (se toma el id), 308/404 = no hay video (es seguro volver a la cola), sin
respuesta = SIN_CONFIRMAR.

Visibilidad: siempre público (VISIBILIDAD). Google advierte que un proyecto de API no
auditado queda bloqueado en privado; al terminar se lee la visibilidad real del video y, si
YouTube no respetó la pedida, queda un evento de error en las trazas (el video igual llegó).

OAuth: Google acepta http://localhost como redirect, así que la vuelta llega directo al
backend (/publicaciones/cuentas/youtube/callback). Credenciales YOUTUBE_CLIENT_ID,
YOUTUBE_CLIENT_SECRET, YOUTUBE_REDIRECT_URI en .env (Configuración). Ningún token ni URL de
sesión va a los eventos.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import requests
from dotenv import dotenv_values

from app.publicacion.base import (
    DESCONOCIDO, ENTREGADO, ERROR, FALLO, NO_SUBIDO, PAUSAR, RECONECTAR, REINTENTABLE, SIN_CONFIRMAR,
    ErrorEnvio, Recuperacion, Registrar,
)
from app.publicacion.horarios import ahora, iso
from app.services.env_manager import ENV_PATH

NOMBRE = "YouTube"
MENSAJE_ENTREGA = "YouTube confirmó: el video está subido y procesado"
VISIBILIDAD = "public"

API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
REDIRECT_DEFAULT = "http://localhost:8000/publicaciones/cuentas/youtube/callback"

CATEGORIA = "22"                # Gente y blogs
IDIOMA = "es"
SONDEO_INTERVALO_S = 10
SONDEO_MAX_S = 600              # ~10 min esperando "processed"
RENOVAR_ANTES = timedelta(minutes=10)   # el access token de Google dura 1 h
TIMEOUT = (15, 120)
TIMEOUT_SUBIDA = (15, 600)

_dormir = time.sleep

# error.errors[0].reason → (tipo, mensaje para el panel)
_RAZONES = {
    "quotaExceeded": (PAUSAR, "YouTube: se agotó la cuota diaria de la API"),
    "dailyLimitExceeded": (PAUSAR, "YouTube: se agotó la cuota diaria de la API"),
    "uploadLimitExceeded": (PAUSAR, "YouTube: el canal llegó a su límite de subidas por día"),
    "rateLimitExceeded": (REINTENTABLE, "YouTube: demasiadas llamadas seguidas"),
    "userRateLimitExceeded": (REINTENTABLE, "YouTube: demasiadas llamadas seguidas"),
    "youtubeSignupRequired": (ERROR, "La cuenta de Google no tiene canal de YouTube"),
    "insufficientPermissions": (RECONECTAR, "La cuenta no autorizó subir videos — reconecta la cuenta"),
    "authError": (RECONECTAR, "El token de YouTube es inválido o venció — reconecta la cuenta"),
    "invalidTitle": (ERROR, "YouTube rechazó el título"),
    "invalidDescription": (ERROR, "YouTube rechazó la descripción"),
    "invalidTags": (ERROR, "YouTube rechazó los tags"),
    "invalidCategoryId": (ERROR, "YouTube rechazó la categoría"),
}

# status.failureReason (uploadStatus failed) y status.rejectionReason (rejected)
_FALLAS = {
    "codec": "el códec del video no es compatible",
    "conversion": "no se pudo convertir el video",
    "emptyFile": "el archivo está vacío",
    "invalidFile": "el archivo no es un video válido",
    "tooSmall": "el archivo es demasiado chico",
    "uploadAborted": "la subida se canceló",
    "duplicate": "es un duplicado de un video que ya está en el canal",
    "copyright": "infracción de derechos de autor",
    "inappropriate": "contenido inapropiado",
    "length": "el video es demasiado largo",
    "termsOfUse": "viola las condiciones de uso",
    "trademark": "infracción de marca",
    "uploaderAccountClosed": "la cuenta del canal está cerrada",
    "uploaderAccountSuspended": "la cuenta del canal está suspendida",
    "claim": "reclamo de derechos",
    "legal": "motivo legal",
}


# ── Configuración ────────────────────────────────────────────

def credenciales() -> dict:
    valores = dotenv_values(str(ENV_PATH)) if ENV_PATH.exists() else {}
    cred = {
        "client_id": (valores.get("YOUTUBE_CLIENT_ID") or "").strip(),
        "client_secret": (valores.get("YOUTUBE_CLIENT_SECRET") or "").strip(),
        "redirect_uri": (valores.get("YOUTUBE_REDIRECT_URI") or "").strip() or REDIRECT_DEFAULT,
    }
    faltan = [k for k in ("client_id", "client_secret") if not cred[k]]
    if faltan:
        raise ValueError("Faltan credenciales de YouTube en Configuración: "
                         + ", ".join(f"YOUTUBE_{k.upper()}" for k in faltan))
    return cred


# ── HTTP ─────────────────────────────────────────────────────

def _razon(resp: requests.Response) -> tuple[str, str]:
    """(reason, message) de un error de la API de Google."""
    try:
        err = resp.json().get("error") or {}
    except ValueError:
        return "", ""
    if not isinstance(err, dict):   # endpoint de tokens: {"error": "invalid_grant", ...}
        return str(err), ""
    errores = err.get("errors") or [{}]
    return errores[0].get("reason") or err.get("status") or "", err.get("message") or ""


def _clasificar(resp: requests.Response, registrar: Registrar, tipo: str) -> ErrorEnvio:
    razon, mensaje = _razon(resp)
    detalle = {"http": resp.status_code, "codigo": razon or None}
    registrar("error", f"YouTube respondió {resp.status_code} {razon} en {tipo}: {mensaje}".strip(), detalle)
    if razon in _RAZONES:
        t, texto = _RAZONES[razon]
        return ErrorEnvio(t, razon, texto, detalle)
    if resp.status_code == 401:
        return ErrorEnvio(RECONECTAR, razon or "http_401", _RAZONES["authError"][1], detalle)
    if resp.status_code >= 500 or resp.status_code == 429:
        return ErrorEnvio(REINTENTABLE, razon or f"http_{resp.status_code}",
                          f"YouTube no disponible (HTTP {resp.status_code})", detalle)
    return ErrorEnvio(ERROR, razon or f"http_{resp.status_code}",
                      f"YouTube rechazó el envío: {razon or resp.status_code} {mensaje}".strip(), detalle)


def _cuerpo_video(meta: dict) -> dict:
    snippet = {"title": meta["titulo"], "description": meta.get("descripcion") or "",
               "categoryId": CATEGORIA, "defaultLanguage": IDIOMA, "defaultAudioLanguage": IDIOMA}
    if meta.get("tags"):
        snippet["tags"] = meta["tags"]
    return {"snippet": snippet,
            "status": {"privacyStatus": VISIBILIDAD, "selfDeclaredMadeForKids": False}}


def _consultar_sesion(sesion: str, size: int, token: str, registrar: Registrar) -> tuple[str, str | None]:
    """¿Terminó la subida de esta sesión? ('completa', id) | ('incompleta', None) | ('desconocido', None)."""
    try:
        resp = requests.put(sesion, data=b"", timeout=TIMEOUT, headers={
            "Authorization": f"Bearer {token}", "Content-Length": "0", "Content-Range": f"bytes */{size}"})
    except requests.RequestException as e:
        registrar("error", f"no se pudo consultar la sesión de subida: {type(e).__name__}", {"excepcion": str(e)[:300]})
        return "desconocido", None
    if resp.status_code in (200, 201):
        try:
            video_id = resp.json().get("id")
        except ValueError:
            video_id = None
        registrar("status", f"la sesión de subida dice: subida completa (video {video_id})",
                  {"http": resp.status_code, "video_id": video_id})
        return ("completa", video_id) if video_id else ("desconocido", None)
    if resp.status_code in (308, 404, 410):
        registrar("status", f"la sesión de subida dice: no se completó (HTTP {resp.status_code})",
                  {"http": resp.status_code, "recibido": resp.headers.get("Range")})
        return "incompleta", None
    registrar("error", f"la sesión de subida respondió HTTP {resp.status_code}", {"http": resp.status_code})
    return "desconocido", None


# ── Publicador ───────────────────────────────────────────────

class PublicadorYouTube:
    def enviar(self, ruta: Path, cuenta: dict, pub: dict, on_publish_id: Callable[[str], None],
               registrar: Registrar, on_sesion: Callable[[str], None] | None = None) -> None:
        meta = json.loads(pub["metadatos"]) if pub.get("metadatos") else None
        if not meta or not meta.get("titulo"):
            raise ErrorEnvio(ERROR, "sin_texto", "El clip no tiene título para YouTube (sin copy del Agente 3)")
        token = cuenta["access_token"]
        size = ruta.stat().st_size

        try:
            resp = requests.post(
                f"{UPLOAD}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                json=_cuerpo_video(meta), timeout=TIMEOUT,
                headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Length": str(size),
                         "X-Upload-Content-Type": "video/mp4"},
            )
        except requests.RequestException as e:
            registrar("error", f"sin conexión con YouTube (init): {type(e).__name__}", {"excepcion": str(e)[:300]})
            raise ErrorEnvio(REINTENTABLE, "red", f"Sin conexión con YouTube: {type(e).__name__}") from e
        sesion = resp.headers.get("Location")
        if resp.status_code != 200 or not sesion:
            if resp.status_code == 200:
                registrar("error", "YouTube no devolvió la sesión de subida", {"http": 200})
                raise ErrorEnvio(REINTENTABLE, "respuesta_incompleta", "YouTube no devolvió la sesión de subida")
            raise _clasificar(resp, registrar, "init")
        registrar("init", f"YouTube aceptó el envío — sesión de subida creada ({size} bytes, {VISIBILIDAD})",
                  {"http": 200, "bytes": size, "titulo": meta["titulo"]})
        if on_sesion:
            on_sesion(sesion)

        video_id = self._subir(sesion, ruta, size, token, registrar)
        on_publish_id(video_id)
        registrar("chunk", f"video subido — id {video_id}",
                  {"http": 201, "bytes": size, "video_id": video_id, "subida_completa": True})
        self._esperar_procesado(video_id, cuenta, registrar)

    def _subir(self, sesion: str, ruta: Path, size: int, token: str, registrar: Registrar) -> str:
        try:
            with open(ruta, "rb") as f:
                resp = requests.put(sesion, data=f, timeout=TIMEOUT_SUBIDA, headers={
                    "Authorization": f"Bearer {token}", "Content-Type": "video/mp4", "Content-Length": str(size)})
        except requests.RequestException as e:
            registrar("error", f"la subida se cortó: {type(e).__name__} — consultando si llegó",
                      {"excepcion": str(e)[:300]})
            resp = None
        if resp is not None and resp.status_code in (200, 201):
            try:
                video_id = resp.json().get("id")
            except ValueError:
                video_id = None
            if video_id:
                return video_id
        if resp is not None and 400 <= resp.status_code < 500 and resp.status_code != 408:
            raise _clasificar(resp, registrar, "subida")   # rechazo explícito: no se creó el video
        if resp is not None:
            registrar("error", f"la subida respondió HTTP {resp.status_code} — consultando si llegó",
                      {"http": resp.status_code})

        # Corte, 5xx o 200 sin id: el video pudo haberse creado. Nunca reenviar a ciegas.
        estado, video_id = _consultar_sesion(sesion, size, token, registrar)
        if estado == "completa":
            return video_id
        if estado == "incompleta":
            raise ErrorEnvio(REINTENTABLE, "subida_incompleta", "La subida no se completó (no hay video) — vuelve a la cola")
        raise ErrorEnvio(SIN_CONFIRMAR, "sin_confirmacion",
                         "La subida se cortó y no se pudo saber si el video llegó — verificá en YouTube Studio")

    def _estado_video(self, video_id: str, token: str, registrar: Registrar,
                      solo_cambios: str | None = None) -> tuple[str, str | None]:
        """(uploadStatus, motivo) del video; ('', None) si todavía no aparece."""
        try:
            resp = requests.get(f"{API}/videos", params={"part": "status,processingDetails", "id": video_id},
                                headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        except requests.RequestException as e:
            registrar("error", f"sin conexión con YouTube (estado): {type(e).__name__}", {"excepcion": str(e)[:300]})
            raise ErrorEnvio(REINTENTABLE, "red", f"Sin conexión con YouTube: {type(e).__name__}") from e
        if resp.status_code != 200:
            raise _clasificar(resp, registrar, "estado")
        items = resp.json().get("items") or []
        if not items:
            estado, motivo, visibilidad = "", None, None
        else:
            st = items[0].get("status") or {}
            estado = st.get("uploadStatus") or ""
            motivo = st.get("failureReason") or st.get("rejectionReason")
            visibilidad = st.get("privacyStatus")
        if estado != solo_cambios:
            proceso = ((items[0].get("processingDetails") or {}).get("processingStatus") if items else None)
            registrar("status", f"YouTube: {estado or 'todavía no aparece'}" + (f" ({motivo})" if motivo else ""),
                      {"http": 200, "status": estado or None, "motivo": motivo, "procesamiento": proceso,
                       "visibilidad": visibilidad})
        if estado == "processed" and visibilidad and visibilidad != VISIBILIDAD:
            # El video llegó, pero YouTube no respetó la visibilidad pedida (proyecto sin auditoría)
            registrar("error", f"se pidió {VISIBILIDAD} pero YouTube dejó el video como {visibilidad} — "
                               "revisalo en YouTube Studio",
                      {"pedida": VISIBILIDAD, "visibilidad": visibilidad})
        return estado, motivo

    @staticmethod
    def _rechazo(estado: str, motivo: str | None) -> ErrorEnvio:
        texto = _FALLAS.get(motivo or "", motivo or "sin motivo")
        if estado == "deleted":
            return ErrorEnvio(ERROR, "deleted", "El video fue eliminado en YouTube")
        verbo = "rechazó" if estado == "rejected" else "no pudo procesar"
        return ErrorEnvio(ERROR, motivo or estado, f"YouTube {verbo} el video: {texto}",
                          {"status": estado, "motivo": motivo})

    def _esperar_procesado(self, video_id: str, cuenta: dict, registrar: Registrar) -> None:
        ultimo = None
        for _ in range(max(1, SONDEO_MAX_S // SONDEO_INTERVALO_S)):
            try:
                estado, motivo = self._estado_video(video_id, cuenta["access_token"], registrar, solo_cambios=ultimo)
            except ErrorEnvio:
                estado, motivo = None, None   # ya quedó registrado; seguir esperando
            if estado == "processed":
                return
            if estado in ("failed", "rejected", "deleted"):
                raise self._rechazo(estado, motivo)
            ultimo = estado if estado is not None else ultimo
            _dormir(SONDEO_INTERVALO_S)
        raise ErrorEnvio(SIN_CONFIRMAR, "sin_confirmacion",
                         f"El video se subió pero YouTube no terminó de procesarlo en {SONDEO_MAX_S // 60} min "
                         f"(último estado: {ultimo or 'desconocido'}) — verificá en YouTube Studio")

    def recuperar(self, pub: dict, cuenta: dict, registrar: Registrar) -> Recuperacion:
        token = cuenta["access_token"]
        video_id = pub.get("publish_id")
        if not video_id:
            if not pub.get("sesion_subida"):
                return Recuperacion(NO_SUBIDO, "se interrumpió antes de que YouTube aceptara el envío (no hay video)")
            size = Path(pub["ruta_video"]).stat().st_size if Path(pub["ruta_video"]).exists() else 0
            estado, video_id = _consultar_sesion(pub["sesion_subida"], size, token, registrar)
            if estado == "incompleta":
                return Recuperacion(NO_SUBIDO, "la subida no se completó (no hay video)")
            if estado != "completa":
                return Recuperacion(DESCONOCIDO, "no se pudo saber si la subida terminó — verificá en YouTube Studio")
        try:
            estado, motivo = self._estado_video(video_id, token, registrar)
        except ErrorEnvio as e:
            return Recuperacion(DESCONOCIDO, f"no se pudo consultar a YouTube: {e.mensaje}", e, publish_id=video_id)
        if estado == "processed":
            return Recuperacion(ENTREGADO, "YouTube confirmó tras la interrupción (processed)", publish_id=video_id)
        if estado in ("failed", "rejected", "deleted"):
            e = self._rechazo(estado, motivo)
            return Recuperacion(FALLO, e.mensaje, e, publish_id=video_id)
        return Recuperacion(DESCONOCIDO, f"el video existe pero YouTube responde {estado or 'sin estado'} — "
                                         "verificá en YouTube Studio", publish_id=video_id)


# ── OAuth ────────────────────────────────────────────────────

def url_autorizacion(state: str) -> str:
    cred = credenciales()
    return URL_AUTORIZACION + "?" + urlencode({
        "client_id": cred["client_id"],
        "redirect_uri": cred["redirect_uri"],
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",      # refresh token
        "prompt": "consent",           # que lo devuelva aunque ya se haya autorizado antes
        "include_granted_scopes": "true",
        "state": state,
    })


def _pedir_token(campos: dict) -> dict:
    try:
        resp = requests.post(URL_TOKEN, data=campos, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise ErrorEnvio(REINTENTABLE, "red", f"Sin conexión con Google: {type(e).__name__}") from e
    try:
        cuerpo = resp.json()
    except ValueError:
        cuerpo = {}
    if resp.status_code != 200 or not cuerpo.get("access_token"):
        codigo = str(cuerpo.get("error") or f"http_{resp.status_code}")
        detalle = {"http": resp.status_code, "codigo": codigo}
        if resp.status_code >= 500:
            raise ErrorEnvio(REINTENTABLE, codigo, "Google no disponible", detalle)
        raise ErrorEnvio(RECONECTAR, codigo,
                         f"Google rechazó el token: {codigo} {cuerpo.get('error_description') or ''}".strip(), detalle)
    tokens = {
        "access_token": cuerpo["access_token"],
        "access_vence": iso(ahora() + timedelta(seconds=int(cuerpo.get("expires_in") or 0))),
        "scope": cuerpo.get("scope") or "",
    }
    if cuerpo.get("refresh_token"):
        tokens["refresh_token"] = cuerpo["refresh_token"]
    return tokens


def canjear_codigo(code: str) -> dict:
    cred = credenciales()
    tokens = _pedir_token({
        "client_id": cred["client_id"], "client_secret": cred["client_secret"],
        "code": code, "grant_type": "authorization_code", "redirect_uri": cred["redirect_uri"],
    })
    if "youtube.upload" not in tokens.pop("scope"):
        raise ValueError("La cuenta no otorgó el permiso para subir videos — volvé a conectar y aceptalo")
    if not tokens.get("refresh_token"):
        raise ValueError("Google no devolvió el permiso permanente (refresh token) — volvé a conectar")
    tokens["refresh_vence"] = None   # Google no informa cuándo vence
    return tokens


def renovar(refresh_token: str) -> dict:
    cred = credenciales()
    tokens = _pedir_token({
        "client_id": cred["client_id"], "client_secret": cred["client_secret"],
        "grant_type": "refresh_token", "refresh_token": refresh_token,
    })
    tokens.pop("scope", None)
    return tokens


def necesita_renovar(cuenta: dict) -> bool:
    if not cuenta.get("access_vence"):
        return True
    return datetime.fromisoformat(cuenta["access_vence"]) - ahora() < RENOVAR_ANTES


def canal(access_token: str) -> tuple[str, str]:
    """(channel_id, nombre) del canal de la cuenta. ValueError si la cuenta no tiene canal."""
    try:
        resp = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                            headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT)
        items = (resp.json().get("items") or []) if resp.status_code == 200 else None
    except (requests.RequestException, ValueError) as e:
        raise ValueError(f"No se pudo leer el canal de YouTube: {type(e).__name__}") from e
    if items is None:
        raise ValueError(f"No se pudo leer el canal de YouTube (HTTP {resp.status_code})")
    if not items:
        raise ValueError("La cuenta de Google no tiene canal de YouTube — creá el canal y volvé a conectar")
    return items[0]["id"], (items[0].get("snippet") or {}).get("title") or "Canal de YouTube"
