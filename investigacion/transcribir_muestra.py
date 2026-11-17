"""
transcribir_muestra.py — Transcribe con Colab el audio de cada clip de la muestra del nicho
(investigacion/<nicho>/muestra/<id>/audio.mp3 → transcripcion.txt). Salta los ya transcritos.

Uso:
    python investigacion/transcribir_muestra.py zapatillas_peru

Requiere COLAB_TRANSCRIBE_URL en .env y el notebook de Colab corriendo.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from investigacion.comun import carpeta_nicho  # noqa: E402
from transcripcion.video_transcriber import ColabError, _transcribe_via_colab  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nicho")
    args = ap.parse_args()

    base = carpeta_nicho(args.nicho) / "muestra"
    carpetas = sorted(c for c in base.iterdir()
                      if (c / "audio.mp3").exists() and not (c / "transcripcion.txt").exists()) if base.exists() else []
    print(f"por transcribir: {len(carpetas)}", flush=True)
    for n, c in enumerate(carpetas, 1):
        try:
            data = _transcribe_via_colab(c / "audio.mp3", timeout=600, poll_interval=4)
        except ColabError as e:
            print(f"[{n}] ⚠ {c.name}: {str(e).splitlines()[0][:150]}", flush=True)
            continue
        lineas = []
        for seg in data.get("segments", []):
            t = seg.get("start", 0)
            voz = f"{seg['speaker']}: " if seg.get("speaker") else ""
            lineas.append(f"[{int(t // 60):02d}:{int(t % 60):02d}] {voz}{seg.get('text', '').strip()}")
        (c / "transcripcion.txt").write_text("\n".join(lineas), encoding="utf-8")
        print(f"[{n}/{len(carpetas)}] {c.name}: {len(lineas)} líneas", flush=True)
    print("✅ listo")


if __name__ == "__main__":
    main()
