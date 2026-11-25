"""
levantar.py — CLIP-55: un solo comando para dejar Clipeo operando en la laptop.

    python -m herramientas.levantar            # desde la raíz del repo; Ctrl+C lo apaga todo

Arranca el backend (API + motor de publicación) y el frontend (panel de revisión), y muestra un resumen:
cuentas de publicación, motor y túnel de Colab. Las rutas y la base salen del `.env` (CLIP-54): no hay que escribir
variables a mano. Portable (Windows, macOS, Linux): solo Python.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
LEGACY = RAIZ / "legacy"
API = "http://127.0.0.1:8000"
PANEL = "http://localhost:5173"


def _get(url: str, timeout: float = 5.0, headers: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, OSError):
        return 0, ""


def esperar(url: str, segundos: int = 60) -> bool:
    fin = time.time() + segundos
    while time.time() < fin:
        if _get(url, timeout=2)[0]:
            return True
        time.sleep(1)
    return False


def estado_colab() -> str:
    """'vivo' | 'sin URL' | 'caído' según el túnel configurado (401/404 con o sin clave = el servidor responde)."""
    sys.path.insert(0, str(LEGACY))
    try:
        from transcripcion.video_transcriber import colab_vivo
        ok, motivo = colab_vivo()
        return "vivo" if ok else motivo
    except Exception as e:   # noqa: BLE001
        return f"no se pudo comprobar ({type(e).__name__})"


def resumen_publicacion() -> list[str]:
    codigo, cuerpo = _get(f"{API}/publicaciones/resumen")
    if codigo != 200:
        return ["  publicación: no responde"]
    lineas = []
    for n in json.loads(cuerpo).get("nichos", []):
        c = n.get("cuenta") or {}
        lineas.append(f"  {n['plataforma']:8s} {n['nicho']}: cuenta {c.get('estado', 'sin cuenta')}"
                      + (f" ({c['motivo']})" if c.get("motivo") else "")
                      + f" · próximo horario {n.get('proximo_horario') or '—'}")
    return lineas or ["  publicación: sin cuentas conectadas"]


def dependencias_al_dia(frontend: Path) -> bool:
    """¿node_modules tiene lo que pide package-lock.json? (npm deja su propia copia en node_modules/.package-lock.json)"""
    instalado, pedido = frontend / "node_modules" / ".package-lock.json", frontend / "package-lock.json"
    return instalado.exists() and instalado.stat().st_mtime >= pedido.stat().st_mtime


def main() -> None:
    npm = shutil.which("npm")
    if not npm:
        sys.exit("No encuentro npm (Node.js): el panel lo necesita.")
    frontend = LEGACY / "frontend"
    if not dependencias_al_dia(frontend):
        # CLIP-84: una dependencia nueva del panel (p. ej. la tipografía) se instala sola al levantar
        print("Instalando dependencias nuevas del panel (npm install)...")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=str(frontend), check=False)
    procesos = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
                         cwd=str(LEGACY / "backend")),
        subprocess.Popen([npm, "run", "dev"], cwd=str(LEGACY / "frontend")),
    ]
    try:
        api_ok = esperar(f"{API}/sessions", 90)
        panel_ok = esperar(PANEL, 90)
        print("\n" + "═" * 60)
        print("  CLIPEO")
        print(f"  API + motor de publicación : {'✅ ' + API if api_ok else '❌ no arrancó (mira los mensajes de arriba)'}")
        print(f"  Panel de revisión          : {'✅ ' + PANEL if panel_ok else '❌ no arrancó'}")
        if api_ok:
            print("\n".join(resumen_publicacion()))
        colab = estado_colab()
        print(f"  Colab (transcripción)      : {'✅ túnel vivo' if colab == 'vivo' else '⚠ ' + colab}")
        if colab != "vivo":
            print("     → levantar el notebook (celdas 1–2, reiniciar sesión, celda 3) y pegar la URL en .env")
        print("  Ctrl+C apaga todo.")
        print("═" * 60 + "\n")
        while all(p.poll() is None for p in procesos):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procesos:
            if p.poll() is None:
                p.terminate()
        for p in procesos:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
