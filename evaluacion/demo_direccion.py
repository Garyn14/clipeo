"""
demo_direccion.py — Demo de CLIP-31: el mismo momento antes y después de la dirección editorial.

Se ejecuta en la laptop del operador (los videos de las sesiones están ahí):

    python -m evaluacion.demo_direccion --origen . --sesion <session_id> --clip <clip_id>

Por cada clip:
  1. busca el clip en `stream_data/<sesion>/contenido_chunks/*.json` (campo `clip_id`) y su chunk;
  2. si el clip ya trae un plan de edición (pipeline con DIRECCION_EDITORIAL=1) lo usa; si no, llama a la
     dirección editorial (Claude Code, `AI_PROVIDER=claude_cli`: sin costo de API) sobre su rango original;
  3. corta con el Agente 4 del piloto, con el mismo título:
       antes.mp4      → el rango original (como se cortó en producción)
       despues.mp4    → el plan dirigido (un tramo, o montaje de varios tramos con `_cut_compilation`)
       lado_a_lado.mp4 → los dos lado a lado (izquierda: antes · derecha: después; audio del "después")
  4. guarda `plan.json` (plan, texto antes/después) en
     `<origen>/demo_direccion/<sesion>_<clip>/`.

`--clip` acepta varios ids separados por coma. Requiere FFmpeg.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from evaluacion import _legacy


def buscar_clip(session_dir: Path, clip_id: str) -> tuple[str, dict]:
    """(chunk_id, entrada de contenido) del clip; ValueError si no está."""
    for f in sorted((session_dir / "contenido_chunks").glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        items = data.get("contenido", data) if isinstance(data, dict) else data
        for item in items or []:
            if isinstance(item, dict) and item.get("clip_id") == clip_id:
                return f.stem, item
    raise ValueError(f"{clip_id} no está en {session_dir / 'contenido_chunks'} (¿sesión anterior a los clip_id por chunk?)")


def transcripcion_del_chunk(session_dir: Path, chunk_id: str) -> str:
    chunk_dir = session_dir / "chunks" / chunk_id
    for nombre in ("transcripcion_enriquecida.txt", "transcripcion_raw.txt", "transcripcion_completa.txt"):
        if (chunk_dir / nombre).exists():
            return (chunk_dir / nombre).read_text(encoding="utf-8")
    raise FileNotFoundError(f"sin transcripción en {chunk_dir}")


def plan_del_clip(item: dict, transcripcion: str, config: dict) -> dict | None:
    """Plan existente del clip o uno nuevo de la dirección editorial (None si el plan no pasa la validación)."""
    from agentes import direccion

    rango = dict(item.get("rango_original") or {})
    if rango.get("plan_edicion"):
        return rango["plan_edicion"]
    rango["conservar"] = True
    rango.pop("plan_edicion", None)
    (rango,) = direccion.run_direccion([rango], transcripcion=transcripcion, config=config)
    return rango.get("plan_edicion")


def lado_a_lado(antes: Path, despues: Path, salida: Path) -> bool:
    filtro = ("[0:v]scale=540:960,setsar=1[a];[1:v]scale=540:960,setsar=1[b];"
              "[a][b]hstack=inputs=2:shortest=0[v]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(antes), "-i", str(despues),
           "-filter_complex", filtro, "-map", "[v]", "-map", "1:a?", "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "aac", str(salida)]
    return subprocess.run(cmd).returncode == 0


def demo(origen: Path, sesion: str, clip_id: str, nicho: str) -> Path:
    from agentes.direccion import texto_del_plan
    from core.utils import _parse_segments
    from edicion_video import agent4_video_cutter as a4
    from evaluacion.cobertura import cargar_config

    session_dir = origen / "stream_data" / sesion
    chunk_id, item = buscar_clip(session_dir, clip_id)
    transcripcion = transcripcion_del_chunk(session_dir, chunk_id)
    rango = item.get("rango_original") or {}
    plan = plan_del_clip(item, transcripcion, cargar_config(nicho))

    salida = origen / "demo_direccion" / f"{sesion}_{clip_id}"
    salida.mkdir(parents=True, exist_ok=True)
    segs = _parse_segments(transcripcion)
    original = [{"inicio": rango.get("inicio"), "fin": rango.get("fin")}]
    (salida / "plan.json").write_text(json.dumps({
        "sesion": sesion, "clip_id": clip_id, "chunk": chunk_id, "rango_original": original[0], "plan": plan,
        "texto_antes": texto_del_plan(segs, original),
        "texto_despues": texto_del_plan(segs, plan["segmentos"]) if plan else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    if not plan:
        print(f"[DEMO] {clip_id}: la dirección no propuso un plan válido (el clip queda igual). Ver plan.json")
        return salida

    video = a4._find_video(session_dir)
    if not video:
        raise FileNotFoundError(f"sin video original en {session_dir}")
    font_rel, _ = a4._prepare_font()
    info = a4._detect_video_info(video)
    comun = dict(session_dir=session_dir, mood=item.get("mood", "neutral"), estilo_texto="fijo",
                 source_width=info["width"], source_height=info["height"],
                 layout=item.get("layout", "pillarbox"), layout_streaming=item.get("layout_streaming"))
    l1, l2 = item.get("texto_linea1", ""), item.get("texto_linea2", "")
    lb, bar = info["has_letterbox"], info["bar_height"]

    print(f"[DEMO] {clip_id} · antes: {original[0]['inicio']} → {original[0]['fin']}")
    a4._cut_clip(video, original[0]["inicio"], original[0]["fin"], l1, l2, salida / "antes.mp4", font_rel, lb, bar,
                 **comun)
    print(f"[DEMO] {clip_id} · después: {plan['estructura']}, {len(plan['segmentos'])} tramo(s) — {plan.get('por_que')}")
    if len(plan["segmentos"]) > 1:
        a4._cut_compilation(video, plan["segmentos"], l1, l2, salida / "despues.mp4", font_rel, lb, bar, **comun)
    else:
        s = plan["segmentos"][0]
        a4._cut_clip(video, s["inicio"], s["fin"], l1, l2, salida / "despues.mp4", font_rel, lb, bar, **comun)
    if (salida / "antes.mp4").exists() and (salida / "despues.mp4").exists():
        lado_a_lado(salida / "antes.mp4", salida / "despues.mp4", salida / "lado_a_lado.mp4")
    print(f"[DEMO] ✅ {salida}")
    return salida


def main() -> None:
    ap = argparse.ArgumentParser(description="Demo CLIP-31: antes y después de la dirección editorial")
    ap.add_argument("--origen", type=Path, default=_legacy.LEGACY, help="carpeta con stream_data/ (default: legacy/)")
    ap.add_argument("--sesion", required=True, help="id de la sesión (carpeta en stream_data/)")
    ap.add_argument("--clip", required=True, help="clip_id (p. ej. clip_c002_01); varios separados por coma")
    ap.add_argument("--nicho", default="zapatillas_peru")
    args = ap.parse_args()

    origen = args.origen.resolve()
    os.chdir(origen)   # el Agente 4 copia la fuente a ./stream_data y la usa con ruta relativa (FFmpeg en Windows)
    fallos = 0
    for clip_id in [c.strip() for c in args.clip.split(",") if c.strip()]:
        try:
            demo(origen, args.sesion, clip_id, args.nicho)
        except (ValueError, FileNotFoundError) as e:
            fallos += 1
            print(f"[DEMO] ❌ {clip_id}: {e}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
