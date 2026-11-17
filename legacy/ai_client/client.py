"""
ai_client/client.py — selección de proveedor de IA.

Uso interno:
    from ai_client import get_client
    client = get_client()   # ClaudeCliClient, anthropic.Anthropic real o ManualClient según AI_PROVIDER

La variable de entorno AI_PROVIDER decide el proveedor:
    AI_PROVIDER=claude_cli (default) — Claude Code headless (`claude -p`) con la sesión iniciada
                                        en la máquina; sin ANTHROPIC_API_KEY — ver
                                        ai_client/cli_provider.py.
    AI_PROVIDER=anthropic            — llama a la API real de Anthropic.
    AI_PROVIDER=manual               — no llama a ninguna API; escribe la request a disco
                                        (ai_client/_pending/) y espera que alguien escriba
                                        la respuesta a mano — ver ai_client/manual_provider.py.
                                        Solo para depuración.

Trazabilidad: si PIPELINE_TRACE_DIR está definida (la define core/pasos.py por cada paso del
pipeline), cada llamada queda guardada ahí como <n>_request.json + <n>_response.json (o
<n>_error.json), con cualquier proveedor. Es lo que muestra la web al abrir un paso.
"""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import anthropic

from .cli_provider import ClaudeCliClient
from .manual_provider import ManualClient

_PROVIDERS = ("claude_cli", "anthropic", "manual")


def get_client():
    """Devuelve un cliente con `.messages.create(...)` según AI_PROVIDER."""
    provider = os.environ.get("AI_PROVIDER", "claude_cli").strip().lower()

    if provider == "claude_cli":
        client = ClaudeCliClient()
    elif provider == "manual":
        client = ManualClient()
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "[AI_CLIENT] ANTHROPIC_API_KEY no configurada en .env — "
                "no se puede usar AI_PROVIDER=anthropic. "
                "Usa AI_PROVIDER=claude_cli (default) para responder con Claude Code."
            )
        client = anthropic.Anthropic(api_key=api_key)
    else:
        raise RuntimeError(
            f"[AI_CLIENT] AI_PROVIDER desconocido: '{provider}' — usa uno de: {', '.join(_PROVIDERS)}"
        )

    trace_dir = os.environ.get("PIPELINE_TRACE_DIR", "").strip()
    if trace_dir:
        client.messages = _TracingMessages(client.messages, Path(trace_dir), provider)
    return client


def _meta_de_respuesta(response, provider: str) -> dict:
    meta = getattr(response, "meta", None)
    if meta:
        return meta
    usage = getattr(response, "usage", None)
    if usage is not None and hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    return {"proveedor": provider, "usage": usage}


class _TracingMessages:
    """Envuelve `.messages` de cualquier proveedor y guarda request/response a disco."""

    def __init__(self, inner, trace_dir: Path, provider: str):
        self._inner     = inner
        self._trace_dir = trace_dir
        self._provider  = provider

    def _siguiente_n(self) -> int:
        return len(list(self._trace_dir.glob("*_request.json"))) + 1

    def _escribir(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def create(self, **kwargs):
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        n  = self._siguiente_n()
        t0 = time.time()
        self._escribir(self._trace_dir / f"{n:03d}_request.json", kwargs)

        try:
            response = self._inner.create(**kwargs)
        except Exception as e:
            self._escribir(self._trace_dir / f"{n:03d}_error.json", {
                "tipo":       type(e).__name__,
                "mensaje":    str(e),
                "duracion_s": round(time.time() - t0, 2),
            })
            raise

        self._escribir(self._trace_dir / f"{n:03d}_response.json", {
            "text":       response.content[0].text,
            "duracion_s": round(time.time() - t0, 2),
            "meta":       _meta_de_respuesta(response, self._provider),
        })
        return response
