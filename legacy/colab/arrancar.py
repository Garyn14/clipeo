"""
arrancar.py — Levanta el servidor de transcripción en Colab en un solo paso, con barra de progreso (CLIP-65).

Uso en la celda única del notebook (ver README):
    RAMA = "main"
    !wget -q -O /content/arrancar.py https://raw.githubusercontent.com/Garyn14/clipeo/{RAMA}/legacy/colab/arrancar.py
    %run /content/arrancar.py {RAMA}

Qué hace, con una barra por etapas (tiempo transcurrido y estimación de lo que falta):
  1. Revisa la GPU y anota la versión de torch que trae Colab.
  2. Instala whisperx con `uv`, CONGELANDO torch/torchaudio/torchvision en la versión de Colab (no reinstala 2–3 GB
     de PyTorch ni deja que pip pruebe versiones). Si no es compatible, reintenta sin congelar y lo avisa.
  3. Descarga cloudflared.
  4. Lanza `servidor.py` en un proceso NUEVO (toma las librerías recién instaladas: no hace falta reiniciar la sesión).
  5. Abre el túnel e imprime `URL_TUNEL=https://….trycloudflare.com`.
Si una etapa falla, lo dice y muestra las últimas líneas del log. Volver a ejecutar reemplaza el servidor anterior.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = "Garyn14/clipeo"
BASE = "/content"
WHISPERX = "whisperx"               # se fija tras la primera medición en Colab (ver README)
EXTRAS = ["numpy==2.2.6", "flask"]   # numpy compatible con whisperx, pyannote y numba

# (clave, texto, segundos típicos): el porcentaje avanza por etapas según estos tiempos
ETAPAS = [
    ("gpu", "Revisando la GPU", 5),
    ("instalar", "Instalando whisperx y dependencias", 150),
    ("tunel_bin", "Descargando cloudflared", 10),
    ("modelos", "Cargando los modelos en la GPU", 120),
    ("tunel", "Abriendo el túnel", 20),
]
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def buscar_url(texto: str) -> str | None:
    m = URL_RE.search(texto)
    return m.group(0) if m else None


def mmss(segundos: float) -> str:
    s = max(0, int(segundos))
    return f"{s // 60}:{s % 60:02d}"


def progreso(indice: int, en_etapa: float) -> tuple[float, float]:
    """(porcentaje 0–100, segundos estimados que faltan) estando `en_etapa` s dentro de la etapa `indice`."""
    total = sum(e[2] for e in ETAPAS)
    hecho = sum(e[2] for e in ETAPAS[:indice])
    esperado = ETAPAS[indice][2]
    actual = min(en_etapa, esperado * 0.95)          # nunca marca la etapa como terminada antes de tiempo
    resto = max(esperado - en_etapa, 0) + sum(e[2] for e in ETAPAS[indice + 1:])
    return 100 * (hecho + actual) / total, resto


def texto_barra(indice: int, en_etapa: float, transcurrido: float) -> str:
    pct, resto = progreso(indice, en_etapa)
    llenos = int(pct // 5)
    faltan = "casi listo" if resto < 15 else f"faltan ~{max(1, round(resto / 60))} min"
    return (f"{'█' * llenos}{'░' * (20 - llenos)} {pct:3.0f}%  ·  Paso {indice + 1} de {len(ETAPAS)}: "
            f"{ETAPAS[indice][1]}  ·  {mmss(transcurrido)} transcurridos  ·  {faltan}")


class Barra:
    """Una sola línea que se actualiza en la salida de la celda (texto plano fuera de Colab)."""

    def __init__(self):
        self.inicio = time.time()
        try:
            from IPython.display import HTML, display
            self._html, self._handle = HTML, display(HTML(""), display_id=True)
        except Exception:  # noqa: BLE001
            self._handle = None

    def mostrar(self, texto: str, color: str = "#7c8cff"):
        if self._handle is None:
            print(texto, flush=True)
            return
        self._handle.update(self._html(
            f'<div style="font-family:monospace;font-size:14px;color:{color};padding:4px 0">{html.escape(texto)}</div>'))


def _cola(ruta: str, n: int = 30) -> str:
    try:
        with open(ruta, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return "(sin log)"


def _fallar(barra: Barra, indice: int, motivo: str, log: str | None = None):
    barra.mostrar(f"✖ Falló el paso {indice + 1} ({ETAPAS[indice][1]}): {motivo}", "#f87171")
    if log:
        print(f"Últimas líneas de {log}:\n{_cola(log)}")
    raise SystemExit(1)


def _esperar(barra: Barra, indice: int, listo, timeout: float, proc=None, log=None):
    """Actualiza la barra cada segundo hasta que `listo()` sea verdadero (o falle el proceso / se agote el tiempo)."""
    t0 = time.time()
    while True:
        resultado = listo()
        if resultado:
            return resultado
        if proc is not None and proc.poll() is not None and not listo():
            _fallar(barra, indice, f"el proceso terminó con código {proc.returncode}", log)
        if time.time() - t0 > timeout:
            _fallar(barra, indice, f"no terminó en {mmss(timeout)}", log)
        barra.mostrar(texto_barra(indice, time.time() - t0, time.time() - barra.inicio))
        time.sleep(1)


def _secret(*nombres):
    from google.colab import userdata   # solo existe dentro de Colab
    for nombre in nombres:
        try:
            valor = userdata.get(nombre)
        except Exception:  # noqa: BLE001  SecretNotFoundError / sin "Acceso del notebook"
            continue
        if valor:
            return valor
    return None


def _version(paquete: str) -> str:
    """Versión instalada leyendo los metadatos en un proceso nuevo (no importa el paquete ni usa la caché vieja)."""
    r = subprocess.run([sys.executable, "-c", f"import importlib.metadata as m; print(m.version('{paquete}'))"],
                       capture_output=True, text=True)
    return r.stdout.strip() or "?"


def main(rama: str = "main"):
    barra = Barra()
    subprocess.run("pkill -f servidor.py; pkill -f cloudflared", shell=True)   # re-ejecución: reemplaza lo anterior

    # 1. GPU y versiones de partida
    barra.mostrar(texto_barra(0, 0, 0))
    hf, auth = _secret("HF_TOKEN"), _secret("AUTH_TOKEN", "COLAB_AUTH_TOKEN")
    if not auth:
        _fallar(barra, 0, "falta el Secret AUTH_TOKEN o COLAB_AUTH_TOKEN (🔑, con 'Acceso del notebook')")
    if not hf:
        print("⚠ Falta el Secret HF_TOKEN: no habrá diarización (pyannote).")
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True)
    if gpu.returncode != 0:
        _fallar(barra, 0, "no hay GPU: Entorno de ejecución → Cambiar tipo → GPU T4")
    torch_antes = {p: _version(p) for p in ("torch", "torchaudio", "torchvision")}

    # 2. Dependencias con uv, congelando el torch de Colab
    log_inst = f"{BASE}/instalacion.log"
    with open(f"{BASE}/restricciones.txt", "w") as f:
        f.writelines(f"{p}=={v}\n" for p, v in torch_antes.items() if v != "?")
    uv = shutil.which("uv") or ""
    if not uv:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], check=False)
        uv = shutil.which("uv") or "uv"
    base_cmd = [uv, "pip", "install", "--system", WHISPERX, *EXTRAS]

    def instalar(cmd):
        with open(log_inst, "a") as salida:
            p = subprocess.Popen(cmd, stdout=salida, stderr=subprocess.STDOUT)
        _esperar(barra, 1, lambda: p.poll() is not None, timeout=1500)
        return p.returncode

    if instalar([*base_cmd, "-c", f"{BASE}/restricciones.txt"]) != 0:
        print("⚠ whisperx no es compatible con el torch de Colab: se instala sin congelarlo (tarda más).")
        if instalar(base_cmd) != 0:
            _fallar(barra, 1, "no se pudieron instalar las dependencias", log_inst)

    # 3. cloudflared y servidor.py
    barra.mostrar(texto_barra(2, 0, time.time() - barra.inicio))
    urllib.request.urlretrieve(
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
        f"{BASE}/cloudflared")
    os.chmod(f"{BASE}/cloudflared", 0o755)
    urllib.request.urlretrieve(f"https://raw.githubusercontent.com/{REPO}/{rama}/legacy/colab/servidor.py",
                               f"{BASE}/servidor.py")

    # 4. Servidor en un proceso nuevo (sin reiniciar la sesión)
    log_srv = f"{BASE}/servidor.log"
    entorno = {**os.environ, "AUTH_TOKEN": auth, "HF_TOKEN": hf or ""}
    with open(log_srv, "w") as salida:
        srv = subprocess.Popen([sys.executable, "-u", f"{BASE}/servidor.py"], stdout=salida,
                               stderr=subprocess.STDOUT, env=entorno, cwd=BASE)
    _esperar(barra, 3, lambda: "SERVIDOR_LISTO" in _cola(log_srv, 200), timeout=900, proc=srv, log=log_srv)

    # 5. Túnel
    log_tun = f"{BASE}/tunel.log"
    with open(log_tun, "w") as salida:
        tun = subprocess.Popen([f"{BASE}/cloudflared", "tunnel", "--url", "http://localhost:5000"],
                               stdout=salida, stderr=subprocess.STDOUT)
    url = _esperar(barra, 4, lambda: buscar_url(_cola(log_tun, 200)), timeout=120, proc=tun, log=log_tun)

    total = time.time() - barra.inicio
    barra.mostrar(f"{'█' * 20} 100%  ·  Listo en {mmss(total)}", "#34d399")
    print(f"torch: {torch_antes.get('torch')} → {_version('torch')}  ·  whisperx: {_version('whisperx')}")
    print("Copiar esta línea al .env como COLAB_TRANSCRIBE_URL (Claude lo hace solo):")
    print(f"URL_TUNEL={url}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "main")
