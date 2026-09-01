"""
clip_manual.py — Corta un clip manual con texto sin necesitar contenido.json.

Uso:
  python entrenamiento/clip_manual.py --video stream_data/<session_id>/stream_completo.mp4
                        --inicio HH:MM:SS --fin HH:MM:SS
                        --linea1 "texto línea 1"
                        --linea2 "texto línea 2 con emoji"
                        [--config canal_id]
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from edicion_video.agent4_video_cutter import (
    _cut_clip,
    _prepare_font,
    _detect_video_info,
    _timestamp_to_seconds,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Corta un clip manual con texto quemado.")
    p.add_argument("--video",   required=True,        help="Ruta al stream_completo.mp4")
    p.add_argument("--inicio",  required=True,        help="Timestamp inicio HH:MM:SS")
    p.add_argument("--fin",     required=True,        help="Timestamp fin   HH:MM:SS")
    p.add_argument("--linea1",  default=None,         help="Texto línea 1 (máx 7 palabras) — opcional")
    p.add_argument("--linea2",  default=None,         help="Texto línea 2 (máx 6 palabras + emoji) — opcional")
    p.add_argument("--config",  default="default",    help="canal_id del YAML (default: 'default')")
    p.add_argument(
        "--entrenamiento", action="store_true", default=False,
        help="Guarda además la transcripción del rango y su contexto en el .json "
             "(ejemplo para revisión manual posterior). No llama a Claude.",
    )
    p.add_argument(
        "--nota", default=None,
        help="Opcional: nota del editor sobre por qué este clip es bueno (solo con --entrenamiento)",
    )
    p.add_argument(
        "--estilo-texto", dest="estilo_texto", default="fijo",
        choices=["sin_texto", "fijo", "fijo_inicial", "dinamico", "dinamico_con_titulo"],
        help="Modo de texto a quemar (default: 'fijo'). 'dinamico'/"
             "'dinamico_con_titulo' usan palabras.json de session_dir (ver "
             "transcripcion/video_transcriber.py) si existe — caen a 'fijo' "
             "si no hay datos de palabra. 'dinamico_con_titulo' combina el "
             "hook fijo con los subtítulos animados en el mismo render.",
    )
    p.add_argument(
        "--cta", dest="cta_texto", default="",
        help="Llamado a la acción quemado en los últimos ~3s del clip "
             "(ej. 'Sígueme para más'). Vacío por defecto (sin CTA).",
    )
    p.add_argument(
        "--palabras-clave", dest="palabras_clave", default="",
        help="Lista separada por comas de palabras a resaltar en rojo "
             "(solo con --estilo-texto dinamico/dinamico_con_titulo).",
    )
    p.add_argument(
        "--layout", default="pillarbox", choices=["pillarbox", "blur", "imagen", "crop"],
        help="Relleno para fuente horizontal (default: 'pillarbox'). "
             "'blur' usa el mismo video difuminado; 'imagen' usa video "
             "arriba + una imagen de edicion_video/assets/imagenes_relleno/<mood>/ "
             "abajo (cae a pillarbox si no hay ninguna para ese mood); 'crop' "
             "recorta el ancho centrado a 9:16 sin relleno (pierde bordes "
             "laterales, solo recomendable si el sujeto está centrado). "
             "Sin efecto si el video fuente ya es vertical.",
    )
    p.add_argument(
        "--facecam-rect", dest="facecam_rect", default=None,
        help="Split-screen (Layout C): rect 'x,y,w,h' en píxeles del video "
             "FUENTE para el facecam. Requiere también --contenido-rect.",
    )
    p.add_argument(
        "--contenido-rect", dest="contenido_rect", default=None,
        help="Split-screen (Layout C): rect 'x,y,w,h' en píxeles del video "
             "FUENTE para el contenido. Requiere también --facecam-rect.",
    )
    p.add_argument(
        "--overlay-ocultar", dest="overlays_ocultar", action="append", default=[],
        help="Rect 'x,y,w,h' a tapar con una caja negra (ej. watermark). "
             "Repetible para varios overlays. Solo con split-screen.",
    )
    p.add_argument(
        "--mood", default="neutral",
        help="Mezcla música de fondo de edicion_video/assets/musica/<mood>/ "
             "(default: 'neutral'). Sin efecto si esa carpeta no tiene pistas.",
    )
    p.add_argument(
        "--momento-enfasis", dest="momento_enfasis", type=float, default=None,
        help="Segundos (relativos a --inicio) donde aplicar un zoom/punch-in "
             "de prueba (ver agentes/agent2_range_refiner.py: momento_enfasis_seg). "
             "Sin esto, no hay zoom.",
    )
    p.add_argument(
        "--efecto-sonido", dest="efecto_sonido", default=None,
        help="Tipo de efecto corto (ej. 'whoosh') a mezclar de "
             "edicion_video/assets/efectos_sonido/<tipo>/, anclado a "
             "--momento-enfasis (requiere que ambos estén presentes).",
    )
    return p.parse_args()


def _extract_transcript_window(
    session_dir: Path, inicio_s: int, fin_s: int, buffer_s: int = 45,
) -> tuple[str, str]:
    """
    Busca en session_dir/chunks/*/transcripcion_completa.txt las líneas dentro
    del rango exacto [inicio_s, fin_s) y dentro de un rango con contexto
    [inicio_s - buffer_s, fin_s + buffer_s). Los timestamps de esos archivos
    son segundos absolutos del video completo (mismo formato que --inicio/--fin).

    Retorna (transcripcion_rango, transcripcion_contexto). Si no hay chunks
    transcritos aún, retorna ("", "").
    """
    pattern = re.compile(r"^\[(\d+):(\d+)\]")
    rango_lines    = []
    contexto_lines = []

    ctx_inicio = max(0, inicio_s - buffer_s)
    ctx_fin    = fin_s + buffer_s

    for chunk_txt in sorted(session_dir.glob("chunks/*/transcripcion_completa.txt")):
        for line in chunk_txt.read_text(encoding="utf-8").splitlines():
            m = pattern.match(line)
            if not m:
                continue
            ts = int(m.group(1)) * 60 + int(m.group(2))
            if inicio_s <= ts < fin_s:
                rango_lines.append(line)
            if ctx_inicio <= ts < ctx_fin:
                contexto_lines.append(line)

    return "\n".join(rango_lines), "\n".join(contexto_lines)


def validate(args: argparse.Namespace, video_path: Path) -> None:
    if not video_path.exists():
        print(f"[CLIP_MANUAL] Error: video no encontrado en {video_path}")
        sys.exit(1)

    s = _timestamp_to_seconds(args.inicio)
    e = _timestamp_to_seconds(args.fin)
    if s >= e:
        print(f"[CLIP_MANUAL] Error: --inicio ({args.inicio}) debe ser menor que --fin ({args.fin})")
        sys.exit(1)


def main() -> None:
    args       = parse_args()
    video_path = Path(args.video)

    validate(args, video_path)

    # Detectar session_id desde la ruta
    parts      = video_path.parts
    session_id = next(
        (parts[i + 1] for i, p in enumerate(parts) if p == "stream_data"),
        video_path.parent.name,
    )
    session_dir  = video_path.parent
    clips_custom = session_dir / "clips_custom"
    clips_custom.mkdir(exist_ok=True)

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    clip_name = f"custom_{ts}.mp4"
    meta_name = f"custom_{ts}.json"
    clip_path = clips_custom / clip_name

    duracion_s = _timestamp_to_seconds(args.fin) - _timestamp_to_seconds(args.inicio)

    border = "═" * 39
    print(border)
    print("  CLIP MANUAL — IDEA MILLONARIA")
    print(border)
    l1_display = f'"{args.linea1}"' if args.linea1 else "(sin texto)"
    l2_display = f'"{args.linea2}"' if args.linea2 else "(sin texto)"
    print(f"  Video   : {args.video}")
    print(f"  Rango   : {args.inicio} -> {args.fin}  ({duracion_s}s)")
    print(f"  Línea 1 : {l1_display}")
    print(f"  Línea 2 : {l2_display}")
    print(f"  Config  : {args.config}")
    print(f"  Salida  : {clips_custom}")
    if args.entrenamiento:
        print(f"  Modo    : entrenamiento (sin Claude)")
    print(border)

    print("[CLIP_MANUAL] Cortando video...")

    font_rel, _  = _prepare_font()
    vid_info     = _detect_video_info(video_path)
    has_lb       = vid_info["has_letterbox"]
    bar_h        = vid_info["bar_height"]

    def _parse_rect(s: str) -> dict:
        x, y, w, h = (int(v.strip()) for v in s.split(","))
        return {"x": x, "y": y, "w": w, "h": h}

    layout_streaming = None
    if args.facecam_rect and args.contenido_rect:
        layout_streaming = {
            "facecam_rect":   _parse_rect(args.facecam_rect),
            "contenido_rect": _parse_rect(args.contenido_rect),
            "overlays_ocultar": [_parse_rect(o) for o in args.overlays_ocultar],
        }

    ok = _cut_clip(
        video_path, args.inicio, args.fin,
        args.linea1 or "", args.linea2 or "",
        clip_path, font_rel, has_lb, bar_h,
        session_dir=session_dir,
        mood=args.mood,
        estilo_texto=args.estilo_texto,
        momento_enfasis_seg=args.momento_enfasis,
        source_width=vid_info["width"], source_height=vid_info["height"],
        cta_texto=args.cta_texto,
        palabras_clave=[p.strip() for p in args.palabras_clave.split(",") if p.strip()],
        layout=args.layout,
        layout_streaming=layout_streaming,
        efecto_sonido=args.efecto_sonido,
    )

    if not ok:
        print("[CLIP_MANUAL] FFmpeg fallo — revisa los mensajes de error arriba.")
        sys.exit(1)

    size_kb = clip_path.stat().st_size // 1024
    print(f"[CLIP_MANUAL] OK {clip_name} — {size_kb} KB")
    print(f"[CLIP_MANUAL] Guardado en: {clips_custom}")

    meta = {
        "clip":          clip_name,
        "inicio":        args.inicio,
        "fin":           args.fin,
        "texto_linea1":  args.linea1 or "",
        "texto_linea2":  args.linea2 or "",
        "config":        args.config,
        "creado_manual": True,
        "fecha":         datetime.now().isoformat(timespec="seconds"),
    }

    if args.entrenamiento:
        inicio_s = _timestamp_to_seconds(args.inicio)
        fin_s    = _timestamp_to_seconds(args.fin)
        rango_txt, contexto_txt = _extract_transcript_window(session_dir, inicio_s, fin_s)
        meta["modo_entrenamiento"]     = True
        meta["transcripcion_rango"]    = rango_txt
        meta["transcripcion_contexto"] = contexto_txt
        if args.nota:
            meta["nota_editor"] = args.nota
        if not rango_txt:
            print("[CLIP_MANUAL] ⚠ No se encontró transcripción en chunks/ — guardado sin texto")
        else:
            print("[CLIP_MANUAL] ✅ Transcripción de rango y contexto guardadas (modo entrenamiento)")

    (clips_custom / meta_name).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
