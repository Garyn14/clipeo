"""
env_manager.py — Ver/editar las variables de .env que hoy se editan a mano
(COLAB_TRANSCRIBE_URL en particular: cambia cada vez que se reinicia el
notebook de Colab, porque el túnel de Cloudflare es efímero).

Solo gestiona el set fijo de claves en ENV_FIELDS — no es un editor de .env
genérico. Los secretos (ANTHROPIC_API_KEY, HF_TOKEN, COLAB_AUTH_TOKEN) nunca
se devuelven en texto plano por la API, solo enmascarados; se pueden
sobreescribir pero no leer de vuelta.

Escribir acá no afecta al proceso del backend en sí (no usa estas variables
directamente) — pipeline.py hace su propio load_dotenv() al arrancar como
subproceso nuevo, así que un cambio guardado acá aplica desde la
PRÓXIMA corrida lanzada, no reinicia nada. Excepción: COLAB_TRANSCRIBE_URL y
COLAB_AUTH_TOKEN se releen del archivo en cada intento de transcripción
(video_transcriber._colab_config), así que también los toma el siguiente
reintento de una corrida en curso.
"""

from pathlib import Path

from dotenv import dotenv_values, set_key

from app.paths import PROJECT_ROOT

def _resolver_env() -> Path:
    """legacy/.env si existe; si no, el .env de la raíz del repo (en la laptop del operador vive ahí: sin esto las
    credenciales de TikTok/YouTube no se encontraban y la publicación quedaba en 'requiere_reconexion')."""
    propio, raiz = PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"
    return propio if propio.exists() or not raiz.exists() else raiz


ENV_PATH = _resolver_env()

ENV_FIELDS = [
    {
        "key": "COLAB_TRANSCRIBE_URL",
        "seccion": "transcripcion",
        "avanzado": False,
        "label": "URL de transcripción (Colab)",
        "secret": False,
        "help": "URL del túnel de Colab (con o sin /transcribe) — cambia cada vez que reinicias el notebook. "
                "Un cambio aplica también al siguiente reintento de una corrida en curso.",
    },
    {
        "key": "COLAB_AUTH_TOKEN",
        "seccion": "transcripcion",
        "avanzado": False,
        "label": "Token de auth de Colab",
        "secret": True,
        "help": "Debe coincidir con AUTH_TOKEN del notebook.",
    },
    {
        "key": "AI_PROVIDER",
        "seccion": "ia",
        "avanzado": False,
        "label": "Proveedor de IA",
        "secret": False,
        "help": "claude_cli (default: Claude Code con la sesión de esta máquina, sin API key), "
                "anthropic (API real) o manual (solo depuración).",
    },
    {
        "key": "ANTHROPIC_API_KEY",
        "seccion": "ia",
        "avanzado": True,
        "label": "Anthropic API key",
        "secret": True,
        "help": "Solo si AI_PROVIDER=anthropic.",
    },
    {
        "key": "HF_TOKEN",
        "seccion": "transcripcion",
        "avanzado": True,
        "label": "Hugging Face token",
        "secret": True,
        "help": "Opcional — activa diarización de hablantes (pyannote) en WhisperX.",
    },
    {
        "key": "TIKTOK_CLIENT_KEY",
        "seccion": "tiktok",
        "avanzado": False,
        "label": "TikTok — Client key",
        "secret": False,
        "help": "De tu app en TikTok for Developers (producto Content Posting API, permiso video.upload). "
                "Se usa al conectar una cuenta real en Publicaciones.",
    },
    {
        "key": "TIKTOK_CLIENT_SECRET",
        "seccion": "tiktok",
        "avanzado": False,
        "label": "TikTok — Client secret",
        "secret": True,
        "help": "De la misma app de TikTok for Developers.",
    },
    {
        "key": "TIKTOK_REDIRECT_URI",
        "seccion": "tiktok",
        "avanzado": True,
        "label": "TikTok — Redirect URI",
        "secret": False,
        "help": "Exactamente la registrada en la app de TikTok (tiene que ser https). No hace falta que cargue: "
                "al conectar, pegas en el panel la URL a la que te devolvió TikTok.",
    },
    {
        "key": "YOUTUBE_CLIENT_ID",
        "seccion": "youtube",
        "avanzado": False,
        "label": "YouTube — Client ID",
        "secret": False,
        "help": "Del cliente OAuth (tipo Aplicación web) de tu proyecto en Google Cloud con YouTube Data API v3 "
                "activada. Se usa al conectar el canal en Publicaciones → YouTube Shorts.",
    },
    {
        "key": "YOUTUBE_CLIENT_SECRET",
        "seccion": "youtube",
        "avanzado": False,
        "label": "YouTube — Client secret",
        "secret": True,
        "help": "Del mismo cliente OAuth de Google Cloud.",
    },
    {
        "key": "YOUTUBE_REDIRECT_URI",
        "seccion": "youtube",
        "avanzado": True,
        "label": "YouTube — Redirect URI",
        "secret": False,
        "help": "Opcional. Por defecto http://localhost:8000/publicaciones/cuentas/youtube/callback; tiene que "
                "estar registrada tal cual en el cliente OAuth de Google.",
    },
    {
        "key": "PUBLICACION_SIMULAR_FALLA",
        "seccion": "pruebas",
        "avanzado": True,
        "label": "Publicación — simular falla (solo cuentas de prueba)",
        "secret": False,
        "help": "Vacío = el envío simulado sale bien. Para probar el panel: red, token, pendientes, formato "
                "o sin_confirmar. Aplica desde el siguiente envío, no afecta cuentas reales.",
    },
]

_VALID_KEYS = {f["key"] for f in ENV_FIELDS}


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}···{value[-4:]}"


def list_env_status() -> list[dict]:
    values = dotenv_values(str(ENV_PATH)) if ENV_PATH.exists() else {}
    resultado = []
    for field in ENV_FIELDS:
        raw = (values.get(field["key"]) or "").strip()
        resultado.append({
            "key": field["key"],
            "label": field["label"],
            "help": field["help"],
            "secret": field["secret"],
            "seccion": field["seccion"],
            "avanzado": field["avanzado"],
            "is_set": bool(raw),
            "value": "" if field["secret"] else raw,
            "masked_value": _mask(raw) if field["secret"] and raw else "",
        })
    return resultado


def update_env(updates: dict[str, str]) -> None:
    claves_invalidas = set(updates) - _VALID_KEYS
    if claves_invalidas:
        raise ValueError(f"Campo(s) no editable(s): {', '.join(sorted(claves_invalidas))}")

    if not ENV_PATH.exists():
        ENV_PATH.touch()

    for key, value in updates.items():
        set_key(str(ENV_PATH), key, value.strip(), quote_mode="never")


def escribir_clave_interna(key: str, value: str) -> None:
    """Escribe una clave que la app gestiona por su cuenta y no se edita como campo (p. ej. AI_CLI_PERFIL, CLIP-83)."""
    if not ENV_PATH.exists():
        ENV_PATH.touch()
    set_key(str(ENV_PATH), key, value.strip(), quote_mode="never")
