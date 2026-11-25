"""
live_check.py — CLIP-88: ¿una cuenta de TikTok está en vivo? Se consulta desde la IP de Colab (endpoint /live/check
de servidor.py), porque desde la PC el WAF de TikTok bloquea la consulta anónima.

Misma lógica que captura/tiktok_capture._diagnosticar_live: distinguir "no en vivo" de "bloqueado" o "error". Un
bloqueo nunca se informa como "no en vivo" (ese falso negativo ya costó una sesión completa).

Respuesta (la espera tiktok_capture.verificar_live_via_colab):
  {"is_live": true|false}   concluyente
  {"blocked": true}         el WAF bloqueó la consulta
  {"error": "..."}          error técnico
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import tempfile

MARCAS_WAF = ("SlardarWAF", "Please wait")
USUARIO_VALIDO = re.compile(r"^[\w.]{2,40}$")


def decidir(returncode: int, stderr: str, paginas: dict[str, str], usuario: str) -> dict:
    """Puro: decide con lo que devolvió yt-dlp --simulate --write-pages. `paginas` = {nombre_archivo: contenido}."""
    perfil = f"@{usuario}.dump"
    bloqueado = any(
        any(m in contenido for m in MARCAS_WAF)
        for nombre, contenido in paginas.items()
        # la página de perfil (sin /live) casi siempre sale bloqueada aunque todo esté bien: no decide
        if not (nombre.endswith(perfil) and not nombre.endswith(f"_live{perfil}"))
    )
    if returncode == 0:
        return {"is_live": True}
    if bloqueado:
        return {"blocked": True}
    if "not currently live" in (stderr or ""):
        return {"is_live": False}
    detalle = (stderr or "").strip().splitlines()[-1] if (stderr or "").strip() else "sin detalle"
    return {"error": f"yt-dlp: {detalle}"}


def consultar(usuario: str, timeout: int = 60) -> dict:
    usuario = (usuario or "").lstrip("@").strip().lower()
    if not USUARIO_VALIDO.match(usuario):
        return {"error": "usuario inválido"}
    with tempfile.TemporaryDirectory() as carpeta:
        try:
            r = subprocess.run(["yt-dlp", "--simulate", "--write-pages", "--no-warnings",
                                f"https://www.tiktok.com/@{usuario}/live"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               cwd=carpeta, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"error": f"yt-dlp no respondió: {e}"}
        paginas = {}
        for ruta in glob.glob(os.path.join(carpeta, "*.dump")):
            try:
                with open(ruta, encoding="utf-8", errors="replace") as f:
                    paginas[os.path.basename(ruta)] = f.read()
            except OSError:
                continue
        return decidir(r.returncode, r.stderr, paginas, usuario)
