"""
ai_client/manual_provider.py — proveedor "manual": protocolo de archivos request/response
que reemplaza la llamada real a Claude por una respuesta escrita a mano (ej. por un agente
de Claude Code en la misma sesión), sin gastar la API de Anthropic.

Uso interno: no se usa directo — se obtiene vía ai_client.get_client() con AI_PROVIDER=manual.

Protocolo: cada llamada a ManualClient.messages.create(**kwargs) escribe kwargs (los mismos
parámetros que irían a client.messages.create() en la API real: model, system, messages,
max_tokens) como JSON en ai_client/_pending/<id>.request.json, y espera a que aparezca
ai_client/_pending/<id>.response.json con {"text": "<respuesta que Claude habría devuelto>"}.
Ese texto se expone como response.content[0].text, igual que el SDK real — el agente que
hizo la llamada no distingue una respuesta manual de una real.
"""

import json
import time
import uuid
from pathlib import Path

_PENDING_DIR = Path(__file__).parent / "_pending"

_DEFAULT_TIMEOUT = 1800  # segundos — mismo orden que el timeout de transcripción por Colab
_POLL_INTERVAL = 2       # segundos — más corto que el de Colab (10s) a propósito: acá se
                         # espera latencia humana respondiendo, no un servidor que no hay
                         # que golpear seguido
_MAX_DECODE_FALLOS = 5   # lecturas fallidas seguidas (archivo de respuesta a medio escribir)
                         # antes de rendirse, en vez de fallar en la primera


class _ManualBlock:
    def __init__(self, text: str):
        self.text = text


class _ManualResponse:
    def __init__(self, text: str):
        self.content = [_ManualBlock(text)]


class _ManualMessages:
    def create(self, **kwargs) -> _ManualResponse:
        _PENDING_DIR.mkdir(parents=True, exist_ok=True)

        request_id = uuid.uuid4().hex[:12]
        request_path = _PENDING_DIR / f"{request_id}.request.json"
        response_path = _PENDING_DIR / f"{request_id}.response.json"

        request_path.write_text(
            json.dumps(kwargs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[AI_CLIENT] Modo manual — request escrita: {request_path}")
        print(
            f"[AI_CLIENT] Esperando respuesta en: {response_path} "
            f"(timeout {_DEFAULT_TIMEOUT}s)"
        )

        try:
            text = self._esperar_respuesta(request_id, response_path)
        finally:
            # Si no hubo éxito (timeout, Ctrl+C, excepción), no dejar la request
            # huérfana en _pending/ — solo se conserva mientras se sigue esperando.
            if not response_path.exists():
                request_path.unlink(missing_ok=True)

        request_path.unlink(missing_ok=True)
        self._borrar_best_effort(response_path)
        return _ManualResponse(text)

    def _esperar_respuesta(self, request_id: str, response_path: Path) -> str:
        elapsed = 0
        fallos_decode = 0
        while True:
            if response_path.exists():
                try:
                    data = json.loads(response_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    # Puede estar a medio escribir todavía — no es un fallo real
                    # salvo que se repita demasiadas veces seguidas.
                    fallos_decode += 1
                    if fallos_decode > _MAX_DECODE_FALLOS:
                        raise RuntimeError(
                            f"[AI_CLIENT] {response_path} existe pero no se pudo "
                            f"leer como JSON válido tras {fallos_decode} intentos"
                        )
                else:
                    if "text" not in data:
                        raise RuntimeError(
                            f"[AI_CLIENT] {response_path} no tiene la clave \"text\" "
                            f"esperada — contenido: {data}"
                        )
                    return data["text"]

            if elapsed >= _DEFAULT_TIMEOUT:
                request_path = _PENDING_DIR / f"{request_id}.request.json"
                raise RuntimeError(
                    f"[AI_CLIENT] Timeout ({_DEFAULT_TIMEOUT}s) esperando respuesta "
                    f"manual para {request_id} — ver {request_path}"
                )

            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

    @staticmethod
    def _borrar_best_effort(path: Path) -> None:
        # Windows puede mantener el archivo brevemente bloqueado (editor/antivirus)
        # justo después de guardarlo — no vale la pena hacer fallar la corrida por
        # un archivo temporal que no se pudo borrar.
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            print(f"[AI_CLIENT] ⚠️  No se pudo borrar {path} (en uso) — queda como residuo")


class ManualClient:
    def __init__(self):
        self.messages = _ManualMessages()
