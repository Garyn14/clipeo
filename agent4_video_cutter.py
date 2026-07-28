"""
===========================================
  IDEA MILLONARIA - Pipeline Paso 5
  Agent 4: Cortador de Video + Subtítulos
===========================================

Lee contenido.json, corta el video original según los rangos
de los clips marcados para publicar, agrega el hook como
subtítulo quemado y exporta en formato vertical 9:16
listo para TikTok / Reels / Shorts.

Uso:
  python agent4_video_cutter.py stream_data/<session_id>/contenido.json
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import re
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from core.utils import _timestamp_to_seconds, setup_ffmpeg_path
setup_ffmpeg_path()


def _normalize_timestamp(ts: str) -> str:
    """
    Convierte cualquier timestamp a HH:MM:SS válido para FFmpeg.

    "71:41"    → "01:11:41"
    "83:52"    → "01:23:52"
    "07:04"    → "00:07:04"
    "01:11:41" → "01:11:41"
    """
    partes = re.sub(r":+", ":", ts.strip()).split(":")
    try:
        if len(partes) == 2:
            total = int(partes[0]) * 60 + int(partes[1])
            hh = total // 3600
            mm = (total % 3600) // 60
            ss = total % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        elif len(partes) == 3:
            hh, mm, ss = int(partes[0]), int(partes[1]), int(partes[2])
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
    except ValueError:
        pass
    return ts


def _sanitize_text(text: str) -> str:
    """Keep printable Latin characters; strip emojis and FFmpeg filter metacharacters."""
    # Keep ASCII + Latin-1 Supplement + Latin Extended A/B (ñ, á, é, ¡, ¿, etc.)
    clean = "".join(c for c in text if ord(c) < 0x0250 and c.isprintable())
    # ',' splits the filter chain; ':' splits options; the rest break quoting.
    for ch in [",", ":", ";", '"', "'"]:
        clean = clean.replace(ch, " ")
    return re.sub(r"  +", " ", clean).strip()


def _prepare_font() -> tuple[str, str]:
    """
    Copia la mejor fuente disponible a stream_data/ para evitar el problema
    del colon de Windows en paths de FFmpeg.

    Prioridad: Impact → Arial Black → Arial Bold → Arial
    Retorna (rel_path, font_name).
    """
    candidates = [
        ("Impact",      r"C:\Windows\Fonts\Impact.ttf",   "impact.ttf"),
        ("Arial Black", r"C:\Windows\Fonts\ariblk.ttf",   "ariblk.ttf"),
        ("Arial Bold",  r"C:\Windows\Fonts\arialbd.ttf",  "arialbd.ttf"),
        ("Arial",       r"C:\Windows\Fonts\arial.ttf",    "arial.ttf"),
    ]
    Path("stream_data").mkdir(exist_ok=True)
    for name, src_path, dest_name in candidates:
        src  = Path(src_path)
        dest = Path("stream_data") / dest_name
        if src.exists():
            if not dest.exists():
                shutil.copy(src, dest)
            return dest.as_posix(), name   # forward slashes — backslash se interpreta como escape en filtros FFmpeg
    return "", "ninguna"


def _find_video(session_dir: Path) -> Path | None:
    """Return the largest video file in the session root (skips clips/ subdir)."""
    candidates = []
    for ext in ("*.mp4", "*.mkv", "*.webm"):
        candidates.extend(session_dir.glob(ext))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


_CHAR_WIDTH_FACTOR = 0.52   # Arial avg char width / font_size (heurístico, mezcla minúsculas + espacios)


def _pick_fontsize(text: str, candidates: list[int], max_px: int = 900) -> int:
    """Devuelve el mayor tamaño de fuente donde el ancho estimado del texto no supera max_px."""
    for fs in candidates:
        if len(text) * fs * _CHAR_WIDTH_FACTOR <= max_px:
            return fs
    return candidates[-1]


def _detect_video_info(video_path: Path) -> dict:
    """
    Detecta dimensiones del video fuente y si producirá barras negras en salida 9:16.
    Retorna: {width, height, has_letterbox, bar_height}
    """
    r = subprocess.run([
        "ffprobe", "-v", "quiet", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(video_path),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace")

    try:
        data = json.loads(r.stdout)
        w    = int(data["streams"][0]["width"])
        h    = int(data["streams"][0]["height"])
    except (KeyError, IndexError, json.JSONDecodeError, ValueError):
        return {"width": 0, "height": 0, "has_letterbox": False, "bar_height": 0}

    # Fuente landscape → al escalar a 1080x1920 produce barras arriba y abajo
    has_letterbox = w > h
    bar_height    = 0
    if has_letterbox:
        scaled_h = int(1080 * h / w)
        if scaled_h % 2:
            scaled_h -= 1          # FFmpeg necesita dimensiones pares
        bar_height = (1920 - scaled_h) // 2

    return {"width": w, "height": h, "has_letterbox": has_letterbox, "bar_height": bar_height}


def _build_vf(linea1: str, linea2: str, font_rel: str, has_letterbox: bool, bar_height: int) -> tuple[str, dict]:
    """
    Caso A  (letterbox, 2 líneas): texto anclado justo encima del video.
    Caso A1 (letterbox, 1 línea):  línea única centrada verticalmente en la barra.
    Caso A0 (letterbox, 0 líneas): sin texto, sin box.
    Caso B  (vertical):            texto centrado, semitransparente, primeros 4s.

    Retorna (filtro_vf, params_debug).
    """
    safe1    = _sanitize_text(linea1) if linea1 else ""
    safe2    = _sanitize_text(linea2) if linea2 else ""
    font_opt = f"fontfile={font_rel}:" if font_rel else ""

    base = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    )
    filters = [base]
    params  = {}

    if has_letterbox:
        pad = 20

        if safe1 and safe2:
            # ── Dos líneas: anclar al inicio del video ──────────────
            fs1 = _pick_fontsize(safe1, [72, 58, 48], 900)
            fs2 = _pick_fontsize(safe2, [58, 44, 36], 900)
            lh1 = int(fs1 * 1.2)
            lh2 = int(fs2 * 1.2)
            gap    = 18
            margin = 20

            y2 = bar_height - margin - lh2
            y1 = y2 - gap - lh1

            steps1 = {72: 58, 58: 48}
            steps2 = {58: 44, 44: 36}
            while y1 < pad and (fs1 in steps1 or fs2 in steps2):
                if fs1 in steps1:
                    fs1 = steps1[fs1]
                elif fs2 in steps2:
                    fs2 = steps2[fs2]
                lh1 = int(fs1 * 1.2)
                lh2 = int(fs2 * 1.2)
                y2  = bar_height - margin - lh2
                y1  = y2 - gap - lh1

            if y2 + lh2 > bar_height - 10:
                y2 = bar_height - 10 - lh2
                y1 = y2 - gap - lh1

            est_w = max(
                int(len(safe1) * fs1 * _CHAR_WIDTH_FACTOR),
                int(len(safe2) * fs2 * _CHAR_WIDTH_FACTOR),
            )
            box_w = min(1060, est_w + 2 * pad)
            box_h = lh1 + gap + lh2 + 2 * pad
            box_x = (1080 - box_w) // 2
            y_box = y1 - pad

            params = {
                "caso": "A", "fs1": fs1, "fs2": fs2,
                "lh1": lh1, "lh2": lh2,
                "y1": y1, "y2": y2, "y_box": y_box,
                "box_w": box_w, "box_h": box_h, "bar_height": bar_height,
            }

            filters.append(f"drawbox=x={box_x}:y={y_box}:w={box_w}:h={box_h}:color=white:t=fill")
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe1}':"
                f"fontsize={fs1}:fontcolor=black:x=(w-text_w)/2:y={y1}"
            )
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe2}':"
                f"fontsize={fs2}:fontcolor=black:x=(w-text_w)/2:y={y2}"
            )

        elif safe1 or safe2:
            # ── Una línea: anclada justo encima del video (igual que A) ─
            text = safe1 if safe1 else safe2
            fs   = _pick_fontsize(text, [72, 58, 48], 900)
            lh   = int(fs * 1.2)
            margin = 20

            y_text = bar_height - margin - lh
            est_w  = int(len(text) * fs * _CHAR_WIDTH_FACTOR)
            box_w  = min(1060, est_w + 2 * pad)
            box_h  = lh + 2 * pad
            box_x  = (1080 - box_w) // 2
            y_box  = y_text - pad

            params = {
                "caso": "A1", "fs": fs, "lh": lh,
                "y_text": y_text, "y_box": y_box,
                "box_w": box_w, "box_h": box_h, "bar_height": bar_height,
            }

            filters.append(f"drawbox=x={box_x}:y={y_box}:w={box_w}:h={box_h}:color=white:t=fill")
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{text}':"
                f"fontsize={fs}:fontcolor=black:x=(w-text_w)/2:y={y_text}"
            )

        else:
            # ── Sin texto ────────────────────────────────────────────
            params = {"caso": "A0", "bar_height": bar_height}

    else:
        # Caso B: centrado, semitransparente, solo primeros 4s
        params = {"caso": "B"}
        if safe1:
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe1}':"
                "fontsize=52:fontcolor=black:"
                "x=(w-text_w)/2:y=200:"
                "enable=lte(t\\,4):"
                "box=1:boxcolor=white@0.85:boxborderw=12"
            )
        if safe2:
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe2}':"
                "fontsize=40:fontcolor=black:"
                "x=(w-text_w)/2:y=275:"
                "enable=lte(t\\,4):"
                "box=1:boxcolor=white@0.85:boxborderw=10"
            )

    return ",".join(filters), params


def _cut_clip(
    video_path: Path, inicio: str, fin: str,
    linea1: str, linea2: str,
    output_path: Path, font_rel: str,
    has_letterbox: bool, bar_height: int,
) -> bool:
    """
    Corta [inicio, fin] del video y quema las dos líneas de texto.
    Fallback a corte sin subtítulo si drawtext falla.
    """
    inicio   = _normalize_timestamp(inicio)
    fin      = _normalize_timestamp(fin)
    duracion = _timestamp_to_seconds(fin) - _timestamp_to_seconds(inicio)
    base_cmd = [
        "ffmpeg",
        "-ss", inicio,           # input seek (rápido, keyframe)
        "-i", str(video_path),
        "-t", str(duracion),     # duración relativa al seek point
        "-v", "error",           # silenciar Late SEI spam
        "-c:v", "libx264", "-c:a", "aac", "-y",
    ]

    vf, params = _build_vf(linea1, linea2, font_rel, has_letterbox, bar_height)

    # Imprimir coordenadas para verificación visual
    if params.get("caso") == "A":
        lh1 = params["lh1"]
        lh2 = params["lh2"]
        y2  = params["y2"]
        bh  = params["bar_height"]
        print(f"         Layout  : Caso A — letterbox  |  barra {bh}px")
        print(f"         Fuentes : L1={params['fs1']}pt (lh={lh1}px)  L2={params['fs2']}pt (lh={lh2}px)")
        print(f"         y_box   : {params['y_box']}px  h={params['box_h']}px  w={params['box_w']}px")
        print(f"         y_L1    : {params['y1']}px")
        print(f"         y_L2    : {y2}px  →  fondo={y2+lh2}px  (bar={bh}px  ok={y2+lh2 < bh})")
        print(f"         video @ : y={bh}px  (margen={bh - y2 - lh2}px)")
        if y2 + lh2 >= bh:
            print(f"  ⚠️  L2 desbordaba la barra — corregido por safety guard")
    elif params.get("caso") == "A1":
        lh = params["lh"]
        bh = params["bar_height"]
        print(f"         Layout  : Caso A1 — letterbox 1 línea  |  barra {bh}px")
        print(f"         Fuente  : {params['fs']}pt (lh={lh}px)")
        print(f"         y_box   : {params['y_box']}px  h={params['box_h']}px  w={params['box_w']}px")
        print(f"         y_text  : {params['y_text']}px  (centro barra: {bh//2}px)")
    elif params.get("caso") == "A0":
        print(f"         Layout  : Caso A0 — letterbox sin texto  |  barra {params['bar_height']}px")

    attempts = [
        ("con subtítulo", base_cmd + ["-vf", vf, str(output_path)]),
        ("sin subtítulo", base_cmd + ["-vf",
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
            str(output_path)]),
    ]

    for label, cmd in attempts:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            if label == "sin subtítulo":
                print(f"  ⚠️  Subtítulo falló — clip guardado sin texto")
            return True
        if label == "con subtítulo":
            print(f"  ⚠️  Subtítulo falló ({result.stderr.split(chr(10))[-2][:80]}), reintentando sin texto...")

    print(f"  ❌ FFmpeg error:\n{result.stderr[-600:]}")
    return False


def run_agent(
    contenido_path: str,
    video_path_override: Path | None = None,
    clips_dir_override:  Path | None = None,
    clip_offset: int = 0,
) -> list[dict]:
    """
    video_path_override — usar este video en lugar de buscarlo en session_dir
    clips_dir_override  — guardar clips aquí en lugar de session_dir/clips/
    clip_offset         — continuar numeración desde este índice (clip_{offset+1:03d})
    """
    contenido_file = Path(contenido_path)
    if not contenido_file.exists():
        print(f"[AGENT4] ❌ No se encontró: {contenido_file}")
        sys.exit(1)

    session_dir    = contenido_file.parent
    contenido_data = json.loads(contenido_file.read_text(encoding="utf-8")).get("contenido", [])
    a_publicar     = [c for c in contenido_data if c.get("publicar")]

    if not a_publicar:
        print("[AGENT4] ℹ️  No hay clips marcados para publicar en contenido.json")
        return []

    video_path = video_path_override or _find_video(session_dir)
    if not video_path:
        print(f"[AGENT4] ❌ No se encontró video original (.mp4/.mkv/.webm) en: {session_dir}")
        print( "[AGENT4]    Copiá el video del stream a esa carpeta antes de correr este agente.")
        sys.exit(1)

    clips_dir = clips_dir_override or (session_dir / "clips")
    clips_dir.mkdir(exist_ok=True)

    font_rel, font_name = _prepare_font()
    vid_info  = _detect_video_info(video_path)
    has_lb    = vid_info["has_letterbox"]
    bar_h     = vid_info["bar_height"]
    caso      = f"A — letterbox  (barra negra {bar_h}px arriba/abajo)" if has_lb else "B — vertical nativo"

    print(f"\n[AGENT4] Sesión   : {session_dir.name}")
    print(f"[AGENT4] Video    : {video_path.name}  ({video_path.stat().st_size // 1024} KB)")
    print(f"[AGENT4] Fuente   : {vid_info['width']}x{vid_info['height']}  →  Caso {caso}")
    print(f"[AGENT4] Clips    : {len(a_publicar)} para cortar")
    print(f"[AGENT4] Font     : {font_name}  ({font_rel or 'default'})")
    print(f"[AGENT4] Salida   : {clips_dir}")
    print(f"[AGENT4] {'─' * 42}\n")

    resultados = []

    for i, item in enumerate(a_publicar):
        rango    = item.get("rango_original", {})
        inicio   = rango.get("inicio",            "00:00")
        fin      = rango.get("fin",               "00:00")
        duracion = rango.get("duracion_segundos", 0)
        linea1   = item.get("texto_linea1",       "")
        linea2   = item.get("texto_linea2",       "")
        hashtags = item.get("hashtags",           [])
        score    = item.get("score",              0)

        clip_name = f"clip_{i + 1 + clip_offset:03d}.mp4"
        meta_name = f"clip_{i + 1 + clip_offset:03d}.json"
        clip_path = clips_dir / clip_name
        meta_path = clips_dir / meta_name

        print(f"[AGENT4] Clip {i + 1}/{len(a_publicar)}  →  {clip_name}")
        print(f"         Rango   : {inicio} → {fin}  ({duracion}s)")
        print(f"         Línea 1 : {linea1}")
        print(f"         Línea 2 : {linea2}")
        print(f"         Texto   : '{_sanitize_text(linea1)}' / '{_sanitize_text(linea2)}'  (sanitizado)")

        ok = _cut_clip(video_path, inicio, fin, linea1, linea2, clip_path, font_rel, has_lb, bar_h)

        if ok:
            size_kb = clip_path.stat().st_size // 1024
            print(f"  ✅ {clip_name} — {size_kb} KB\n")
        else:
            print(f"  ❌ Falló el corte de {clip_name}\n")

        meta = {
            "clip":                clip_name,
            "texto_linea1":        linea1,
            "texto_linea2":        linea2,
            "hashtags":            hashtags,
            "score":               score,
            "duracion_segundos":   duracion,
            "listo_para_publicar": False,
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        resultados.append({"ok": ok, "meta": meta, "path": str(clip_path)})

    # ── Tabla resumen ────────────────────────────────────────
    exitosos = [r for r in resultados if r["ok"]]

    print(f"[AGENT4] {'─' * 42}")
    print(f"[AGENT4] RESUMEN")
    print(f"[AGENT4] {'─' * 42}")
    for r in resultados:
        m      = r["meta"]
        estado = "✅" if r["ok"] else "❌"
        print(f"  {estado}  {m['clip']}  |  {m['duracion_segundos']}s  |  score {m['score']}  |  \"{m['texto_linea1']} / {m['texto_linea2']}\"")

    print(f"\n[AGENT4] {len(exitosos)}/{len(resultados)} clips generados correctamente")
    print(f"[AGENT4] Clips en : {clips_dir}")
    print(f"[AGENT4] Revisá cada clip y cambiá 'listo_para_publicar' a true en el .json\n")

    return resultados


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUso: python agent4_video_cutter.py <path/contenido.json>")
        print("Ejemplo: python agent4_video_cutter.py stream_data/20260529_143022/contenido.json\n")
        sys.exit(1)

    run_agent(sys.argv[1])
