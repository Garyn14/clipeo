"""
ai_client/client.py — selección de proveedor de IA (API real de Anthropic o modo manual).

Uso interno:
    from ai_client import get_client
    client = get_client()   # anthropic.Anthropic real, o ManualClient según AI_PROVIDER

La variable de entorno AI_PROVIDER decide el proveedor:
    AI_PROVIDER=anthropic (default)  — llama a la API real de Anthropic.
    AI_PROVIDER=manual               — no llama a ninguna API; escribe la request a disco
                                        (ai_client/_pending/) y espera que alguien (ej. un
                                        agente de Claude Code en la misma sesión) escriba
                                        la respuesta a mano, con el mismo punto de contacto
                                        que usa el SDK real (.content[0].text) — ver
                                        ai_client/manual_provider.py.
"""

import os

from dotenv import load_dotenv
load_dotenv()

import anthropic

from .manual_provider import ManualClient


def get_client():
    """Devuelve un cliente con `.messages.create(...)` según AI_PROVIDER."""
    provider = os.environ.get("AI_PROVIDER", "anthropic").strip().lower()

    if provider == "manual":
        return ManualClient()

    if provider != "anthropic":
        raise RuntimeError(
            f"[AI_CLIENT] AI_PROVIDER desconocido: '{provider}' — usa 'anthropic' o 'manual'"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "[AI_CLIENT] ANTHROPIC_API_KEY no configurada en .env — "
            "no se puede usar AI_PROVIDER=anthropic (default). "
            "Usa AI_PROVIDER=manual para probar sin gastar la API."
        )
    return anthropic.Anthropic(api_key=api_key)
