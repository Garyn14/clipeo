"""
medios_poc.py — CLIP-34: prueba de concepto de "medios como fuente" (TV/prensa sobre el personaje).

Pasa un video de YouTube por el detector (A1 → A2), la dirección editorial y el juez del piloto, usando los
**subtítulos automáticos** de YouTube como transcripción (sin descargar el video, sin Colab). No corta ni publica
nada (contenido de terceros, R-01): solo informa qué momentos encontraría el sistema.

    python -m evaluacion.medios_poc <id_o_url_youtube> [--nicho zapatillas_peru] [--vtt archivo.vtt]

Desde servidores en la nube YouTube suele pedir "confirmar que no eres un bot": correrlo en la laptop, o pasar un
.vtt ya descargado con --vtt. Escribe evaluacion/resultados/medios_<id>.json.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from evaluacion import _legacy  # noqa: F401 — agrega legacy/ al path

DIR_RESULTADOS = Path(__file__).resolve().parent / "resultados"
_TS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.\d{3} --> ")


def vtt_a_transcripcion(vtt: str, bloque_s: int = 5) -> str:
    """VTT de subtítulos automáticos (líneas que se repiten al avanzar) → líneas '[MM:SS] texto' cada ~5 s."""
    lineas, vistas = [], set()
    t_actual = 0
    for linea in vtt.splitlines():
        m = _TS.match(linea)
        if m:
            h, mi, s = map(int, m.groups())
            t_actual = h * 3600 + mi * 60 + s
            continue
        texto = re.sub(r"<[^>]+>", "", linea).strip()
        if not texto or texto in vistas or "-->" in texto or texto.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        vistas.add(texto)
        lineas.append((t_actual, texto))
    salida, buffer, inicio = [], [], None
    for t, texto in lineas:
        if inicio is None:
            inicio = t
        buffer.append(texto)
        if t - inicio >= bloque_s:
            salida.append(f"[{inicio // 60:02d}:{inicio % 60:02d}] {' '.join(buffer)}")
            buffer, inicio = [], None
    if buffer:
        salida.append(f"[{inicio // 60:02d}:{inicio % 60:02d}] {' '.join(buffer)}")
    return "\n".join(salida)


def bajar_subtitulos(video: str, carpeta: Path) -> str:
    for cliente in ("default", "android_vr", "tv_embedded"):
        cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--sub-langs", "es.*", "--sub-format", "vtt",
               "-o", str(carpeta / "sub.%(ext)s")]
        if cliente != "default":
            cmd += ["--extractor-args", f"youtube:player_client={cliente}"]
        subprocess.run(cmd + ["--", video], capture_output=True, text=True, timeout=180)
        archivos = sorted(carpeta.glob("sub*.vtt"))
        if archivos:
            return archivos[0].read_text(encoding="utf-8")
    raise RuntimeError("YouTube no entregó subtítulos (¿bloqueo de bots?). Corre esto en la laptop o usa --vtt.")


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-34: momentos que el piloto encontraría en un video de medios")
    ap.add_argument("video", help="id o URL de YouTube")
    ap.add_argument("--nicho", default="zapatillas_peru")
    ap.add_argument("--vtt", type=Path, help="subtítulos ya descargados (.vtt)")
    args = ap.parse_args()

    from agentes import juez
    from agentes.direccion import run_direccion
    from evaluacion.cobertura import cargar_config, detectar

    vid = re.sub(r".*(?:v=|youtu\.be/|shorts/)", "", args.video).split("&")[0]
    with tempfile.TemporaryDirectory() as tmp:
        vtt = args.vtt.read_text(encoding="utf-8") if args.vtt else bajar_subtitulos(args.video, Path(tmp))
        transcripcion = vtt_a_transcripcion(vtt)
        config = cargar_config(args.nicho)
        print(f"[MEDIOS] {vid}: {len(transcripcion.splitlines())} líneas de transcripción")
        rangos = detectar(transcripcion, config)
        print(f"[MEDIOS] detector: {len(rangos)} candidato(s)")
        rangos = run_direccion(rangos, transcripcion=transcripcion, config=config) if rangos else []
        decisiones = []
        if rangos:
            juez.run_juez(rangos, transcripcion=transcripcion, config=config, session_dir=Path(tmp), chunk_dir=Path(tmp))
            decisiones = json.loads((Path(tmp) / "juez.json").read_text(encoding="utf-8"))["decisiones"]

    DIR_RESULTADOS.mkdir(exist_ok=True)
    salida = DIR_RESULTADOS / f"medios_{vid}.json"
    salida.write_text(json.dumps({"video": vid, "fecha": datetime.now().isoformat(timespec="seconds"),
                                  "nicho": args.nicho, "lineas_transcripcion": len(transcripcion.splitlines()),
                                  # sin la transcripción: contenido de terceros (R-01), el repo puede ser público
                                  "decisiones": decisiones},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    for d in decisiones:
        marca = "⭐" if d.get("prioridad") and d["publicar"] else ("✅" if d["publicar"] else "❌")
        print(f"  {marca} {d['inicio']}→{d['fin']} {d.get('fuerza')}/10 [{d.get('tipo')}] {d.get('linea1')} {d.get('linea2')}")
    print(f"[MEDIOS] → {salida}")


if __name__ == "__main__":
    sys.exit(main())
