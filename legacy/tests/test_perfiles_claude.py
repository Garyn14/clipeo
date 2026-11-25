"""
test_perfiles_claude.py — CLIP-83: perfiles de cuenta de Claude (carpetas CLAUDE_CONFIG_DIR) y su uso en el
proveedor claude_cli y en Configuración. No ejecuta Claude Code: subprocess.run se reemplaza.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import ai_client.cli_provider as cli_module
from ai_client import AIFatalError, perfiles
from ai_client.cli_provider import ClaudeCliClient


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Carpeta de perfiles y .env temporales (nunca los reales del operador)."""
    env = tmp_path / ".env"
    env.write_text("AI_PROVIDER=claude_cli\n", encoding="utf-8")
    monkeypatch.setenv("AI_CLI_PERFILES_DIR", str(tmp_path / "perfiles"))
    monkeypatch.setattr(perfiles, "ruta_env", lambda: env)
    monkeypatch.delenv("AI_CLI_PATH", raising=False)
    monkeypatch.setattr(perfiles.shutil, "which", lambda _: "claude")
    return tmp_path, env


def _activar(env: Path, nombre: str):
    env.write_text(f"AI_PROVIDER=claude_cli\nAI_CLI_PERFIL={nombre}\n", encoding="utf-8")


# ── módulo perfiles ──

def test_crear_y_listar(entorno):
    tmp, _ = entorno
    assert perfiles.listar() == []
    assert perfiles.crear(" Cuenta2 ") == "cuenta2"
    perfiles.crear("principal")
    assert perfiles.listar() == ["cuenta2", "principal"]
    assert (tmp / "perfiles" / "cuenta2").is_dir()


@pytest.mark.parametrize("malo", ["", "../fuera", "con espacio", "a/b", "x" * 41])
def test_nombre_invalido(entorno, malo):
    with pytest.raises(ValueError):
        perfiles.crear(malo)


def test_sin_perfil_activo_usa_sesion_por_defecto(entorno):
    assert perfiles.perfil_activo() == ""
    assert perfiles.config_dir_activo() is None


def test_perfil_activo_se_relee_del_env(entorno):
    tmp, env = entorno
    perfiles.crear("cuenta2")
    _activar(env, "cuenta2")
    assert perfiles.config_dir_activo() == tmp / "perfiles" / "cuenta2"
    _activar(env, "")
    assert perfiles.config_dir_activo() is None


def test_perfil_activo_inexistente_falla(entorno):
    _, env = entorno
    _activar(env, "borrado")
    with pytest.raises(FileNotFoundError):
        perfiles.config_dir_activo()


def test_comando_login_apunta_a_la_carpeta(entorno):
    tmp, _ = entorno
    cmd = perfiles.comando_login("cuenta2")
    assert str(tmp / "perfiles" / "cuenta2") in cmd and cmd.endswith("claude auth login")


def test_estado_lee_auth_status_sin_tokens(entorno, monkeypatch):
    tmp, _ = entorno
    llamadas = []

    def fake(cmd, **kw):
        llamadas.append(kw["env"])
        salida = {"loggedIn": True, "authMethod": "claude.ai", "email": "op@ejemplo.com", "subscriptionType": "pro",
                  "orgId": "x"}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(salida), "")

    monkeypatch.setattr(perfiles.subprocess, "run", fake)
    e = perfiles.estado("cuenta2")
    assert e == {"sesion": True, "cuenta": "op@ejemplo.com", "plan": "pro", "metodo": "claude.ai"}
    assert llamadas[0]["CLAUDE_CONFIG_DIR"] == str(tmp / "perfiles" / "cuenta2")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "otra")
    perfiles.estado(None)
    assert "CLAUDE_CONFIG_DIR" not in llamadas[1]


def test_estado_sin_sesion_o_con_error(entorno, monkeypatch):
    monkeypatch.setattr(perfiles.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, '{"loggedIn": false}', ""))
    assert perfiles.estado("cuenta2")["sesion"] is False

    def explota(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 20)
    monkeypatch.setattr(perfiles.subprocess, "run", explota)
    e = perfiles.estado("cuenta2")
    assert e["sesion"] is False and "error" in e


# ── proveedor claude_cli ──

def _salida_ok():
    return json.dumps({"is_error": False, "result": "ok", "usage": {}})


def _llamar(monkeypatch):
    envs = []

    def fake(cmd, **kw):
        envs.append(kw["env"])
        return subprocess.CompletedProcess(cmd, 0, _salida_ok(), "")
    monkeypatch.setattr(cli_module.subprocess, "run", fake)
    monkeypatch.setattr(cli_module.shutil, "which", lambda _: "claude")
    ClaudeCliClient().messages.create(model="x", max_tokens=10, messages=[{"role": "user", "content": "hola"}])
    return envs[0]


def test_proveedor_usa_el_perfil_activo(entorno, monkeypatch):
    tmp, env = entorno
    perfiles.crear("cuenta2")
    _activar(env, "cuenta2")
    assert _llamar(monkeypatch)["CLAUDE_CONFIG_DIR"] == str(tmp / "perfiles" / "cuenta2")


def test_proveedor_sin_perfil_no_toca_config_dir(entorno, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert "CLAUDE_CONFIG_DIR" not in _llamar(monkeypatch)


def test_proveedor_perfil_inexistente_es_fatal(entorno, monkeypatch):
    _, env = entorno
    _activar(env, "borrado")
    with pytest.raises(AIFatalError):
        _llamar(monkeypatch)


# ── backend: Configuración ──

@pytest.fixture
def cliente(entorno, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import env_manager

    _, env = entorno
    monkeypatch.setattr(env_manager, "ENV_PATH", env)
    monkeypatch.setattr(perfiles, "estado", lambda nombre, timeout=20: {"sesion": nombre != "nueva", "cuenta": "",
                                                                       "plan": "pro", "metodo": "claude.ai"})
    return TestClient(app), env


def test_campos_env_traen_seccion_y_avanzado(cliente):
    c, _ = cliente
    campos = {f["key"]: f for f in c.get("/config/env").json()}
    assert campos["COLAB_TRANSCRIBE_URL"]["seccion"] == "transcripcion"
    assert campos["ANTHROPIC_API_KEY"]["avanzado"] is True
    assert campos["TIKTOK_CLIENT_KEY"]["avanzado"] is False
    assert "AI_CLI_PERFIL" not in campos


def test_crear_activar_y_volver_al_defecto(cliente):
    c, env = cliente
    r = c.get("/config/claude").json()
    assert r["activo"] == "" and [p["nombre"] for p in r["perfiles"]] == [""]

    assert c.post("/config/claude/perfiles", json={"nombre": "cuenta2"}).status_code == 200
    r = c.put("/config/claude/activo", json={"nombre": "cuenta2"}).json()
    assert r["activo"] == "cuenta2" and r["activo_existe"]
    assert "AI_CLI_PERFIL=cuenta2" in env.read_text(encoding="utf-8")
    assert "AI_PROVIDER=claude_cli" in env.read_text(encoding="utf-8")

    r = c.put("/config/claude/activo", json={"nombre": ""}).json()
    assert r["activo"] == ""


def test_activar_inexistente_o_invalido(cliente):
    c, _ = cliente
    assert c.put("/config/claude/activo", json={"nombre": "nadie"}).status_code == 404
    assert c.post("/config/claude/perfiles", json={"nombre": "../x"}).status_code == 400
