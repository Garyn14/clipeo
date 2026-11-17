"""
tiktok.py — Publicador real: Content Posting API de TikTok, flujo *Upload* (borrador a la
bandeja del usuario; sin auditoría de la app no se puede publicar directo en público).

Flujo (doc oficial, verificada 2026-10-09):
  1. POST /v2/post/publish/inbox/video/init/  (scope video.upload; solo el video, sin texto)
     → publish_id + upload_url (válida 1 h). Máx. 6 llamadas/min.
  2. PUT upload_url por partes, en orden: 5–64 MB por parte (la última hasta 128 MB),
     < 5 MB va entero. 206 = sigue, 201 = completo.
  3. POST /v2/post/publish/status/fetch/ hasta SEND_TO_USER_INBOX (nuestro fin).
     FAILED + fail_reason si TikTok lo rechazó. Máx. 30 llamadas/min.
  Límite de TikTok: 5 borradores pendientes en 24 h (spam_risk_too_many_pending_share).

Seguridad del reintento: hasta que la subida devuelve 201 no existe borrador, así que
cualquier falla antes es REINTENTABLE. Después del 201 solo un FAILED explícito es
definitivo; si no hay respuesta clara, SIN_CONFIRMAR (nunca reenviar a ciegas).

OAuth: el redirect_uri tiene que ser https y estar registrado en la app de TikTok; el
backend local es http, así que el usuario pega en el panel la URL a la que lo devolvió
TikTok y de ahí sale el `code` (ver router /publicaciones/tiktok/conectar).

Las credenciales (TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI) se leen
de .env en cada uso (se editan desde Configuración). Ningún token va a los eventos.
"""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import dotenv_values

from app.publicacion.base import (
    DESCONOCIDO, ENTREGADO, ERROR, ESTADOS_EN_BANDEJA, FALLO, NO_SUBIDO, PAUSAR, RECONECTAR, REINTENTABLE,
    SIN_CONFIRMAR, ErrorEnvio, Recuperacion, Registrar,
)
from app.publicacion.horarios import ahora, iso
from app.services.env_manager import ENV_PATH

NOMBRE = "TikTok"
MENSAJE_ENTREGA = "TikTok confirmó: el borrador está en la bandeja"

API = "https://open.tiktokapis.com"
URL_AUTORIZACION = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = "user.info.basic,video.upload"

MB = 1024 * 1024
PARTE_MIN = 5 * MB
PARTE_MAX = 64 * MB
PARTE_GRANDE = 10 * MB          # tamaño de parte para videos de más de PARTE_MAX

REINTENTOS_PARTE = 3
SONDEO_INTERVALO_S = 5
SONDEO_MAX_S = 600              # ~10 min esperando SEND_TO_USER_INBOX
RENOVAR_ANTES = timedelta(hours=1)
TIMEOUT = (15, 120)

_dormir = time.sleep

# error.code de init / status → (tipo, mensaje para el panel)
_CODIGOS = {
    "access_token_invalid": (RECONECTAR, "El token de TikTok es inválido o venció — reconectá la cuenta"),
    "scope_not_authorized": (RECONECTAR, "La cuenta no autorizó el permiso video.upload — reconectá la cuenta"),
    "spam_risk_too_many_pending_share": (
        PAUSAR, "TikTok: demasiados borradores pendientes en 24 h (máx. 5). Activá o descartá los de la bandeja"),
    "spam_risk_user_banned_from_posting": (ERROR, "TikTok: la cuenta tiene prohibido publicar"),
    "rate_limit_exceeded": (REINTENTABLE, "TikTok: límite de llamadas por minuto"),
    "url_ownership_unverified": (ERROR, "TikTok: dominio no verificado"),
    "invalid_param": (ERROR, "TikTok rechazó los parámetros del envío"),
}

# fail_reason de un status FAILED (nada llegó a la bandeja)
_FALLAS = {
    "internal": (REINTENTABLE, "TikTok tuvo un error interno"),
    "auth_removed": (RECONECTAR, "Se revocó el acceso de la app a la cuenta"),
    "spam_risk_too_many_posts": (PAUSAR, "TikTok: se superó el límite de publicaciones por API en 24 h"),
    "spam_risk_too_many_pending_share": (PAUSAR, "TikTok: demasiados borradores pendientes en 24 h"),
    "spam_risk_user_banned_from_posting": (ERROR, "TikTok: la cuenta tiene prohibido publicar"),
    "file_format_check_failed": (ERROR, "TikTok rechazó el formato del video"),
    "duration_check_failed": (ERROR, "TikTok rechazó la duración del video"),
    "frame_rate_check_failed": (ERROR, "TikTok rechazó los fps del video"),
    "picture_size_check_failed": (ERROR, "TikTok rechazó la resolución del video"),
    "spam_risk": (ERROR, "TikTok marcó el envío como riesgoso"),
    "spam_risk_text": (ERROR, "TikTok marcó el texto como riesgoso"),
    "publish_cancelled": (ERROR, "El envío fue cancelado"),
}


# ── Configuración ────────────────────────────────────────────

def credenciales() -> dict:
    valores = dotenv_values(str(ENV_PATH)) if ENV_PATH.exists() else {}
    cred = {
        "client_key": (valores.get("TIKTOK_CLIENT_KEY") or "").strip(),
        "client_secret": (valores.get("TIKTOK_CLIENT_SECRET") or "").strip(),
        "redirect_uri": (valores.get("TIKTOK_REDIRECT_URI") or "").strip(),
    }
    faltan = [k for k, v in cred.items() if not v]
    if faltan:
        raise ValueError("Faltan credenciales de TikTok en Configuración: "
                         + ", ".join(f"TIKTOK_{k.upper()}" for k in faltan))
    return cred


# ── Partes de la subida ──────────────────────────────────────

def plan_partes(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) según las reglas de TikTok."""
    if size <= 0:
        raise ValueError("El video está vacío")
    if size <= PARTE_MAX:
        return size, 1                       # entero (también cubre < 5 MB)
    return PARTE_GRANDE, size // PARTE_GRANDE  # la última absorbe el resto (< 2 partes)


def rangos_partes(size: int) -> list[tuple[int, int]]:
    parte, total = plan_partes(size)
    rangos = []
    for i in range(total):
        inicio = i * parte
        fin = size - 1 if i == total - 1 else inicio + parte - 1
        rangos.append((inicio, fin))
    return rangos


# ── HTTP ─────────────────────────────────────────────────────

def _error_api(resp: requests.Response) -> tuple[str, str, str | None]:
    try:
        cuerpo = resp.json()
    except ValueError:
        return "", "", None
    err = cuerpo.get("error") or {}
    if isinstance(err, dict):
        return err.get("code") or "", err.get("message") or "", err.get("log_id")
    # endpoints de OAuth: {"error": "invalid_grant", "error_description": ..., "log_id": ...}
    return str(err), cuerpo.get("error_description") or "", cuerpo.get("log_id")


def _post_api(ruta: str, token: str, cuerpo: dict, registrar: Registrar, tipo: str) -> dict:
    try:
        resp = requests.post(
            f"{API}{ruta}", json=cuerpo, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        )
    except requests.RequestException as e:
        registrar("error", f"sin conexión con TikTok ({tipo}): {type(e).__name__}", {"excepcion": str(e)[:300]})
        raise ErrorEnvio(REINTENTABLE, "red", f"Sin conexión con TikTok: {type(e).__name__}") from e

    codigo, mensaje, log_id = _error_api(resp)
    detalle = {"http": resp.status_code, "codigo": codigo or None, "log_id": log_id}
    if resp.status_code == 200 and codigo in ("ok", ""):
        try:
            return {"data": resp.json().get("data") or {}, "detalle": detalle}
        except ValueError:
            registrar("error", f"TikTok respondió algo que no es JSON en {tipo}", detalle)
            raise ErrorEnvio(REINTENTABLE, "respuesta_invalida", "TikTok respondió algo inesperado", detalle)

    registrar("error", f"TikTok respondió {resp.status_code} {codigo} en {tipo}: {mensaje}".strip(), detalle)
    if codigo in _CODIGOS:
        t, texto = _CODIGOS[codigo]
        raise ErrorEnvio(t, codigo, texto, detalle)
    if resp.status_code >= 500 or resp.status_code == 429:
        raise ErrorEnvio(REINTENTABLE, codigo or f"http_{resp.status_code}",
                         f"TikTok no disponible (HTTP {resp.status_code})", detalle)
    raise ErrorEnvio(ERROR, codigo or f"http_{resp.status_code}",
                     f"TikTok rechazó el envío: {codigo or resp.status_code} {mensaje}".strip(), detalle)


def _subir_parte(upload_url: str, datos: bytes, inicio: int, fin: int, size: int, ultima: bool,
                 n: int, total: int, registrar: Registrar) -> None:
    esperado = 201 if ultima else 206
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(len(datos)),
        "Content-Range": f"bytes {inicio}-{fin}/{size}",
    }
    for intento in range(1, REINTENTOS_PARTE + 1):
        try:
            resp = requests.put(upload_url, data=datos, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            registrar("error", f"parte {n}/{total}: sin conexión (intento {intento}/{REINTENTOS_PARTE})",
                      {"excepcion": str(e)[:300]})
            if intento == REINTENTOS_PARTE:
                raise ErrorEnvio(REINTENTABLE, "red", f"Se cortó la subida en la parte {n}/{total}") from e
            _dormir(2 * intento)
            continue

        if resp.status_code == esperado:
            detalle = {"http": resp.status_code, "bytes": len(datos), "rango": f"{inicio}-{fin}/{size}"}
            if ultima:
                detalle["subida_completa"] = True   # 201: desde acá puede existir el borrador
            registrar("chunk", f"parte {n}/{total} subida ({len(datos)} bytes)", detalle)
            return
        detalle = {"http": resp.status_code, "rango": f"{inicio}-{fin}/{size}"}
        registrar("error", f"parte {n}/{total}: TikTok respondió {resp.status_code} (esperaba {esperado})", detalle)
        if resp.status_code >= 500 and intento < REINTENTOS_PARTE:
            _dormir(2 * intento)
            continue
        # sin 201 no hay borrador: volver a empezar más tarde es seguro
        raise ErrorEnvio(REINTENTABLE, f"subida_http_{resp.status_code}",
                         f"Falló la subida de la parte {n}/{total} (HTTP {resp.status_code})", detalle)


# ── Publicador ───────────────────────────────────────────────

def _falla(fail_reason: str | None) -> tuple[str, str]:
    return _FALLAS.get(fail_reason or "", (ERROR, f"TikTok rechazó el video ({fail_reason})"))


class PublicadorTikTok:
    def enviar(self, ruta: Path, cuenta: dict, pub: dict, on_publish_id: Callable[[str], None],
               registrar: Registrar, on_sesion: Callable[[str], None] | None = None) -> None:
        token = cuenta["access_token"]
        size = ruta.stat().st_size
        rangos = rangos_partes(size)
        parte, total = plan_partes(size)

        r = _post_api("/v2/post/publish/inbox/video/init/", token, {
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": parte, "total_chunk_count": total},
        }, registrar, "init")
        publish_id = r["data"].get("publish_id")
        upload_url = r["data"].get("upload_url")
        if not publish_id or not upload_url:
            raise ErrorEnvio(REINTENTABLE, "respuesta_incompleta", "TikTok no devolvió publish_id/upload_url",
                             r["detalle"])
        registrar("init", f"TikTok aceptó el envío — publish_id {publish_id}",
                  {**r["detalle"], "publish_id": publish_id, "bytes": size, "partes": total})
        on_publish_id(publish_id)

        with open(ruta, "rb") as f:
            for i, (inicio, fin) in enumerate(rangos):
                f.seek(inicio)
                datos = f.read(fin - inicio + 1)
                _subir_parte(upload_url, datos, inicio, fin, size, i == len(rangos) - 1,
                             i + 1, len(rangos), registrar)

        self._esperar_bandeja(publish_id, cuenta, registrar)

    def _esperar_bandeja(self, publish_id: str, cuenta: dict, registrar: Registrar) -> None:
        ultimo = None
        for _ in range(max(1, SONDEO_MAX_S // SONDEO_INTERVALO_S)):
            try:
                status, fail_reason = self.consultar(publish_id, cuenta, registrar, solo_cambios=ultimo)
            except ErrorEnvio:
                status, fail_reason = None, None   # ya quedó registrado; seguir esperando
            if status in ESTADOS_EN_BANDEJA:
                return
            if status == "FAILED":
                tipo, texto = _falla(fail_reason)
                raise ErrorEnvio(tipo, fail_reason or "failed", texto, {"status": status, "fail_reason": fail_reason})
            ultimo = status or ultimo
            _dormir(SONDEO_INTERVALO_S)
        raise ErrorEnvio(SIN_CONFIRMAR, "sin_confirmacion",
                         f"El video se subió pero TikTok no confirmó la bandeja en {SONDEO_MAX_S // 60} min "
                         f"(último estado: {ultimo or 'desconocido'})")

    def consultar(self, publish_id: str, cuenta: dict, registrar: Registrar,
                  solo_cambios: str | None = None) -> tuple[str, str | None]:
        r = _post_api("/v2/post/publish/status/fetch/", cuenta["access_token"],
                      {"publish_id": publish_id}, registrar, "status")
        status = r["data"].get("status") or ""
        fail_reason = r["data"].get("fail_reason")
        if status != solo_cambios:
            registrar("status", f"TikTok: {status}" + (f" ({fail_reason})" if fail_reason else ""),
                      {**r["detalle"], "status": status, "fail_reason": fail_reason})
        return status, fail_reason

    def recuperar(self, pub: dict, cuenta: dict, registrar: Registrar) -> Recuperacion:
        if not pub["publish_id"]:
            return Recuperacion(NO_SUBIDO, "se interrumpió antes de que TikTok aceptara el envío (no hay borrador)")
        try:
            status, fail_reason = self.consultar(pub["publish_id"], cuenta, registrar)
        except ErrorEnvio as e:
            return Recuperacion(DESCONOCIDO, f"no se pudo consultar a TikTok: {e.mensaje}", e)
        if status in ESTADOS_EN_BANDEJA:
            return Recuperacion(ENTREGADO, f"TikTok confirmó tras la interrupción ({status})")
        if status == "FAILED":
            tipo, texto = _falla(fail_reason)
            return Recuperacion(FALLO, texto, ErrorEnvio(tipo, fail_reason or "failed", texto))
        if status == "PROCESSING_UPLOAD" and not pub["subida_completa"]:
            return Recuperacion(NO_SUBIDO, "la subida quedó a medias (no hay borrador)")
        return Recuperacion(DESCONOCIDO, f"TikTok responde {status or 'sin estado'} — verificá la bandeja en la app")


# ── OAuth ────────────────────────────────────────────────────

def url_autorizacion(state: str) -> str:
    cred = credenciales()
    return URL_AUTORIZACION + "?" + urlencode({
        "client_key": cred["client_key"],
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": cred["redirect_uri"],
        "state": state,
    })


def leer_url_de_vuelta(url_pegada: str) -> tuple[str, str]:
    """(code, state) de la URL a la que TikTok devolvió al usuario."""
    q = parse_qs(urlparse(url_pegada.strip()).query)
    if q.get("error"):
        raise ValueError(f"TikTok no autorizó: {q['error'][0]} {q.get('error_description', [''])[0]}".strip())
    if not q.get("code") or not q.get("state"):
        raise ValueError("La URL pegada no tiene code/state — copiá la URL completa de la barra del navegador")
    return q["code"][0], q["state"][0]


def _pedir_token(campos: dict) -> dict:
    try:
        resp = requests.post(f"{API}/v2/oauth/token/", data=campos, timeout=TIMEOUT,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    except requests.RequestException as e:
        raise ErrorEnvio(REINTENTABLE, "red", f"Sin conexión con TikTok: {type(e).__name__}") from e
    codigo, mensaje, log_id = _error_api(resp)
    try:
        cuerpo = resp.json()
    except ValueError:
        cuerpo = {}
    if resp.status_code != 200 or codigo or not cuerpo.get("access_token"):
        detalle = {"http": resp.status_code, "codigo": codigo or None, "log_id": log_id}
        if resp.status_code >= 500:
            raise ErrorEnvio(REINTENTABLE, codigo or f"http_{resp.status_code}", "TikTok no disponible", detalle)
        raise ErrorEnvio(RECONECTAR, codigo or f"http_{resp.status_code}",
                         f"TikTok rechazó el token: {codigo} {mensaje}".strip(), detalle)
    momento = ahora()
    return {
        "open_id": cuerpo.get("open_id"),
        "access_token": cuerpo["access_token"],
        "access_vence": iso(momento + timedelta(seconds=int(cuerpo.get("expires_in") or 0))),
        "refresh_token": cuerpo.get("refresh_token"),
        "refresh_vence": iso(momento + timedelta(seconds=int(cuerpo.get("refresh_expires_in") or 0))),
        "scope": cuerpo.get("scope") or "",
    }


def canjear_codigo(code: str) -> dict:
    cred = credenciales()
    tokens = _pedir_token({
        "client_key": cred["client_key"], "client_secret": cred["client_secret"],
        "code": code, "grant_type": "authorization_code", "redirect_uri": cred["redirect_uri"],
    })
    if "video.upload" not in tokens.pop("scope").split(","):
        raise ValueError("La cuenta no otorgó el permiso video.upload — volvé a conectar y aceptalo")
    return tokens


def renovar(refresh_token: str) -> dict:
    cred = credenciales()
    tokens = _pedir_token({
        "client_key": cred["client_key"], "client_secret": cred["client_secret"],
        "grant_type": "refresh_token", "refresh_token": refresh_token,
    })
    tokens.pop("scope", None)
    return tokens


def necesita_renovar(cuenta: dict) -> bool:
    if not cuenta.get("access_vence"):
        return True
    return datetime.fromisoformat(cuenta["access_vence"]) - ahora() < RENOVAR_ANTES


def nombre_usuario(access_token: str) -> str | None:
    """display_name de la cuenta (solo para mostrar; si falla, no importa).
    Solo display_name: username exige el scope user.info.profile, que no pedimos."""
    try:
        resp = requests.get(f"{API}/v2/user/info/", params={"fields": "open_id,display_name"},
                            headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT)
        return ((resp.json().get("data") or {}).get("user") or {}).get("display_name")
    except (requests.RequestException, ValueError):
        return None
