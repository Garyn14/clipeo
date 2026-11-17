"""
test_ai_client.py — Tests unitarios para ai_client/ (client.py + manual_provider.py).

Ninguno de estos tests llama a la red: el proveedor "anthropic" solo se verifica por
isinstance/errores de configuración, y el proveedor "manual" se prueba con _PENDING_DIR
apuntando a tmp_path.
"""

import json
import uuid

import anthropic
import pytest

import ai_client.client as ai_client_module
import ai_client.manual_provider as manual_module
from ai_client import get_client
from ai_client.cli_provider import ClaudeCliClient
from ai_client.manual_provider import ManualClient


# ─────────────────────────────────────────
#  get_client() — selección de proveedor
# ─────────────────────────────────────────

def test_get_client_default_devuelve_claude_cli(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("PIPELINE_TRACE_DIR", raising=False)
    client = get_client()
    assert isinstance(client, ClaudeCliClient)


def test_get_client_explicito_anthropic_devuelve_anthropic_real(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-key")
    client = get_client()
    assert isinstance(client, anthropic.Anthropic)


def test_get_client_sin_api_key_falla_claro(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        get_client()


def test_get_client_provider_desconocido_falla_claro(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="AI_PROVIDER"):
        get_client()


def test_get_client_manual_devuelve_manual_client(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "manual")
    client = get_client()
    assert isinstance(client, ManualClient)


def test_get_client_provider_respeta_mayusculas_y_espacios(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "  MANUAL  ")
    client = get_client()
    assert isinstance(client, ManualClient)


# ─────────────────────────────────────────
#  ManualClient.messages.create() — protocolo de archivos
# ─────────────────────────────────────────

def test_manual_client_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_module, "_PENDING_DIR", tmp_path)
    monkeypatch.setattr(manual_module.uuid, "uuid4", lambda: uuid.UUID(int=1))

    request_id = uuid.UUID(int=1).hex[:12]
    response_path = tmp_path / f"{request_id}.response.json"
    response_path.write_text(
        json.dumps({"text": '{"picos": []}'}), encoding="utf-8"
    )

    client = ManualClient()
    response = client.messages.create(model="claude-sonnet-4-6", max_tokens=512, messages=[])

    assert response.content[0].text == '{"picos": []}'
    # ambos archivos quedan limpios tras una respuesta exitosa
    assert not (tmp_path / f"{request_id}.request.json").exists()
    assert not response_path.exists()


def test_manual_client_serializa_kwargs_anidados(tmp_path, monkeypatch):
    # Caso real de uso: system=lista de bloques con cache_control (agent2/3),
    # messages=lista de bloques (agent1/3) — confirma que create() no falla al
    # serializar estructuras anidadas, solo strings/dicts planos.
    monkeypatch.setattr(manual_module, "_PENDING_DIR", tmp_path)
    monkeypatch.setattr(manual_module.uuid, "uuid4", lambda: uuid.UUID(int=2))

    request_id = uuid.UUID(int=2).hex[:12]
    (tmp_path / f"{request_id}.response.json").write_text(
        json.dumps({"text": "ok"}), encoding="utf-8"
    )

    kwargs = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 512,
        "system": [{"type": "text", "text": "prompt", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hola"}]}],
    }

    client = ManualClient()
    response = client.messages.create(**kwargs)
    assert response.content[0].text == "ok"


def test_manual_client_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_module, "_PENDING_DIR", tmp_path)
    monkeypatch.setattr(manual_module, "_DEFAULT_TIMEOUT", 0.01)
    monkeypatch.setattr(manual_module, "_POLL_INTERVAL", 0.01)
    monkeypatch.setattr(manual_module.uuid, "uuid4", lambda: uuid.UUID(int=3))

    client = ManualClient()
    with pytest.raises(RuntimeError, match="Timeout"):
        client.messages.create(model="claude-sonnet-4-6", max_tokens=512, messages=[])

    # la request huérfana se limpia tras el timeout
    request_id = uuid.UUID(int=3).hex[:12]
    assert not (tmp_path / f"{request_id}.request.json").exists()


def test_manual_client_respuesta_sin_clave_text_falla_claro(tmp_path, monkeypatch):
    monkeypatch.setattr(manual_module, "_PENDING_DIR", tmp_path)
    monkeypatch.setattr(manual_module.uuid, "uuid4", lambda: uuid.UUID(int=4))

    request_id = uuid.UUID(int=4).hex[:12]
    (tmp_path / f"{request_id}.response.json").write_text(
        json.dumps({"otra_clave": "x"}), encoding="utf-8"
    )

    client = ManualClient()
    with pytest.raises(RuntimeError, match='"text"'):
        client.messages.create(model="claude-sonnet-4-6", max_tokens=512, messages=[])
