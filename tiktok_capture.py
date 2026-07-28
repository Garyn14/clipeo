"""
===========================================
  TIKTOK CAPTURE — IDEA MILLONARIA
===========================================

Graba un TikTok Live en chunks para procesarlo después con el
pipeline normal. Este script NO procesa nada, solo descarga.

Uso:
  python tiktok_capture.py --usuario @fritzsport
  python tiktok_capture.py --usuario @fritzsport --chunk 1m
  python tiktok_capture.py --usuario @fritzsport --chunk 30m
  python tiktok_capture.py --usuario @fritzsport --chunk 0         # sin límite: graba de corrido
  python tiktok_capture.py --usuario @fritzsport --sin-verificar   # ya confirmaste que está en vivo
  python tiktok_capture.py --usuario @fritzsport --chunk 30 --max-chunks 1   # graba un solo chunk y para solo
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import glob
import json
import os
import re
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

STREAM_DATA = Path("stream_data")
COOKIES_PATH = Path("cookies.txt")

_CHUNK_UNITS = {"s": 1, "m": 60, "h": 3600}
_CHUNK_DEFAULT_SEGUNDOS = 1800
_GRACE_SEGUNDOS = 5
_REINTENTOS_MAX = 5
_REINTENTO_ESPERA_SEGUNDOS = 5


def _cookies_args() -> list[str]:
    """
    --cookies cookies.txt si el archivo existe: una sesión real logueada
    evita buena parte del bloqueo SlardarWAF que sufre el tráfico anónimo
    (ver memoria: tiktok-live-detection-blocked).
    """
    return ["--cookies", str(COOKIES_PATH)] if COOKIES_PATH.exists() else []


def parse_chunk(valor: str | None) -> int:
    """
    Convierte el valor de --chunk a segundos.
      "1m"  → 60
      "30m" → 1800
      "2h"  → 7200
      "90"  → 90 (sin letra → segundos)
      "0"   → 0 (sin límite: graba de corrido hasta que termine, falle, o se interrumpa)
      None  → default 1800
    """
    if valor is None:
        return _CHUNK_DEFAULT_SEGUNDOS
    m = re.match(r"^(\d+)(m|h|s)?$", valor.strip())
    if not m:
        return _CHUNK_DEFAULT_SEGUNDOS
    n, unidad = int(m.group(1)), m.group(2) or "s"
    return n * _CHUNK_UNITS[unidad]


def normalizar_usuario(usuario: str) -> str:
    return usuario.lstrip("@").strip()


def verificar_yt_dlp() -> None:
    try:
        subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(
            "[CAPTURE] ❌ yt-dlp no está disponible. Instálalo con: pip install yt-dlp"
        ) from e


_WAF_MARKERS = ("SlardarWAF", "Please wait")


def verificar_live_via_colab(usuario: str) -> bool:
    """
    Consulta si el usuario está en vivo vía el mismo servidor Colab usado para
    transcripción (Flask + túnel Cloudflare), corriendo desde una IP distinta
    a la local. Evita los falsos negativos del WAF de TikTok que bloquea la
    IP local tras uso intensivo (ver memoria: tiktok-live-detection-blocked).

    Nunca cae a la verificación local silenciosamente: si Colab está
    configurado pero no responde, es preferible fallar explícito a reportar
    un falso "no en vivo" que ya nos costó una sesión completa detectar.
    """
    base_url = os.environ.get("COLAB_TRANSCRIBE_URL", "").strip()
    check_url = base_url.rsplit("/transcribe", 1)[0] + "/live/check"
    token = os.environ.get("COLAB_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        response = requests.post(check_url, json={"username": usuario}, headers=headers, timeout=30)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        raise RuntimeError(
            "[CAPTURE] Colab no respondió al chequeo de live — verifica que el notebook y el túnel estén activos"
        ) from e

    if response.status_code != 200:
        raise RuntimeError(
            f"[CAPTURE] Colab respondió con error {response.status_code} al chequear @{usuario}: {response.text}"
        )

    data = response.json()
    if "error" in data:
        raise RuntimeError(f"[CAPTURE] Colab reportó error al chequear @{usuario}: {data['error']}")
    if data.get("blocked"):
        raise RuntimeError(
            f"[CAPTURE] Colab no pudo verificar @{usuario} — la IP de Colab fue bloqueada "
            f"por el WAF de TikTok (rate limit), no es un 'no en vivo' real. Espera un rato "
            f"antes de reintentar."
        )
    return bool(data.get("is_live"))


def _diagnosticar_live(usuario: str) -> bool:
    """
    Corre yt-dlp --simulate --write-pages contra @usuario/live e inspecciona
    las páginas crudas para distinguir "no en vivo" real de un bloqueo del
    WAF o un error técnico (ver memoria: tiktok-live-detection-blocked).

    Lanza RuntimeError si el resultado no es concluyente (bloqueo o error
    técnico) en vez de devolver un falso "no en vivo" — ese falso negativo
    (por ejemplo un HTTP 403 o un error de TLS, que no dejan ningún .dump
    para inspeccionar) fue justo el bug que costó una sesión completa
    detectar. Lógica compartida entre verificar_live_activo() y
    check_live_waf.py para no mantener dos implementaciones por separado.

    La página de perfil (@usuario sin /live) casi siempre sale bloqueada
    por el WAF aunque todo esté bien, así que se ignora al decidir.
    """
    url = f"https://www.tiktok.com/@{usuario}/live"
    perfil_suffix = f"@{usuario}.dump"

    result = subprocess.run(
        ["yt-dlp", "--simulate", "--write-pages", "--no-warnings", *_cookies_args(), url],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )

    dumps = glob.glob(f"{usuario}_*.dump") + glob.glob(f"*uniqueId={usuario}.dump")
    bloqueado = False
    for f in dumps:
        if f.endswith(perfil_suffix) and not f.endswith(f"_live{perfil_suffix}"):
            continue  # ruido conocido: esta siempre sale bloqueada, no decide nada
        try:
            contenido = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if any(marker in contenido for marker in _WAF_MARKERS):
            bloqueado = True
    for f in dumps:
        os.remove(f)

    if result.returncode == 0:
        return True

    stderr = result.stderr or ""
    if bloqueado:
        raise RuntimeError(f"[CAPTURE] @{usuario} bloqueado por el WAF de TikTok — no es un 'no en vivo' real")
    if "not currently live" in stderr:
        return False

    detalle = stderr.strip().splitlines()[-1] if stderr.strip() else "(sin detalle)"
    raise RuntimeError(f"[CAPTURE] error técnico al verificar @{usuario}, no es un resultado confiable: {detalle}")


def verificar_live_activo(url: str) -> bool:
    """
    Consulta si un live de TikTok está activo.

    Si COLAB_TRANSCRIBE_URL está configurada, intenta Colab primero; si falla
    (túnel caído, bloqueado, etc.) cae al chequeo local en vez de abortar —
    con cookies.txt (ver memoria: tiktok-live-detection-blocked) el chequeo
    local dejó de ser la fuente de falsos negativos que era antes, así que
    ya no tiene sentido depender solo de Colab.
    """
    m = re.search(r"@([\w.]+)", url)
    usuario = m.group(1) if m else url

    if os.environ.get("COLAB_TRANSCRIBE_URL", "").strip():
        try:
            return verificar_live_via_colab(usuario)
        except RuntimeError as e:
            print(f"[CAPTURE] ⚠️ Colab falló ({e}), cayendo al chequeo local...")

    return _diagnosticar_live(usuario)


def _guardar_estado(estado_path: Path, estado: dict) -> None:
    estado_path.write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _matar_arbol(pid: int) -> None:
    """
    Mata un proceso y todos sus descendientes.

    yt-dlp delega la descarga real a un proceso ffmpeg hijo. Matar solo el
    proceso yt-dlp deja a ffmpeg huérfano, escribiendo el archivo sin límite
    de tiempo — por eso hay que matar el árbol completo, no solo el padre.
    """
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _detener_ordenado(proc: subprocess.Popen) -> None:
    """
    Pide a yt-dlp que cierre de forma ordenada (señal de interrupción) para que
    termine de escribir/cerrar el archivo de destino correctamente, y solo si
    no responde dentro de _GRACE_SEGUNDOS recurre al kill forzoso del árbol
    completo (yt-dlp + ffmpeg hijo, si lo hay).

    Un taskkill/SIGKILL inmediato no le da a ningún muxer en curso (ffmpeg u
    otro) la chance de finalizar el contenedor de salida, lo que puede dejar
    el archivo sin índice/cabecera final y por tanto ilegible.
    """
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        proc.communicate(timeout=_GRACE_SEGUNDOS)
        return
    except Exception:
        pass
    _matar_arbol(proc.pid)
    proc.communicate()


def _grabar_chunk(url: str, chunk_path: Path, chunk_segundos: int) -> tuple[int, str]:
    """
    Corre yt-dlp para grabar un chunk del live, con timeout externo
    (chunk_segundos == 0 → sin timeout, graba de corrido hasta que el
    proceso termine solo, falle, o se interrumpa).
    Retorna (returncode, stderr). returncode == -1 si se agotó el timeout,
    lo cual es el caso normal: el live sigue activo y cortamos el chunk.

    --no-live-from-start es obligatorio: TikTok Live no tiene DVR, así que
    --live-from-start hace que yt-dlp aborte de inmediato sin escribir nada.

    --format-sort vcodec:h264 prioriza H.264 sobre HEVC/H.265 — HEVC
    requiere una extensión de pago para reproducirse en Windows por defecto.
    """
    cmd = [
        "yt-dlp",
        "--no-live-from-start",
        "--no-part",
        "--format-sort", "vcodec:h264",
        *_cookies_args(),
        "-o", str(chunk_path),
        "--max-downloads", "1",
        url,
    ]
    popen_kwargs = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        **popen_kwargs,
    )
    try:
        _, stderr = proc.communicate(timeout=chunk_segundos or None)
        return proc.returncode, stderr or ""
    except subprocess.TimeoutExpired:
        _detener_ordenado(proc)
        return -1, ""
    except KeyboardInterrupt:
        _detener_ordenado(proc)
        raise


def _registrar_chunk(
    estado: dict, estado_path: Path, chunk_num: int, chunk_name: str,
    inicio_ts: int, fin_ts: int, session_dir: Path,
) -> None:
    estado["chunks"].append({
        "chunk_id": f"chunk_{chunk_num:03d}",
        "archivo": chunk_name,
        "inicio_ts": _fmt_ts(inicio_ts),
        "fin_ts": _fmt_ts(fin_ts),
        "estado": "listo",
    })
    _guardar_estado(estado_path, estado)
    chunk_min = (fin_ts - inicio_ts) / 60
    print(f"[CAPTURE] ✅ {chunk_name} guardado")
    print(f"              ({chunk_min:.0f} min · listo para procesar)")
    print("[CAPTURE] Para procesar:")
    print("          python pipeline.py \\")
    print(f"            --video {session_dir}/{chunk_name} \\")
    print("            --config <nicho>")


def _resolver_corte_temprano(
    url: str, chunk_path: Path, chunk_name: str, chunk_valido: bool,
    returncode: int, stderr: str, reintentos_transitorios: int, total_chunks: int,
) -> tuple[bool, int]:
    """
    yt-dlp terminó antes del timeout: puede ser que el live realmente haya
    terminado, o un corte de red/servidor transitorio. Sin esta verificación,
    cualquier hiccup de red se interpretaba como "el live terminó" y cortaba
    la captura completa aunque siguiera activo.

    Retorna (reintentar, nuevo_contador_reintentos).
    """
    print("[CAPTURE] yt-dlp se detuvo antes de tiempo, verificando el live...")
    try:
        sigue_activo = verificar_live_activo(url)
    except RuntimeError as e:
        print(f"[CAPTURE] ⚠️ No se pudo verificar el estado del live: {e}")
        print(f"[CAPTURE] Chunks guardados: {total_chunks}")
        return False, 0

    if sigue_activo:
        if not chunk_valido and chunk_path.exists():
            chunk_path.unlink(missing_ok=True)
        reintentos_transitorios += 1
        if reintentos_transitorios > _REINTENTOS_MAX:
            print(f"[CAPTURE] ❌ Demasiados cortes seguidos ({_REINTENTOS_MAX}), abandonando")
            print(f"[CAPTURE] Chunks guardados: {total_chunks}")
            return False, reintentos_transitorios
        print(f"[CAPTURE] ⚠️ El live sigue activo — corte transitorio, "
              f"reintentando en {_REINTENTO_ESPERA_SEGUNDOS}s "
              f"({reintentos_transitorios}/{_REINTENTOS_MAX})...")
        time.sleep(_REINTENTO_ESPERA_SEGUNDOS)
        return True, reintentos_transitorios

    if chunk_valido:
        # yt-dlp terminó antes del timeout, con archivo válido, y el live ya no está activo
        print("[CAPTURE] 📴 Live terminado")
    else:
        print(f"[CAPTURE] ❌ yt-dlp falló (exit {returncode}) sin generar {chunk_name}")
        if stderr.strip():
            print(f"[CAPTURE] {stderr.strip().splitlines()[-1]}")
    print(f"[CAPTURE] Chunks guardados: {total_chunks}")
    return False, 0


def capturar(
    usuario: str,
    chunk_segundos: int | None = None,
    sin_verificar: bool = False,
    max_chunks: int | None = None,
) -> Path | None:
    """
    Verifica que el usuario esté en vivo y, si lo está, graba el live en
    chunks hasta que termine, se interrumpa manualmente (Ctrl+C), o se
    alcance max_chunks (si se especifica).

    sin_verificar=True salta la verificación previa (útil cuando un humano
    ya confirmó visualmente que el live está activo) — evita una petición
    extra que puede contribuir al bloqueo del WAF de TikTok
    (ver memoria: tiktok-live-detection-blocked).

    Retorna la carpeta de sesión, o None si el live no estaba activo.
    """
    usuario = normalizar_usuario(usuario)
    url = f"https://www.tiktok.com/@{usuario}/live"
    chunk_segundos = _CHUNK_DEFAULT_SEGUNDOS if chunk_segundos is None else chunk_segundos
    if chunk_segundos == 0:
        chunk_desc = "sin límite (hasta error o corte manual)"
    elif chunk_segundos < 60:
        chunk_desc = f"{chunk_segundos} segundos"
    else:
        chunk_desc = f"{chunk_segundos / 60:.0f} minutos"

    print("════════════════════════════════════")
    print("  TIKTOK CAPTURE — IDEA MILLONARIA")
    print(f"  Usuario : @{usuario}")
    print(f"  URL     : {url}")
    print(f"  Chunk   : {chunk_desc}")

    verificar_yt_dlp()

    if sin_verificar:
        print("[CAPTURE] ⚠️ Verificación salteada (--sin-verificar) — asumiendo que el live está activo")
    else:
        print("[CAPTURE] Verificando live...")
        if not verificar_live_activo(url):
            print(f"[CAPTURE] ❌ El live de @{usuario} no está activo")
            return None
        print("[CAPTURE] ✅ Live activo — iniciando captura")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_name = f"tiktok_{usuario}_{timestamp}"
    session_dir = STREAM_DATA / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Sesión  : {session_dir}/")
    print("════════════════════════════════════")

    estado_path = session_dir / "captura_estado.json"
    estado = {
        "usuario": usuario,
        "url": url,
        "chunk_segundos": chunk_segundos,
        "inicio": datetime.now().isoformat(),
        "chunks": [],
    }
    _guardar_estado(estado_path, estado)

    chunk_num = 0
    reintentos_transitorios = 0
    inicio_stream = time.time()
    try:
        while True:
            chunk_num += 1
            chunk_name = f"chunk_{chunk_num:03d}.mp4"
            chunk_path = session_dir / chunk_name

            print(f"[CAPTURE] Chunk {chunk_num}/? — grabando {chunk_desc}...")
            print("          (Ctrl+C para detener)")

            inicio_ts = int(time.time() - inicio_stream)
            returncode, stderr = _grabar_chunk(url, chunk_path, chunk_segundos)
            fin_ts = int(time.time() - inicio_stream)

            chunk_valido = chunk_path.exists() and chunk_path.stat().st_size > 0

            if chunk_valido:
                _registrar_chunk(
                    estado, estado_path, chunk_num, chunk_name,
                    inicio_ts, fin_ts, session_dir,
                )
                if max_chunks is not None and chunk_num >= max_chunks:
                    print(f"[CAPTURE] Límite de {max_chunks} chunk(s) alcanzado, deteniendo captura")
                    break

            if returncode == -1:
                # timeout normal: se cortó el chunk porque el live sigue activo
                reintentos_transitorios = 0
                continue

            reintentar, reintentos_transitorios = _resolver_corte_temprano(
                url, chunk_path, chunk_name, chunk_valido, returncode, stderr,
                reintentos_transitorios, len(estado["chunks"]),
            )
            if reintentar:
                continue
            break

    except KeyboardInterrupt:
        # _grabar_chunk ya mató el árbol de procesos (yt-dlp + ffmpeg) antes de
        # relanzar la excepción, así que el archivo del chunk actual (si tiene
        # contenido) queda cerrado en disco y se puede registrar como parcial.
        chunk_actual = session_dir / f"chunk_{chunk_num:03d}.mp4"
        if chunk_actual.exists() and chunk_actual.stat().st_size > 0:
            ya_registrado = any(c["archivo"] == chunk_actual.name for c in estado["chunks"])
            if not ya_registrado:
                estado["chunks"].append({
                    "chunk_id": f"chunk_{chunk_num:03d}",
                    "archivo": chunk_actual.name,
                    "inicio_ts": _fmt_ts(inicio_ts),
                    "fin_ts": None,
                    "estado": "parcial",
                })

        estado["fin"] = datetime.now().isoformat()
        _guardar_estado(estado_path, estado)
        print()
        print("[CAPTURE] ⏹ Captura detenida manualmente")
        print(f"[CAPTURE] Chunks guardados: {len(estado['chunks'])}")
        print(f"[CAPTURE] Carpeta: {session_dir}/")
        return session_dir

    estado["fin"] = datetime.now().isoformat()
    _guardar_estado(estado_path, estado)
    print(f"[CAPTURE] Carpeta: {session_dir}/")
    return session_dir


def _fmt_ts(segundos: int) -> str:
    h, resto = divmod(max(segundos, 0), 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(
        description="Graba un TikTok Live en chunks para procesar después con pipeline.py"
    )
    parser.add_argument("--usuario", required=True, help="Handle de TikTok (con o sin @)")
    parser.add_argument("--chunk", default=None, help="Duración de cada chunk: 1m, 30m, 2h (default: 30m)")
    parser.add_argument(
        "--sin-verificar", action="store_true",
        help="Salta la verificación previa de si el live está activo (úsalo si ya lo confirmaste visualmente)",
    )
    parser.add_argument(
        "--max-chunks", type=int, default=None,
        help="Graba como máximo N chunks y para sola (sin esto, graba indefinidamente hasta Ctrl+C)",
    )
    args = parser.parse_args()

    try:
        session_dir = capturar(
            args.usuario, parse_chunk(args.chunk),
            sin_verificar=args.sin_verificar, max_chunks=args.max_chunks,
        )
    except RuntimeError as e:
        print(f"[CAPTURE] ❌ {e}")
        sys.exit(1)
    if session_dir is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
