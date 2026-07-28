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
  python edicion_video/agent4_video_cutter.py stream_data/<session_id>/contenido.json
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
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


_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),  # pictogramas, emoticonos, transporte, suplementarios
    (0x2600, 0x27BF),    # símbolos varios y dingbats
    (0x2B00, 0x2BFF),    # estrellas, flechas
)


def _is_emoji(c: str) -> bool:
    cp = ord(c)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _sanitize_text(text: str) -> str:
    """Keep printable Latin characters + emoji; strip FFmpeg filter metacharacters."""
    # Keep ASCII + Latin-1 Supplement + Latin Extended A/B (ñ, á, é, ¡, ¿, etc.) + emoji
    clean = "".join(c for c in text if (ord(c) < 0x0250 or _is_emoji(c)) and c.isprintable())
    # ',' splits the filter chain; ':' splits options; the rest break quoting.
    for ch in [",", ":", ";", '"', "'"]:
        clean = clean.replace(ch, " ")
    return re.sub(r"  +", " ", clean).strip()


_EMOJI_ASSETS_DIR = Path(__file__).parent / "assets" / "emoji"


def _get_emoji_image(char: str) -> Path | None:
    """
    Devuelve la ruta a un PNG del emoji, descargándolo una sola vez a
    assets/emoji/ si no está en caché local (llamadas siguientes son gratis).

    Fuente: Noto Emoji (googlefonts/noto-emoji) — Apache 2.0 / OFL, uso
    comercial libre y sin atribución requerida en el producto final (a
    diferencia de Twemoji, que es CC-BY 4.0 y sí la exige).

    FFmpeg drawtext no puede renderizar emojis a color (limitación conocida
    de libfreetype con fuentes CBDT/CBLC) — confirmado empíricamente: sale
    como un cuadrado vacío ("tofu"). Por eso se superpone como imagen en vez
    de intentar dibujarlo como texto.

    Retorna None si no se pudo conseguir (emoji no está en el repo de Noto,
    sin red, etc.) — el llamador debe omitir el emoji, nunca fallar el corte
    completo por esto.
    """
    _EMOJI_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    codepoint = f"{ord(char):x}"
    dest      = _EMOJI_ASSETS_DIR / f"emoji_u{codepoint}.png"
    if dest.exists():
        return dest

    url = f"https://raw.githubusercontent.com/googlefonts/noto-emoji/main/png/128/emoji_u{codepoint}.png"
    try:
        urllib.request.urlretrieve(url, dest)
        return dest
    except Exception:
        return None


def _split_trailing_emoji(text: str) -> tuple[str, str]:
    """
    Separa un emoji final del resto del texto (los prompts de contenido
    piden "remate con emoji al final" — solo se soporta ese caso, un emoji
    al final de la línea, no emojis intercalados en medio del texto).
    """
    stripped = text.rstrip()
    if stripped and _is_emoji(stripped[-1]):
        return stripped[:-1].rstrip(), stripped[-1]
    return text, ""


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


_EMOJI_GAP = 8  # px entre el final del texto y el emoji


def _emoji_overlay(
    text_sin_emoji: str, emoji_char: str, fs: int, lh: int, y: int, enable: str = "",
) -> dict | None:
    """
    Calcula dónde superponer la imagen del emoji justo después del texto
    centrado. Usa el mismo heurístico _CHAR_WIDTH_FACTOR que ya usa el resto
    del archivo para estimar anchos de caja — no es pixel-perfect (el ancho
    real lo mide FFmpeg internamente al renderizar, no accesible desde acá),
    pero es consistente con el nivel de precisión del resto del layout.

    Retorna None si no se consiguió la imagen del emoji (sin red, etc.) —
    el llamador debe simplemente no mostrar el emoji en ese caso.
    """
    img = _get_emoji_image(emoji_char)
    if img is None:
        return None
    text_w = int(len(text_sin_emoji) * fs * _CHAR_WIDTH_FACTOR)
    size   = int(lh * 0.9)
    return {
        "path":         img,
        "x":            540 + text_w // 2 + _EMOJI_GAP,
        "y":            y + (lh - size) // 2,
        "size":         size,
        "extra_w":      size + _EMOJI_GAP,
        "enable":       enable,
    }


def _build_vf(linea1: str, linea2: str, font_rel: str, has_letterbox: bool, bar_height: int) -> tuple[str, dict, list[dict]]:
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

    # drawtext no puede renderizar emoji a color (ver _get_emoji_image) — se
    # separan acá y se agregan como overlays de imagen sobre el texto.
    txt1, emoji1 = _split_trailing_emoji(safe1)
    txt2, emoji2 = _split_trailing_emoji(safe2)

    base = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    )
    filters  = [base]
    params   = {}
    overlays = []

    if has_letterbox:
        pad = 20

        if txt1 and txt2:
            # ── Dos líneas: anclar al inicio del video ──────────────
            fs1 = _pick_fontsize(txt1, [72, 58, 48], 900)
            fs2 = _pick_fontsize(txt2, [58, 44, 36], 900)
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

            ov1 = _emoji_overlay(txt1, emoji1, fs1, lh1, y1) if emoji1 else None
            ov2 = _emoji_overlay(txt2, emoji2, fs2, lh2, y2) if emoji2 else None
            extra_w = max(ov1["extra_w"] if ov1 else 0, ov2["extra_w"] if ov2 else 0)

            est_w = max(
                int(len(txt1) * fs1 * _CHAR_WIDTH_FACTOR),
                int(len(txt2) * fs2 * _CHAR_WIDTH_FACTOR),
            ) + extra_w
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
                f"drawtext={font_opt}expansion=none:text='{txt1}':"
                f"fontsize={fs1}:fontcolor=black:x=(w-text_w)/2:y={y1}"
            )
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{txt2}':"
                f"fontsize={fs2}:fontcolor=black:x=(w-text_w)/2:y={y2}"
            )
            overlays = [ov for ov in (ov1, ov2) if ov]

        elif txt1 or txt2:
            # ── Una línea: anclada justo encima del video (igual que A) ─
            text  = txt1 if txt1 else txt2
            emoji = emoji1 if txt1 else emoji2
            fs   = _pick_fontsize(text, [72, 58, 48], 900)
            lh   = int(fs * 1.2)
            margin = 20

            y_text = bar_height - margin - lh
            ov     = _emoji_overlay(text, emoji, fs, lh, y_text) if emoji else None
            extra_w = ov["extra_w"] if ov else 0

            est_w  = int(len(text) * fs * _CHAR_WIDTH_FACTOR) + extra_w
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
            overlays = [ov] if ov else []

        else:
            # ── Sin texto ────────────────────────────────────────────
            params = {"caso": "A0", "bar_height": bar_height}

    else:
        # Caso B: centrado, semitransparente, solo primeros 4s
        params = {"caso": "B"}
        if txt1:
            fs1 = 52
            lh1 = int(fs1 * 1.2)
            ov1 = _emoji_overlay(txt1, emoji1, fs1, lh1, 200, enable="lte(t,4)") if emoji1 else None
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{txt1}':"
                f"fontsize={fs1}:fontcolor=black:"
                "x=(w-text_w)/2:y=200:"
                "enable=lte(t\\,4):"
                "box=1:boxcolor=white@0.85:boxborderw=12"
            )
            if ov1:
                overlays.append(ov1)
        if txt2:
            fs2 = 40
            lh2 = int(fs2 * 1.2)
            ov2 = _emoji_overlay(txt2, emoji2, fs2, lh2, 275, enable="lte(t,4)") if emoji2 else None
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{txt2}':"
                f"fontsize={fs2}:fontcolor=black:"
                "x=(w-text_w)/2:y=275:"
                "enable=lte(t\\,4):"
                "box=1:boxcolor=white@0.85:boxborderw=10"
            )
            if ov2:
                overlays.append(ov2)

    return ",".join(filters), params, overlays


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

    vf, params, overlays = _build_vf(linea1, linea2, font_rel, has_letterbox, bar_height)

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

    if overlays:
        print(f"         Emoji   : {len(overlays)} superpuesto(s) como imagen (drawtext no soporta color)")
        filter_complex = f"[0:v]{vf}[v0]"
        label = "v0"
        for i, ov in enumerate(overlays):
            emoji_label = f"e{i}"
            next_label  = f"v{i + 1}"
            filter_complex += f";[{i + 1}:v]scale={ov['size']}:{ov['size']},format=rgba[{emoji_label}]"
            enable_opt = f":enable='{ov['enable']}'" if ov.get("enable") else ""
            filter_complex += f";[{label}][{emoji_label}]overlay=x={ov['x']}:y={ov['y']}{enable_opt}[{next_label}]"
            label = next_label

        cmd_con_subtitulo = ["ffmpeg", "-ss", inicio, "-i", str(video_path)]
        for ov in overlays:
            cmd_con_subtitulo += ["-i", str(ov["path"])]
        cmd_con_subtitulo += [
            "-t", str(duracion), "-v", "error",
            "-filter_complex", filter_complex,
            "-map", f"[{label}]", "-map", "0:a",
            "-c:v", "libx264", "-c:a", "aac", "-y",
            str(output_path),
        ]
    else:
        cmd_con_subtitulo = [
            "ffmpeg", "-ss", inicio, "-i", str(video_path),
            "-t", str(duracion), "-v", "error",
            "-vf", vf,
            "-c:v", "libx264", "-c:a", "aac", "-y",
            str(output_path),
        ]

    cmd_sin_subtitulo = [
        "ffmpeg", "-ss", inicio, "-i", str(video_path),
        "-t", str(duracion), "-v", "error",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-c:a", "aac", "-y",
        str(output_path),
    ]

    attempts = [
        ("con subtítulo", cmd_con_subtitulo),
        ("sin subtítulo", cmd_sin_subtitulo),
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
        print("\nUso: python edicion_video/agent4_video_cutter.py <path/contenido.json>")
        print("Ejemplo: python edicion_video/agent4_video_cutter.py stream_data/20260529_143022/contenido.json\n")
        sys.exit(1)

    run_agent(sys.argv[1])
