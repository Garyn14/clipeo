"""
perfiles.py — Perfiles de cuenta de Claude para AI_PROVIDER=claude_cli (CLIP-83).

Un perfil es una carpeta de configuración propia de Claude Code (variable CLAUDE_CONFIG_DIR): cada una guarda su
propia sesión, así que con varias carpetas se pueden tener varias cuentas de Claude iniciadas a la vez en la misma
máquina. El operador inicia sesión una vez por perfil en una terminal (`comando_login`); la app nunca ve ni guarda
tokens, solo elige qué carpeta usa el pipeline.

- Las carpetas viven FUERA del repositorio (contienen credenciales): `~/.clipeo/claude_perfiles/<nombre>`,
  o donde diga AI_CLI_PERFILES_DIR.
- El perfil activo es AI_CLI_PERFIL en el .env. Vacío = la sesión por defecto de la máquina (comportamiento previo).
- Se relee del .env en cada llamada (`config_dir_activo`), así que un cambio lo toma la siguiente llamada de una
  corrida en curso, sin cortarla.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

CLAVE_ACTIVO = "AI_CLI_PERFIL"
_NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_LEGACY = Path(__file__).resolve().parents[1]


def ruta_env() -> Path:
    """Mismo criterio que el backend (env_manager): legacy/.env si existe; si no, el .env de la raíz del repo."""
    propio, raiz = _LEGACY / ".env", _LEGACY.parent / ".env"
    return propio if propio.exists() or not raiz.exists() else raiz


def carpeta_perfiles() -> Path:
    propia = os.environ.get("AI_CLI_PERFILES_DIR", "").strip()
    return Path(propia) if propia else Path.home() / ".clipeo" / "claude_perfiles"


def validar_nombre(nombre: str) -> str:
    nombre = (nombre or "").strip().lower()
    if not _NOMBRE_VALIDO.match(nombre):
        raise ValueError("Nombre de perfil inválido: minúsculas, números, '-' o '_' (máx. 40), p. ej. 'cuenta2'.")
    return nombre


def listar() -> list[str]:
    base = carpeta_perfiles()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and _NOMBRE_VALIDO.match(p.name))


def crear(nombre: str) -> str:
    nombre = validar_nombre(nombre)
    (carpeta_perfiles() / nombre).mkdir(parents=True, exist_ok=True)
    return nombre


def perfil_activo() -> str:
    """Perfil activo leído del .env en este momento ('' = sesión por defecto)."""
    env = ruta_env()
    valor = (dotenv_values(str(env)).get(CLAVE_ACTIVO) if env.exists() else None) or ""
    return valor.strip()


def config_dir_activo() -> Path | None:
    """Carpeta que debe usar la próxima llamada a Claude Code, o None para la sesión por defecto.

    Un perfil activo que ya no existe es un error de configuración: mejor fallar claro que gastar otra cuenta.
    """
    nombre = perfil_activo()
    if not nombre:
        return None
    carpeta = carpeta_perfiles() / nombre
    if not carpeta.is_dir():
        raise FileNotFoundError(f"El perfil de Claude '{nombre}' (AI_CLI_PERFIL) no existe en {carpeta}.")
    return carpeta


def comando_login(nombre: str) -> str:
    """Comando de PowerShell que el operador corre una vez para iniciar sesión en ese perfil."""
    carpeta = carpeta_perfiles() / validar_nombre(nombre)
    return f'$env:CLAUDE_CONFIG_DIR="{carpeta}"; claude auth login'


def estado(nombre: str | None, timeout: int = 20) -> dict:
    """Sesión de un perfil (None = la por defecto) según `claude auth status --json`. Nunca devuelve tokens."""
    exe = os.environ.get("AI_CLI_PATH", "").strip() or shutil.which("claude")
    if not exe:
        return {"sesion": False, "error": "No se encontró 'claude' en el PATH."}
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    if nombre:
        env["CLAUDE_CONFIG_DIR"] = str(carpeta_perfiles() / validar_nombre(nombre))
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)
    try:
        proc = subprocess.run([exe, "auth", "status", "--json"], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env)
        data = json.loads(proc.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"sesion": False, "error": f"No se pudo leer la sesión: {e}"}
    return {
        "sesion": bool(data.get("loggedIn")),
        "cuenta": data.get("email") or "",
        "plan": data.get("subscriptionType") or "",
        "metodo": data.get("authMethod") or "",
    }
