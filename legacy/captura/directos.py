"""
directos.py — CLIP-88/89 (épica L1, CLIP-86): cuentas de directo por cliente y estado de sus capturas.

- Configuración: `investigacion/<nicho>/directos.yaml`
      cuentas:
        - {plataforma: tiktok, usuario: fritzsport, activo: true, trozo_min: 30, procesar: true}
- Capturas: cada directo grabado es una carpeta `<stream_data>/directo_<nicho>_<usuario>_<AAAAMMDD_HHMMSS>/` con
  `captura_estado.json` (lo escribe captura/grabador.py) y sus trozos `trozo_001.mp4`, `trozo_002.mp4`...
- Último chequeo de cada cuenta: `<stream_data>/_directos_estado.json` (lo escribe el vigilante).

Sin red ni procesos: lo puro y el disco. La red está en tipos_directo; los procesos, en el grabador y el vigilante.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from captura import tipos_directo
from investigacion import comun

ARCHIVO_CONFIG = "directos.yaml"
ARCHIVO_ESTADO = "captura_estado.json"
ARCHIVO_CHEQUEOS = "_directos_estado.json"
PREFIJO = "directo_"
TROZO_MIN_DEFECTO = 30
TROZO_MIN_LIMITES = (1, 120)


# ── Configuración por cliente ──────────────────────────────

def _ruta_config(nicho: str) -> Path:
    return comun.carpeta_nicho(nicho) / ARCHIVO_CONFIG


def leer(nicho: str) -> dict:
    ruta = _ruta_config(nicho)
    if not ruta.exists():
        return {"cuentas": []}
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    datos.setdefault("cuentas", [])
    return datos


def _guardar(nicho: str, datos: dict) -> None:
    ruta = _ruta_config(nicho)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cabecera = ("# Cuentas de directo del cliente (CLIP-88). Se editan desde el panel → Directos.\n"
                "# trozo_min: duración de cada trozo grabado · procesar: cada trozo entra solo al pipeline.\n")
    ruta.write_text(cabecera + yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")


def clientes() -> list[str]:
    """Nichos que pueden tener directos: los que tienen fuentes (son clientes) o ya tienen directos.yaml."""
    base = comun.carpeta_nicho("x").parent
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and ((p / "fuentes.yaml").exists() or (p / ARCHIVO_CONFIG).exists()))


def cuentas_activas() -> list[tuple[str, dict]]:
    return [(nicho, c) for nicho in clientes() for c in leer(nicho)["cuentas"] if c.get("activo", True)]


def _buscar(datos: dict, plataforma: str, usuario: str) -> dict | None:
    return next((c for c in datos["cuentas"] if c.get("plataforma") == plataforma and c.get("usuario") == usuario), None)


def agregar(nicho: str, plataforma: str, usuario: str, trozo_min: int = TROZO_MIN_DEFECTO,
            procesar: bool = True) -> dict:
    tipo = tipos_directo.obtener(plataforma)
    usuario = tipo.normalizar_usuario(usuario)
    datos = leer(nicho)
    if _buscar(datos, plataforma, usuario):
        raise tipos_directo.DirectoError(f"@{usuario} ya está en los directos de este cliente")
    cuenta = {"plataforma": plataforma, "usuario": usuario, "activo": True,
              "trozo_min": _trozo_valido(trozo_min), "procesar": bool(procesar)}
    datos["cuentas"].append(cuenta)
    _guardar(nicho, datos)
    return cuenta


def actualizar(nicho: str, plataforma: str, usuario: str, **cambios) -> dict:
    datos = leer(nicho)
    cuenta = _buscar(datos, plataforma, usuario)
    if not cuenta:
        raise tipos_directo.DirectoError(f"@{usuario} no está en los directos de este cliente")
    for clave in ("activo", "procesar"):
        if cambios.get(clave) is not None:
            cuenta[clave] = bool(cambios[clave])
    if cambios.get("trozo_min") is not None:
        cuenta["trozo_min"] = _trozo_valido(cambios["trozo_min"])
    _guardar(nicho, datos)
    return cuenta


def quitar(nicho: str, plataforma: str, usuario: str) -> None:
    datos = leer(nicho)
    antes = len(datos["cuentas"])
    datos["cuentas"] = [c for c in datos["cuentas"]
                        if not (c.get("plataforma") == plataforma and c.get("usuario") == usuario)]
    if len(datos["cuentas"]) == antes:
        raise tipos_directo.DirectoError(f"@{usuario} no está en los directos de este cliente")
    _guardar(nicho, datos)


def _trozo_valido(valor) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        raise tipos_directo.DirectoError("La duración del trozo debe ser un número de minutos")
    bajo, alto = TROZO_MIN_LIMITES
    if not bajo <= n <= alto:
        raise tipos_directo.DirectoError(f"La duración del trozo va de {bajo} a {alto} minutos")
    return n


# ── Capturas ────────────────────────────────────────────────

def nombre_captura(nicho: str, usuario: str, momento: datetime | None = None) -> str:
    seguro = re.sub(r"[^\w.-]", "_", usuario)
    return f"{PREFIJO}{nicho}_{seguro}_{(momento or datetime.now()):%Y%m%d_%H%M%S}"


def escribir_json(ruta: Path, datos: dict) -> None:
    """Escritura atómica: el vigilante lee mientras el grabador escribe."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=".tmp_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


def leer_json(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def capturas(stream_data: Path, nicho: str | None = None) -> list[dict]:
    """Estados de las capturas (más nueva primero), con `carpeta` agregada."""
    if not stream_data.is_dir():
        return []
    salida = []
    for carpeta in stream_data.iterdir():
        if not carpeta.is_dir() or not carpeta.name.startswith(PREFIJO):
            continue
        estado = leer_json(carpeta / ARCHIVO_ESTADO)
        if not estado or (nicho and estado.get("nicho") != nicho):
            continue
        salida.append({**estado, "carpeta": carpeta.name})
    return sorted(salida, key=lambda e: e.get("inicio") or "", reverse=True)


def captura_activa(stream_data: Path, nicho: str, plataforma: str, usuario: str, vivo) -> dict | None:
    """La captura en curso de esa cuenta, si su grabador sigue vivo (`vivo(pid, inicio) -> bool`)."""
    for e in capturas(stream_data, nicho):
        if (e.get("plataforma"), e.get("usuario")) == (plataforma, usuario) and e.get("estado") == "grabando":
            if vivo(e.get("pid"), e.get("inicio")):
                return e
    return None


# ── Último chequeo por cuenta ───────────────────────────────

def clave_cuenta(nicho: str, plataforma: str, usuario: str) -> str:
    return f"{nicho}/{plataforma}/{usuario}"


def chequeos(stream_data: Path) -> dict:
    return leer_json(stream_data / ARCHIVO_CHEQUEOS) or {}


def anotar_chequeo(stream_data: Path, nicho: str, plataforma: str, usuario: str, resultado: bool | None,
                   detalle: str = "") -> None:
    datos = chequeos(stream_data)
    datos[clave_cuenta(nicho, plataforma, usuario)] = {
        "ts": datetime.now().isoformat(timespec="seconds"), "en_vivo": resultado, "detalle": detalle}
    escribir_json(stream_data / ARCHIVO_CHEQUEOS, datos)
