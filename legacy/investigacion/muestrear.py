"""
muestrear.py — Elige los clips a analizar a fondo y descarga su material: por universo, los
de mayor y menor outlier de las cuentas de clips, más los éxitos de la cuenta propia.

Uso:
    python investigacion/muestrear.py zapatillas_peru [--top 12] [--fondo 5] [--propia 8]

Por clip deja en investigacion/<nicho>/muestra/<id>/: video.mp4 (baja calidad),
fotogramas.jpg (4 cuadros para leer el texto en pantalla) y audio.mp3 (para transcribir con
transcribir_muestra.py). La lista va a muestra.jsonl. La carpeta muestra/ está en .gitignore.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from investigacion.comun import RAIZ, calcular_outliers, carpeta_nicho, leer_videos  # noqa: E402


def elegir(maduros: list[dict], top: int, fondo: int, propia: int) -> list[dict]:
    muestra = []
    for u in sorted({f["universo"] for f in maduros if f["tipo_cuenta"] == "clipper"}):
        grupo = sorted((f for f in maduros if f["universo"] == u and f["tipo_cuenta"] == "clipper"),
                       key=lambda f: f["outlier"], reverse=True)
        muestra += [dict(f, grupo="top") for f in grupo[:top]]
        muestra += [dict(f, grupo="fondo") for f in grupo[-fondo:]] if len(grupo) > top else []
    propios = sorted((f for f in maduros if f["tipo_cuenta"] == "propia"), key=lambda f: f["vistas"], reverse=True)
    return muestra + [dict(f, grupo="propia_top") for f in propios[:propia]]


def descargar(f: dict, destino: Path, pausa: int) -> bool:
    destino.mkdir(parents=True, exist_ok=True)
    video = destino / "video.mp4"
    if not video.exists():
        cmd = ["yt-dlp", "-f", "worst[ext=mp4]/worst", "-o", str(video), f["url"]]
        if (RAIZ / "cookies.txt").exists():
            cmd[1:1] = ["--cookies", str(RAIZ / "cookies.txt")]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        time.sleep(pausa)
        if r.returncode != 0 or not video.exists():
            print(f"  ⚠ {f['id']}: {(r.stderr.strip().splitlines() or ['?'])[-1][:120]}", flush=True)
            return False
    dur = max(float(f.get("duracion_s") or 8), 4.0)
    # 4 fotogramas: 0.8 s (gancho), 25%, 55% y 85% del clip, en una tira horizontal
    tiempos = [0.8, dur * 0.25, dur * 0.55, dur * 0.85]
    sel = "+".join(f"lt(prev_pts*TB\\,{t:.2f})*gte(pts*TB\\,{t:.2f})" for t in tiempos)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf",
                    f"select='{sel}',scale=360:-2,tile=4x1", "-frames:v", "1", str(destino / "fotogramas.jpg")])
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn",
                    "-acodec", "libmp3lame", "-q:a", "6", str(destino / "audio.mp3")])
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nicho")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--fondo", type=int, default=5)
    ap.add_argument("--propia", type=int, default=8)
    ap.add_argument("--pausa", type=int, default=12, help="segundos entre descargas")
    args = ap.parse_args()

    carpeta = carpeta_nicho(args.nicho)
    muestra = elegir(calcular_outliers(leer_videos(args.nicho)), args.top, args.fondo, args.propia)
    print(f"muestra: {len(muestra)} clips", flush=True)
    for n, f in enumerate(muestra, 1):
        ok = descargar(f, carpeta / "muestra" / f["id"], args.pausa)
        estado = "" if ok else " (falló la descarga)"
        print(f"[{n}/{len(muestra)}] {f['grupo']:<10} {f['universo']:<6} {f['outlier']:>7.1f}×  @{f['cuenta']}{estado}", flush=True)

    (carpeta / "muestra.jsonl").write_text(
        "\n".join(json.dumps(f, ensure_ascii=False) for f in muestra) + "\n", encoding="utf-8")
    print("✅ listo")


if __name__ == "__main__":
    main()
