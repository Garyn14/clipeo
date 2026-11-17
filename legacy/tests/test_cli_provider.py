"""
test_cli_provider.py — Tests unitarios para ai_client/cli_provider.py y el wrapper de
trazabilidad de ai_client/client.py.

Ninguno ejecuta Claude Code de verdad: subprocess.run se reemplaza por un fake que registra
el comando/stdin y devuelve la salida JSON que daría `claude -p --output-format json`.
"""

import json
import subprocess

import pytest

import ai_client.cli_provider as cli_module
from ai_client import AIFatalError, AIRetryableError, get_client
from ai_client.cli_provider import ClaudeCliClient


class _FakeRun:
    def __init__(self, stdout="", stderr="", returncode=0, exc=None):
        self.stdout, self.stderr, self.returncode, self.exc = stdout, stderr, returncode, exc
        self.llamadas = []

    def __call__(self, cmd, **kwargs):
        system = None
        if "--system-prompt-file" in cmd:
            # El archivo vive en un directorio temporal que se borra al volver de create()
            with open(cmd[cmd.index("--system-prompt-file") + 1], encoding="utf-8") as f:
                system = f.read()
        self.llamadas.append({"cmd": cmd, "system": system, **kwargs})
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def _salida_ok(texto: str) -> str:
    return json.dumps({
        "is_error": False, "result": texto, "duration_api_ms": 1234,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })


@pytest.fixture
def fake_run(monkeypatch):
    def _instalar(**kwargs):
        fake = _FakeRun(**kwargs)
        monkeypatch.setattr(cli_module.subprocess, "run", fake)
        monkeypatch.setattr(cli_module.shutil, "which", lambda _: "claude")
        monkeypatch.delenv("AI_CLI_PATH", raising=False)
        monkeypatch.delenv("AI_CLI_MODEL", raising=False)
        return fake
    return _instalar


# ─────────────────────────────────────────
#  Mapeo de kwargs → comando / stdin
# ─────────────────────────────────────────

def test_mapea_system_mensajes_y_modelo(fake_run):
    fake = fake_run(stdout=_salida_ok('{"picos": []}'))

    resp = ClaudeCliClient().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system="Eres un detector\nREGLA FINAL: solo JSON",
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "PROMPT DEL NICHO", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "TRANSCRIPCION"},
        ]}],
    )

    assert resp.content[0].text == '{"picos": []}'
    assert resp.meta["duracion_api_ms"] == 1234
    llamada = fake.llamadas[0]
    cmd = llamada["cmd"]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "sonnet"          # ignora el id del agente
    assert "--system-prompt" not in cmd                        # multilínea: solo por archivo
    assert llamada["system"] == "Eres un detector\nREGLA FINAL: solo JSON"
    assert cmd[cmd.index("--tools") + 1] == ""                 # sin herramientas
    assert "--no-session-persistence" in cmd
    assert llamada["input"] == "PROMPT DEL NICHO\n\nTRANSCRIPCION"
    assert llamada["env"]["DISABLE_AUTOUPDATER"] == "1"
    assert "ANTHROPIC_API_KEY" not in llamada["env"]


def test_system_como_lista_de_bloques(fake_run):
    fake = fake_run(stdout=_salida_ok("ok"))
    ClaudeCliClient().messages.create(
        system=[{"type": "text", "text": "parte A"}, {"type": "text", "text": "parte B"}],
        messages=[{"role": "user", "content": "hola"}],
    )
    assert fake.llamadas[0]["system"] == "parte A\n\nparte B"


def test_sin_system_no_pasa_flag(fake_run):
    fake = fake_run(stdout=_salida_ok("ok"))
    ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "hola"}])
    assert "--system-prompt-file" not in fake.llamadas[0]["cmd"]


def test_respeta_ai_cli_model(fake_run, monkeypatch):
    fake = fake_run(stdout=_salida_ok("ok"))
    monkeypatch.setenv("AI_CLI_MODEL", "opus")
    ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "hola"}])
    cmd = fake.llamadas[0]["cmd"]
    assert cmd[cmd.index("--model") + 1] == "opus"


# ─────────────────────────────────────────
#  Clasificación de errores
# ─────────────────────────────────────────

@pytest.mark.parametrize("status", [429, 500, 529])
def test_status_transitorios_son_reintentables(fake_run, status):
    fake_run(returncode=1, stdout=json.dumps({
        "is_error": True, "api_error_status": status, "result": "limit reached",
    }))
    with pytest.raises(AIRetryableError):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


@pytest.mark.parametrize("status", [401, 404])
def test_status_de_configuracion_son_fatales(fake_run, status):
    fake_run(returncode=1, stdout=json.dumps({
        "is_error": True, "api_error_status": status, "result": "issue with the selected model",
    }))
    with pytest.raises(AIFatalError):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


def test_sesion_no_iniciada_es_fatal(fake_run):
    fake_run(returncode=1, stdout="", stderr="Not logged in · Please run /login")
    with pytest.raises(AIFatalError):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


def test_timeout_es_reintentable(fake_run):
    fake_run(exc=subprocess.TimeoutExpired(cmd="claude", timeout=600))
    with pytest.raises(AIRetryableError, match="no respondió"):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


def test_salida_no_json_es_reintentable(fake_run):
    fake_run(returncode=0, stdout="esto no es json")
    with pytest.raises(AIRetryableError):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


def test_respuesta_vacia_es_reintentable(fake_run):
    fake_run(stdout=_salida_ok("   "))
    with pytest.raises(AIRetryableError, match="vacía"):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


def test_cli_no_instalado_es_fatal(monkeypatch):
    monkeypatch.setattr(cli_module.shutil, "which", lambda _: None)
    monkeypatch.delenv("AI_CLI_PATH", raising=False)
    with pytest.raises(AIFatalError, match="claude"):
        ClaudeCliClient().messages.create(messages=[{"role": "user", "content": "x"}])


# ─────────────────────────────────────────
#  Trazabilidad (PIPELINE_TRACE_DIR) — vale para cualquier proveedor
# ─────────────────────────────────────────

def test_trace_dir_guarda_request_y_response(fake_run, monkeypatch, tmp_path):
    fake_run(stdout=_salida_ok('{"picos": []}'))
    monkeypatch.setenv("AI_PROVIDER", "claude_cli")
    monkeypatch.setenv("PIPELINE_TRACE_DIR", str(tmp_path / "trazas"))

    client = get_client()
    client.messages.create(system="s", messages=[{"role": "user", "content": "uno"}])
    client.messages.create(system="s", messages=[{"role": "user", "content": "dos"}])

    trazas = tmp_path / "trazas"
    req1 = json.loads((trazas / "001_request.json").read_text(encoding="utf-8"))
    res2 = json.loads((trazas / "002_response.json").read_text(encoding="utf-8"))
    assert req1["messages"][0]["content"] == "uno"
    assert res2["text"] == '{"picos": []}'
    assert res2["meta"]["proveedor"] == "claude_cli"


def test_trace_dir_guarda_error_y_relanza(fake_run, monkeypatch, tmp_path):
    fake_run(exc=subprocess.TimeoutExpired(cmd="claude", timeout=600))
    monkeypatch.setenv("AI_PROVIDER", "claude_cli")
    monkeypatch.setenv("PIPELINE_TRACE_DIR", str(tmp_path))

    with pytest.raises(AIRetryableError):
        get_client().messages.create(messages=[{"role": "user", "content": "x"}])

    error = json.loads((tmp_path / "001_error.json").read_text(encoding="utf-8"))
    assert error["tipo"] == "AIRetryableError"
