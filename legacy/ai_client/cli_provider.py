"""
ai_client/cli_provider.py — proveedor "claude_cli": responde cada llamada con Claude Code en
modo headless (`claude -p`), usando la sesión iniciada en la máquina (suscripción) en vez de
la API de Anthropic. No requiere ANTHROPIC_API_KEY.

Uso interno: no se usa directo — se obtiene vía ai_client.get_client() con
AI_PROVIDER=claude_cli (default).

Aislamiento: cada llamada corre en un proceso nuevo, desde un directorio temporal neutro,
sin herramientas, sin settings de usuario/proyecto (no carga CLAUDE.md ni memorias), sin
MCP, sin skills y sin persistir la sesión. El system prompt del agente reemplaza al de
Claude Code, así que se comporta como una llamada directa a la API: entra el prompt, sale
el texto.

Mapeo desde los kwargs del SDK (los mismos que reciben los agentes):
    system          → --system-prompt-file (str o lista de bloques de texto, se aplanan;
                      por archivo porque el wrapper claude.CMD de Windows trunca
                      argumentos multilínea)
    messages        → texto por stdin (bloques {"type": "text"} aplanados; cache_control
                      se ignora). Por stdin y no como argumento: las transcripciones
                      superan el límite de longitud de línea de comando de Windows.
    model           → se ignora el id del agente; se usa AI_CLI_MODEL (default "sonnet")
    max_tokens, temperature → sin equivalente en la CLI, se ignoran
"""

import json
import os
import shutil
import subprocess
import tempfile

from ._response import TextResponse
from .errors import AIFatalError, AIRetryableError

_DEFAULT_MODEL   = "sonnet"
_DEFAULT_TIMEOUT = 600  # segundos por llamada

_FLAGS_AISLAMIENTO = [
    "--tools", "",
    "--setting-sources", "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--output-format", "json",
]

# api_error_status que no se arreglan reintentando: credenciales, modelo inexistente,
# request inválida (ej. prompt demasiado largo).
_STATUS_FATALES = {400, 401, 403, 404}

_PISTAS_FATALES = ("not logged in", "/login", "please log in", "invalid api key", "authentication")


def _texto_de_bloques(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    partes = []
    for bloque in contenido or []:
        if isinstance(bloque, dict) and bloque.get("type") == "text":
            partes.append(bloque.get("text", ""))
        elif isinstance(bloque, str):
            partes.append(bloque)
    return "\n\n".join(p for p in partes if p)


def _texto_de_mensajes(messages: list) -> str:
    partes = []
    for msg in messages or []:
        texto = _texto_de_bloques(msg.get("content", ""))
        if not texto:
            continue
        if msg.get("role", "user") != "user":
            texto = f"[{msg['role'].upper()}]\n{texto}"
        partes.append(texto)
    return "\n\n".join(partes)


def _resolver_ejecutable() -> str:
    exe = os.environ.get("AI_CLI_PATH", "").strip() or shutil.which("claude")
    if not exe:
        raise AIFatalError(
            "[AI_CLIENT] No se encontró el ejecutable 'claude' (Claude Code) en PATH — "
            "instálalo o define AI_CLI_PATH. Alternativa: AI_PROVIDER=anthropic."
        )
    return exe


def _error_desde_salida(data: dict | None, stdout: str, stderr: str, returncode: int) -> Exception:
    status  = (data or {}).get("api_error_status")
    mensaje = (data or {}).get("result") or stderr.strip() or stdout.strip() or f"exit {returncode}"
    detalle = f"[AI_CLIENT] Claude CLI falló (exit {returncode}, status {status}): {mensaje[:500]}"

    if status in _STATUS_FATALES:
        return AIFatalError(detalle)
    texto = f"{mensaje} {stderr}".lower()
    if status is None and any(p in texto for p in _PISTAS_FATALES):
        return AIFatalError(detalle)
    # 429 (límite de uso / rate limit), 5xx, 529 (overloaded), cortes de red y lo
    # desconocido: transitorio.
    return AIRetryableError(detalle)


class _CliMessages:
    def create(self, **kwargs) -> TextResponse:
        exe     = _resolver_ejecutable()
        model   = os.environ.get("AI_CLI_MODEL", "").strip() or _DEFAULT_MODEL
        timeout = int(os.environ.get("AI_CLI_TIMEOUT", "").strip() or _DEFAULT_TIMEOUT)

        cmd = [exe, "-p", "--model", model, *_FLAGS_AISLAMIENTO]
        system = _texto_de_bloques(kwargs.get("system"))
        prompt = _texto_de_mensajes(kwargs.get("messages", []))

        env = dict(os.environ)
        env["DISABLE_AUTOUPDATER"] = "1"  # corridas largas chocan con el auto-update ("claude.exe in use")
        env.pop("ANTHROPIC_API_KEY", None)  # forzar la sesión de la suscripción, no la API

        with tempfile.TemporaryDirectory(prefix="ai_cli_") as cwd_neutro:
            if system:
                # Por archivo, no como argumento: en Windows `claude` es un wrapper .CMD y
                # cmd.exe corta los argumentos en el primer salto de línea — el modelo
                # recibía solo la primera línea del prompt del agente.
                system_path = os.path.join(cwd_neutro, "system_prompt.txt")
                with open(system_path, "w", encoding="utf-8") as f:
                    f.write(system)
                cmd += ["--system-prompt-file", system_path]
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=cwd_neutro,
                    env=env,
                )
            except subprocess.TimeoutExpired as e:
                raise AIRetryableError(
                    f"[AI_CLIENT] Claude CLI no respondió en {timeout}s"
                ) from e
            except OSError as e:
                raise AIFatalError(f"[AI_CLIENT] No se pudo ejecutar Claude CLI: {e}") from e

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = None

        if proc.returncode != 0 or data is None or data.get("is_error"):
            raise _error_desde_salida(data, stdout, stderr, proc.returncode)

        texto = data.get("result") or ""
        if not texto.strip():
            raise AIRetryableError("[AI_CLIENT] Claude CLI devolvió una respuesta vacía")

        return TextResponse(texto, meta={
            "proveedor":       "claude_cli",
            "modelo":          model,
            "duracion_api_ms": data.get("duration_api_ms"),
            "usage":           data.get("usage"),
        })


class ClaudeCliClient:
    def __init__(self):
        self.messages = _CliMessages()
