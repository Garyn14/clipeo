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
import os
import random
import re
import shutil
import subprocess
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


def _sanitize_text(text: str) -> str:
    """Keep printable Latin characters; strip emojis and FFmpeg filter metacharacters."""
    # Keep ASCII + Latin-1 Supplement + Latin Extended A/B (ñ, á, é, ¡, ¿, etc.)
    # Sin emoji a propósito: drawtext no los renderiza a color (tofu), y aunque
    # se probó un overlay de imagen para mostrarlos bien, el criterio editorial
    # es no usarlos en el video quemado — el texto solo alcanza.
    clean = "".join(c for c in text if ord(c) < 0x0250 and c.isprintable())
    # ',' splits the filter chain; ':' splits options; the rest break quoting.
    for ch in [",", ":", ";", '"', "'"]:
        clean = clean.replace(ch, " ")
    return re.sub(r"  +", " ", clean).strip()


_MUSICA_DIR        = Path(__file__).parent / "assets" / "musica"
_MUSICA_VOLUMEN    = 0.15  # bajo, para no tapar el diálogo original


def _pick_music_track(mood: str) -> Path | None:
    """
    Elige (al azar) una pista de edicion_video/assets/musica/<mood>/ para
    mezclar de fondo. Cae a la carpeta "neutral" si el mood pedido no tiene
    pistas propias, y retorna None si no hay ninguna disponible — el clip
    sale sin música de fondo en vez de fallar el corte por esto.
    """
    for candidate in (mood, "neutral"):
        carpeta = _MUSICA_DIR / candidate
        if carpeta.is_dir():
            pistas = [p for p in carpeta.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a")]
            if pistas:
                return random.choice(pistas)
    return None


_IMAGENES_RELLENO_DIR = Path(__file__).parent / "assets" / "imagenes_relleno"


def _pick_imagen_relleno(mood: str) -> Path | None:
    """
    Elige (al azar) una imagen de edicion_video/assets/imagenes_relleno/<mood>/
    para el layout "imagen" (Fase 13). Mismo patrón que _pick_music_track:
    cae a "neutral" si el mood no tiene imágenes propias, y retorna None si
    no hay ninguna disponible — layout="imagen" cae a pillarbox en vez de
    fallar el corte por esto (ver _build_vf).
    """
    for candidate in (mood, "neutral"):
        carpeta = _IMAGENES_RELLENO_DIR / candidate
        if carpeta.is_dir():
            imagenes = [p for p in carpeta.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
            if imagenes:
                return random.choice(imagenes)
    return None


_EFECTOS_SONIDO_DIR = Path(__file__).parent / "assets" / "efectos_sonido"
_EFECTO_VOLUMEN     = 0.6  # más alto que _MUSICA_VOLUMEN — es puntual, no de fondo continuo


def _pick_sound_effect(tipo: str) -> Path | None:
    """
    Elige (al azar) un efecto corto de edicion_video/assets/efectos_sonido/<tipo>/
    (Fase 15). A diferencia de _pick_music_track/_pick_imagen_relleno, NO cae
    a una carpeta "neutral" — un tipo de efecto (ej. "whoosh") no tiene un
    género neutro razonable. Retorna None si la carpeta no existe o está
    vacía — el clip sale sin efecto en vez de fallar el corte por esto.
    """
    carpeta = _EFECTOS_SONIDO_DIR / tipo
    if carpeta.is_dir():
        efectos = [p for p in carpeta.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a")]
        if efectos:
            return random.choice(efectos)
    return None


_FONTS_DIR = Path(__file__).parent / "assets" / "fonts"


def _prepare_font() -> tuple[str, str]:
    """
    Copia la mejor fuente disponible a stream_data/ y devuelve su ruta relativa, para
    evitar el problema del colon de Windows (C:) en los filtros de FFmpeg.

    Prioridad: fuentes libres incluidas en el repo (iguales en cualquier máquina:
    Anton ≈ Impact, Archivo Black ≈ Arial Black) → fuentes de Windows como respaldo.
    Retorna (rel_path, font_name); ("", "ninguna") si no hay ninguna.
    """
    win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = [
        ("Anton",        _FONTS_DIR / "Anton-Regular.ttf",        "anton.ttf"),
        ("Archivo Black", _FONTS_DIR / "ArchivoBlack-Regular.ttf", "archivoblack.ttf"),
        ("Impact",       win_fonts / "Impact.ttf",                "impact.ttf"),
        ("Arial Black",  win_fonts / "ariblk.ttf",                "ariblk.ttf"),
        ("Arial Bold",   win_fonts / "arialbd.ttf",               "arialbd.ttf"),
        ("Arial",        win_fonts / "arial.ttf",                 "arial.ttf"),
    ]
    Path("stream_data").mkdir(exist_ok=True)
    for name, src, dest_name in candidates:
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


_LECTURA_PALABRAS_POR_SEG = 3.0
_LECTURA_MARGEN_SEG       = 1.0
_LECTURA_MIN_SEG          = 3.0
_LECTURA_MAX_SEG          = 7.0


def _text_display_duration(txt1: str, txt2: str) -> float:
    """
    Duración (segundos) para mostrar el texto en Caso B, según velocidad de
    lectura — no es un juicio subjetivo, es aritmética simple (palabras
    totales / palabras-por-segundo + margen de arranque), acotada para que
    un hook de 2 palabras no destelle ni uno largo se quede pegado.
    """
    palabras = len((txt1 + " " + txt2).split())
    duracion = palabras / _LECTURA_PALABRAS_POR_SEG + _LECTURA_MARGEN_SEG
    return max(_LECTURA_MIN_SEG, min(_LECTURA_MAX_SEG, duracion))


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


_FACECAM_ALTO_PCT = 0.4   # ~35-45% observado en la muestra real (Layout C)


def _build_vf_splitscreen(
    facecam_rect: dict, contenido_rect: dict,
    overlays_ocultar: list[dict] | None = None,
) -> str:
    """
    Compone Layout C (facecam apilado sobre contenido) recortando dos
    regiones FIJAS del mismo frame fuente — calibradas manualmente una vez
    por canal (ver docs/ESTRUCTURA_DATOS.md, bloque `layout_streaming`).

    No hay dos streams de video separados: el layout de streaming del
    canal (la escena de OBS del streamer) ya trae ambos en un solo frame,
    así que esto es recorte+reescalado+apilado puro, sin necesidad de
    detección visual — el layout de un streamer es estático durante toda
    la sesión.

    Cada región se escala a un ancho de 1080 y una altura fija (40%/60%
    de 1920) para que el apilado (`vstack`) siempre dé exactamente
    1080x1920, sin importar la relación de aspecto de los rects recortados
    (puede distorsionar levemente — aceptable para la primera versión).

    overlays_ocultar (opcional): rects fijos a tapar con una caja negra
    sólida (ej. watermark de Kick) ANTES de recortar/apilar.

    facecam_rect/contenido_rect: dicts {"x","y","w","h"} en coordenadas de
    píxel del video FUENTE (no del recorte del clip).
    """
    facecam_h   = int(round(1920 * _FACECAM_ALTO_PCT / 2)) * 2
    contenido_h = 1920 - facecam_h

    ocultar = "".join(
        f"drawbox=x={r['x']}:y={r['y']}:w={r['w']}:h={r['h']}:color=black:t=fill,"
        for r in (overlays_ocultar or [])
    )

    fx, fy, fw, fh = facecam_rect["x"], facecam_rect["y"], facecam_rect["w"], facecam_rect["h"]
    cx, cy, cw, ch = contenido_rect["x"], contenido_rect["y"], contenido_rect["w"], contenido_rect["h"]

    return (
        f"{ocultar}split=2[_ss_face][_ss_cont];"
        f"[_ss_face]crop=w={fw}:h={fh}:x={fx}:y={fy},scale=1080:{facecam_h}[_ss_face2];"
        f"[_ss_cont]crop=w={cw}:h={ch}:x={cx}:y={cy},scale=1080:{contenido_h}[_ss_cont2];"
        f"[_ss_face2][_ss_cont2]vstack=inputs=2"
    )


_IMAGEN_RECORTE_ANCHO_PCT     = 0.90   # % del ancho fuente que se conserva (recorte suave, sin perder foco)
_IMAGEN_ZONA_VIDEO_PCT        = 0.60   # altura objetivo del bloque de video, como % de 1920 (60/40, énfasis en el video)
_IMAGEN_AJUSTE_VISUAL_ARRIBA  = 30     # px extra en la franja superior — junto al video se percibe más chica, se compensa a ojo


def _build_vf_imagen(source_width: int, source_height: int) -> tuple[str, dict]:
    """
    Layout "imagen" (Fase 13): el video ocupa la parte superior (recorte
    suave de ancho, alto NATURAL resultante — sin distorsión) y una imagen
    de relleno SEPARADA (no el mismo video — para eso está "blur"; no un
    crop de otra región del mismo frame — para eso está el split-screen de
    _build_vf_splitscreen) llena el resto hacia abajo. Franjas negras finas
    en los bordes del CUADRO COMPLETO (arriba de todo / abajo de todo) —
    video e imagen quedan pegados entre sí, sin negro en el medio. La
    franja de arriba queda un poco más alta que la de abajo (ajuste visual
    validado con el usuario: junto al video de contraste oscuro se percibía
    más chica de lo que en realidad es).

    Requiere un segundo input de video (la imagen) en el índice [1:v] —
    el llamador (_cut_clip) debe agregarlo a extra_inputs cuando esta rama
    se activa (ver params["imagen_activa"] que retorna _build_vf).

    Retorna (fragmento_filtro, params) — params incluye seam_y (dónde cae
    el límite video/imagen en el cuadro final) para que _build_vf ancle el
    texto ahí, solapando un poco el video (ver overlap en _build_vf).
    """
    crop_w = int(source_width * _IMAGEN_RECORTE_ANCHO_PCT)
    if crop_w % 2:
        crop_w -= 1
    x_off = (source_width - crop_w) // 2

    zona_video_objetivo = int(1920 * _IMAGEN_ZONA_VIDEO_PCT)
    video_h = int(1080 * source_height / crop_w) if crop_w else 0
    if video_h % 2:
        video_h -= 1

    sobrante     = max(0, zona_video_objetivo - video_h)
    barra_abajo  = sobrante // 2
    barra_arriba = (sobrante - barra_abajo) + _IMAGEN_AJUSTE_VISUAL_ARRIBA
    imagen_h     = 1920 - barra_arriba - video_h - barra_abajo

    fragmento = (
        f"crop=w={crop_w}:h={source_height}:x={x_off}:y=0,"
        f"scale=1080:{video_h}[_imgvidtop];"
        f"[1:v]scale=1080:{imagen_h}[_imgbot];"
        f"[_imgvidtop][_imgbot]vstack=inputs=2,"
        f"pad=1080:1920:0:{barra_arriba}:color=black"
    )
    return fragmento, {
        "video_h": video_h, "barra_arriba": barra_arriba,
        "barra_abajo": barra_abajo, "imagen_h": imagen_h,
        "seam_y": barra_arriba + video_h,
    }


def _build_vf_crop(source_width: int, source_height: int) -> str:
    """
    Layout "crop" (Fase 14): recorte centrado sin relleno (crop-to-fill) —
    llena 1080x1920 recortando el ancho de la fuente a la proporción 9:16,
    sin barras negras ni imagen/blur de relleno. Pierde información de los
    bordes laterales — recomendable solo cuando el sujeto principal está
    centrado en el frame (ver modulo_edicion_patrones_clipeo.md, sección 5).
    """
    crop_w = int(source_height * 9 / 16)
    if crop_w % 2:
        crop_w -= 1
    x_off = (source_width - crop_w) // 2
    return f"crop=w={crop_w}:h={source_height}:x={x_off}:y=0,scale=1080:1920"


def _build_vf(
    linea1: str, linea2: str, font_rel: str, has_letterbox: bool, bar_height: int,
    estilo_texto: str = "fijo",
    cta_texto: str = "", duracion_clip: float = 0,
    layout: str = "pillarbox",
    layout_streaming: dict | None = None,
    source_width: int = 0, source_height: int = 0,
    imagen_relleno_path: Path | None = None,
) -> tuple[str, dict]:
    """
    has_letterbox decide la geometría (barra negra arriba/abajo vs. centrado
    en pantalla) — nunca si hay texto o cuánto dura, eso lo decide
    estilo_texto (editorial, viene de Agent 3): "sin_texto" | "fijo" |
    "fijo_inicial" | "dinamico" | "dinamico_con_titulo". ("dinamico"/
    "dinamico_con_titulo" se resuelven en _cut_clip vía _build_vf_animated;
    si no hay datos de palabra, caen a "fijo" antes de llegar acá.)

    Caso A  (letterbox, 2 líneas): texto anclado justo encima del video.
    Caso A1 (letterbox, 1 línea):  línea única centrada verticalmente en la barra.
    Caso A0 (letterbox, 0 líneas): sin texto, sin box.
    Caso B  (vertical):            texto centrado, semitransparente.

    cta_texto (opcional, editorial): llamado a la acción quemado en los
    últimos ~3s del clip, independiente de estilo_texto/caso — siempre en
    la misma posición inferior del cuadro 1080x1920 ya escalado.

    layout (editorial, solo importa si has_letterbox): "pillarbox" (barras
    negras sólidas, default) | "blur" (fondo con el mismo video escalado y
    difuminado en vez de barras sólidas). Es una alternativa de RELLENO
    nada más — el video en primer plano queda exactamente en el mismo
    rectángulo en ambos casos, así que la geometría de drawbox/drawtext
    (bar_height, y1/y2, etc.) no cambia entre uno y otro.

    layout_streaming (hecho TÉCNICO del canal, no editorial — no viene de
    Agent 3 sino de la config del canal): dict opcional con
    facecam_rect/contenido_rect para armar Layout C (split-screen, ver
    _build_vf_splitscreen). Si está presente, tiene prioridad sobre
    has_letterbox/layout — el split-screen ya resuelve el encuadre
    vertical por su cuenta, así que el texto se posiciona igual que en
    Caso B (el resultado del stack siempre es 1080x1920 exacto).

    layout="imagen" (Fase 13, solo importa si has_letterbox): video arriba
    + imagen de relleno separada abajo (ver _build_vf_imagen). Requiere
    imagen_relleno_path resuelto (Agent 4 ya eligió el archivo vía
    _pick_imagen_relleno) y source_width/source_height de la fuente — si
    falta cualquiera de los dos, cae a pillarbox sin avisar (misma
    degradación silenciosa que música/marca de agua sin asset).

    Retorna (filtro_vf, params_debug). Cuando se usa layout="imagen",
    params trae "imagen_activa": True — el llamador (_cut_clip) debe
    agregar imagen_relleno_path a extra_inputs en ese caso (índice [1:v]).
    """
    facecam_rect     = (layout_streaming or {}).get("facecam_rect")
    contenido_rect   = (layout_streaming or {}).get("contenido_rect")
    usa_splitscreen  = bool(facecam_rect and contenido_rect)
    if usa_splitscreen:
        has_letterbox = False   # el split-screen ya resuelve el encuadre

    usa_imagen = (
        not usa_splitscreen and has_letterbox and layout == "imagen"
        and imagen_relleno_path is not None and source_width and source_height
    )
    usa_crop = (
        not usa_splitscreen and not usa_imagen and has_letterbox and layout == "crop"
        and source_width and source_height
    )
    if usa_crop:
        has_letterbox = False   # el crop-to-fill ya resuelve el encuadre, texto como Caso B

    mostrar_texto = estilo_texto != "sin_texto"
    safe1    = _sanitize_text(linea1) if linea1 and mostrar_texto else ""
    safe2    = _sanitize_text(linea2) if linea2 and mostrar_texto else ""
    font_opt = f"fontfile={font_rel}:" if font_rel else ""

    duracion_texto = None
    enable_clause  = ""
    if estilo_texto == "fijo_inicial" and (safe1 or safe2):
        duracion_texto = _text_display_duration(safe1, safe2)
        enable_clause  = f":enable=lte(t\\,{duracion_texto:.1f})"

    imagen_params: dict = {}
    if usa_splitscreen:
        base = _build_vf_splitscreen(
            facecam_rect, contenido_rect, (layout_streaming or {}).get("overlays_ocultar"),
        )
    elif usa_imagen:
        base, imagen_params = _build_vf_imagen(source_width, source_height)
    elif usa_crop:
        base = _build_vf_crop(source_width, source_height)
    elif has_letterbox and layout == "blur":
        # Fondo con el video difuminado (split en dos ramas: una de fondo
        # recortada+blureada llenando 1080x1920, otra de primer plano
        # ajustada sin recortar, superpuesta centrada) en vez de barras
        # negras sólidas. El primer plano ocupa el MISMO rectángulo final
        # que en pillarbox (misma lógica scale=decrease), por eso la
        # geometría de texto de abajo no necesita distinguir entre ambos.
        base = (
            "split=2[_bgblur][_fgblur];"
            "[_bgblur]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,gblur=sigma=20[_bgblur2];"
            "[_fgblur]scale=1080:1920:force_original_aspect_ratio=decrease[_fgblur2];"
            "[_bgblur2][_fgblur2]overlay=(W-w)/2:(H-h)/2"
        )
    else:
        base = (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        )
    filters = [base]
    params  = {}

    if usa_imagen:
        # ── Caso IMG: texto anclado en el límite video/imagen, solapando
        # un poco el video (overlap) — el grueso de la caja cae en la
        # imagen de relleno. Mismo patrón de fuentes que Caso A, tamaños
        # más chicos porque el bloque de video acá es más angosto.
        pad = 20
        overlap = 40
        seam_y = imagen_params["seam_y"]

        if safe1 and safe2:
            fs1 = _pick_fontsize(safe1, [48, 40, 34], 900)
            fs2 = _pick_fontsize(safe2, [40, 34, 28], 900)
            lh1, lh2 = int(fs1 * 1.2), int(fs2 * 1.2)
            gap = 14

            y_box = seam_y - overlap
            y1    = y_box + pad
            y2    = y1 + lh1 + gap

            est_w = max(
                int(len(safe1) * fs1 * _CHAR_WIDTH_FACTOR),
                int(len(safe2) * fs2 * _CHAR_WIDTH_FACTOR),
            )
            box_w = min(1060, est_w + 2 * pad)
            box_h = lh1 + gap + lh2 + 2 * pad
            box_x = (1080 - box_w) // 2

            params = {"caso": "IMG", "fs1": fs1, "fs2": fs2, "y1": y1, "y2": y2,
                      "y_box": y_box, "box_w": box_w, "box_h": box_h, **imagen_params}

            filters.append(f"drawbox=x={box_x}:y={y_box}:w={box_w}:h={box_h}:color=white:t=fill{enable_clause}")
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe1}':"
                f"fontsize={fs1}:fontcolor=black:x=(w-text_w)/2:y={y1}{enable_clause}"
            )
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe2}':"
                f"fontsize={fs2}:fontcolor=black:x=(w-text_w)/2:y={y2}{enable_clause}"
            )

        elif safe1 or safe2:
            text = safe1 if safe1 else safe2
            fs   = _pick_fontsize(text, [48, 40, 34], 900)
            lh   = int(fs * 1.2)

            y_box = seam_y - overlap
            y_text = y_box + pad
            est_w  = int(len(text) * fs * _CHAR_WIDTH_FACTOR)
            box_w  = min(1060, est_w + 2 * pad)
            box_h  = lh + 2 * pad
            box_x  = (1080 - box_w) // 2

            params = {"caso": "IMG1", "fs": fs, "y_text": y_text, "y_box": y_box,
                      "box_w": box_w, "box_h": box_h, **imagen_params}

            filters.append(f"drawbox=x={box_x}:y={y_box}:w={box_w}:h={box_h}:color=white:t=fill{enable_clause}")
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{text}':"
                f"fontsize={fs}:fontcolor=black:x=(w-text_w)/2:y={y_text}{enable_clause}"
            )
        else:
            params = {"caso": "IMG0", **imagen_params}

        params["imagen_activa"] = True

    elif has_letterbox:
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

            filters.append(f"drawbox=x={box_x}:y={y_box}:w={box_w}:h={box_h}:color=white:t=fill{enable_clause}")
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe1}':"
                f"fontsize={fs1}:fontcolor=black:x=(w-text_w)/2:y={y1}{enable_clause}"
            )
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe2}':"
                f"fontsize={fs2}:fontcolor=black:x=(w-text_w)/2:y={y2}{enable_clause}"
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

            filters.append(f"drawbox=x={box_x}:y={y_box}:w={box_w}:h={box_h}:color=white:t=fill{enable_clause}")
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{text}':"
                f"fontsize={fs}:fontcolor=black:x=(w-text_w)/2:y={y_text}{enable_clause}"
            )

        else:
            # ── Sin texto ────────────────────────────────────────────
            params = {"caso": "A0", "bar_height": bar_height}

    else:
        # Caso B: centrado, semitransparente — visible todo el clip salvo
        # que estilo_texto sea "fijo_inicial" (ver enable_clause arriba).
        # usa_crop también cae acá (mismo comportamiento de texto), pero se
        # marca aparte para que _cut_clip distinga el print de debug.
        params = {"caso": "B"}
        if usa_crop:
            params["crop_activo"] = True

        if safe1:
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe1}':"
                "fontsize=52:fontcolor=black:"
                f"x=(w-text_w)/2:y=200{enable_clause}:"
                "box=1:boxcolor=white@0.85:boxborderw=12"
            )
        if safe2:
            filters.append(
                f"drawtext={font_opt}expansion=none:text='{safe2}':"
                "fontsize=40:fontcolor=black:"
                f"x=(w-text_w)/2:y=275{enable_clause}:"
                "box=1:boxcolor=white@0.85:boxborderw=10"
            )

    if duracion_texto is not None:
        params["duracion_texto_seg"] = duracion_texto

    safe_cta = _sanitize_text(cta_texto) if cta_texto else ""
    if safe_cta:
        _cta_margen_seg = 3.0
        cta_desde = max(0.0, duracion_clip - _cta_margen_seg) if duracion_clip else 0.0
        filters.append(
            f"drawtext={font_opt}expansion=none:text='{safe_cta}':"
            "fontsize=44:fontcolor=black:"
            f"x=(w-text_w)/2:y=1780:enable=gte(t\\,{cta_desde:.1f}):"
            "box=1:boxcolor=white@0.85:boxborderw=12"
        )
        params["cta_desde_seg"] = cta_desde

    if has_letterbox:
        params["layout"] = layout
    if usa_splitscreen:
        params["splitscreen"] = True

    return ",".join(filters), params


def _load_word_timings(session_dir: Path, inicio_s: float, fin_s: float) -> list[dict]:
    """
    Lee palabras.json (si existe — ver transcripcion/video_transcriber.py)
    y filtra al rango [inicio_s, fin_s), con timestamps ajustados a
    relativos-al-clip (restando inicio_s).

    Retorna [] si no hay datos (sesión vieja, o transcripción por Colab que
    no devolvió alineación por palabra) — el llamador debe caer a la ruta
    estática de subtítulos, nunca fallar el corte por esto.
    """
    palabras_path = session_dir / "palabras.json"
    if not palabras_path.exists():
        return []
    try:
        data = json.loads(palabras_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    out = []
    for w in data:
        start = w.get("start")
        if start is None or not (inicio_s <= start < fin_s):
            continue
        rel_start = start - inicio_s
        rel_end   = max(rel_start + 0.05, w.get("end", start) - inicio_s)
        out.append({"word": w.get("word", ""), "start": rel_start, "end": rel_end})
    return out


def _build_vf_animated(
    words: list[dict], font_rel: str, palabras_clave: list[str] | None = None,
) -> str | None:
    """
    Subtítulos animados palabra por palabra: una palabra visible a la vez,
    centrada, cada una con su propia ventana de tiempo (mutuamente
    excluyentes) según los timestamps reales de WhisperX en palabras.json.

    Empieza simple a propósito (una palabra a la vez, no frase completa con
    la palabra actual resaltada) — es la forma de filtro más robusta, menos
    propensa a romperse por un filter_complex gigante.

    palabras_clave (opcional, editorial — decidido por Agent 3): palabras
    que se muestran en rojo en vez de negro para dar énfasis visual. El
    match es insensible a mayúsculas/acentos simples (comparación tal cual
    llega, sin stemming).

    Retorna None si ninguna palabra sobrevivió el saneo (texto vacío tras
    _sanitize_text) — el llamador debe caer a la ruta estática.
    """
    font_opt  = f"fontfile={font_rel}:" if font_rel else ""
    clave_set = {p.strip().lower() for p in (palabras_clave or []) if p.strip()}
    base = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    )
    filters = [base]
    alguna  = False

    for w in words:
        text = _sanitize_text(w["word"])
        if not text or w["end"] <= w["start"]:
            continue
        fs    = _pick_fontsize(text, [72, 64, 56, 48], 900)
        color = "red" if text.strip().lower() in clave_set else "black"
        filters.append(
            f"drawtext={font_opt}expansion=none:text='{text}':"
            f"fontsize={fs}:fontcolor={color}:"
            "x=(w-text_w)/2:y=(h-text_h)/2:"
            f"enable=between(t\\,{w['start']:.3f}\\,{w['end']:.3f}):"
            "box=1:boxcolor=white@0.85:boxborderw=14"
        )
        alguna = True

    return ",".join(filters) if alguna else None


_ZOOM_FACTOR      = 1.15   # 15% de acercamiento en el pico
_ZOOM_RAMPA_SEG   = 1.0    # segundos de transición in/out
_ZOOM_VENTANA_SEG = 3.0    # segundos que se sostiene el acercamiento


def _build_vf_zoom(
    momento_enfasis_seg: float | None, width: int, height: int,
    ventana: float = _ZOOM_VENTANA_SEG,
) -> str | None:
    """
    Filtro de zoom/punch-in centrado alrededor de un instante de énfasis
    (ver agentes/agent2_range_refiner.py: momento_enfasis_seg — el timestamp
    del pico original de Agente 1, relativo al inicio del rango ya recortado).

    Es un punch-in genérico, no dirigido a un sujeto: los agentes de este
    pipeline son 100% texto/transcripción, nunca ven el frame, así que no
    hay forma de saber DÓNDE en el encuadre está lo relevante — solo CUÁNDO.

    Implementación: escalar el frame hacia arriba/abajo según el factor de
    zoom (con eval=frame, para que FFmpeg reevalúe la expresión en cada
    frame) y luego recortar siempre al tamaño FIJO original (width, height).
    Esto es necesario porque el filtro `crop` con w/h dinámicos en función
    de `t` puede achicar el cuadro pero luego no lo vuelve a agrandar (el
    tamaño de salida del link queda pegado al mínimo visto) — probado
    empíricamente. Al mantener el crop final en un tamaño constante, el
    "achicar/agrandar" ocurre en el `scale` de entrada, que si soporta
    reevaluación por frame en ambos sentidos.

    Rampa en/fuera de _ZOOM_RAMPA_SEG segundos, sostiene _ZOOM_FACTOR
    durante `ventana` segundos centrados en momento_enfasis_seg. Se aplica
    sobre el frame fuente ANTES del scale/pad a 9:16.

    Retorna None si no hay momento de énfasis (sesiones viejas, o el rango
    no tiene un pico asociado) — el llamador no debe forzar zoom sin este dato.
    """
    if momento_enfasis_seg is None or not width or not height:
        return None

    pre        = max(0.0, momento_enfasis_seg - ventana / 2 - _ZOOM_RAMPA_SEG)
    peak_start = pre + _ZOOM_RAMPA_SEG
    peak_end   = peak_start + ventana
    post       = peak_end + _ZOOM_RAMPA_SEG
    delta      = _ZOOM_FACTOR - 1.0

    zf = (
        f"if(lt(t\\,{pre:.2f})\\,1.0\\,"
        f"if(lt(t\\,{peak_start:.2f})\\,1.0+{delta:.3f}*(t-{pre:.2f})/{_ZOOM_RAMPA_SEG:.2f}\\,"
        f"if(lt(t\\,{peak_end:.2f})\\,{_ZOOM_FACTOR:.3f}\\,"
        f"if(lt(t\\,{post:.2f})\\,{_ZOOM_FACTOR:.3f}-{delta:.3f}*(t-{peak_end:.2f})/{_ZOOM_RAMPA_SEG:.2f}\\,1.0))))"
    )

    return (
        f"scale=w=trunc(iw*({zf})/2)*2:h=trunc(ih*({zf})/2)*2:eval=frame,"
        f"crop=w={width}:h={height}:x=(iw-{width})/2:y=(ih-{height})/2"
    )


_MARCA_AGUA_PATH  = Path(__file__).parent / "assets" / "marca_agua.png"
_MARCA_AGUA_ANCHO = 150   # px, en el cuadro final 1080x1920


def _con_marca_agua(filtro: str, start_index: int = 1) -> tuple[str, list[Path]]:
    """
    Superpone edicion_video/assets/marca_agua.png (si existe) en la esquina
    inferior derecha del cuadro final. Reutiliza el mecanismo de
    `extra_inputs` de _ffmpeg_cmd (mismo patrón de índice secuencial que ya
    usa el input de música). No falla el clip si el archivo no existe —
    simplemente no hay marca de agua (asset pendiente de curar).

    start_index: índice del primer extra_input LIBRE al llegar acá — por
    default 1 (nadie más pidió uno antes), pero si layout="imagen" ya
    ocupó el índice 1 (ver _build_vf_imagen), el llamador debe pasar 2.
    """
    if not _MARCA_AGUA_PATH.exists():
        return filtro, []
    return (
        f"{filtro}[__premark];"
        f"[{start_index}:v]scale={_MARCA_AGUA_ANCHO}:-1[__wm];"
        f"[__premark][__wm]overlay=W-w-30:H-h-30"
    ), [_MARCA_AGUA_PATH]


def _cut_clip(
    video_path: Path, inicio: str, fin: str,
    linea1: str, linea2: str,
    output_path: Path, font_rel: str,
    has_letterbox: bool, bar_height: int,
    session_dir: Path | None = None,
    mood: str = "neutral",
    estilo_texto: str = "fijo",
    momento_enfasis_seg: float | None = None,
    source_width: int = 0,
    source_height: int = 0,
    cta_texto: str = "",
    palabras_clave: list[str] | None = None,
    layout: str = "pillarbox",
    layout_streaming: dict | None = None,
    efecto_sonido: str | None = None,
) -> bool:
    """
    Corta [inicio, fin] del video y ejecuta el estilo_texto pedido (decidido
    río arriba, no acá — ver _build_vf): "sin_texto" | "fijo" | "fijo_inicial"
    | "dinamico" | "dinamico_con_titulo". Ambos modos "dinamico*" requieren
    palabras.json en session_dir (ver transcripcion/video_transcriber.py);
    si no hay datos de palabra, caen a "fijo" como respaldo estático — nunca
    se pierde el clip por esto. "dinamico_con_titulo" combina el hook fijo
    (arriba/barra) con los subtítulos animados (centro) en el mismo render.

    Si hay una pista en edicion_video/assets/musica/<mood>/ (ver
    _pick_music_track), se mezcla de fondo a bajo volumen sin importar el
    estilo de texto ni si el intento primario rindió bien.

    Si efecto_sonido está presente Y momento_enfasis_seg también (Fase 15),
    se mezcla un efecto corto (ver _pick_sound_effect) anclado a ese
    instante vía adelay — sin momento_enfasis_seg conocido, se omite en vez
    de sonar en un punto arbitrario.
    """
    inicio   = _normalize_timestamp(inicio)
    fin      = _normalize_timestamp(fin)
    duracion = _timestamp_to_seconds(fin) - _timestamp_to_seconds(inicio)

    attempts    = []
    vf_animado  = None
    usa_animado = estilo_texto in ("dinamico", "dinamico_con_titulo")

    if usa_animado and session_dir is not None:
        inicio_s   = _timestamp_to_seconds(inicio)
        words      = _load_word_timings(session_dir, inicio_s, inicio_s + duracion)
        vf_animado = _build_vf_animated(words, font_rel, palabras_clave) if words else None

    # "dinamico_con_titulo" siempre muestra el hook completo (el respaldo
    # y el modo "con título" son el mismo caso estático: "fijo"). "dinamico"
    # sin datos de palabra también cae a "fijo" — nunca se infiere de
    # has_letterbox.
    if estilo_texto == "dinamico_con_titulo" or (estilo_texto == "dinamico" and not vf_animado):
        estilo_estatico = "fijo"
    else:
        estilo_estatico = estilo_texto
    imagen_relleno_path = _pick_imagen_relleno(mood) if layout == "imagen" else None
    vf, params = _build_vf(
        linea1, linea2, font_rel, has_letterbox, bar_height, estilo_estatico,
        cta_texto=cta_texto, duracion_clip=duracion, layout=layout,
        layout_streaming=layout_streaming,
        source_width=source_width, source_height=source_height,
        imagen_relleno_path=imagen_relleno_path,
    )
    imagen_extra_inputs = [imagen_relleno_path] if params.get("imagen_activa") else []

    print(f"         Estilo  : {estilo_texto}" + (
        " → sin datos de palabra, respaldo 'fijo'" if (usa_animado and not vf_animado) else ""
    ))

    # Imprimir coordenadas para verificación visual
    if params.get("caso") == "A":
        lh1 = params["lh1"]
        lh2 = params["lh2"]
        y2  = params["y2"]
        bh  = params["bar_height"]
        print(f"         Layout  : Caso A — letterbox ({params.get('layout', 'pillarbox')})  |  barra {bh}px")
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
    elif params.get("crop_activo"):
        print(f"         Layout  : Caso CROP — recorte centrado 9:16 (sin relleno)")
    elif params.get("caso") == "B" and "duracion_texto_seg" in params:
        print(f"         Layout  : Caso B — vertical nativo")
        print(f"         Texto visible : {params['duracion_texto_seg']:.1f}s (según velocidad de lectura)")
    elif params.get("imagen_activa"):
        print(f"         Layout  : Caso IMG — video+imagen de relleno  |  video={params['video_h']}px  imagen={params['imagen_h']}px")
        print(f"         Franjas : arriba={params['barra_arriba']}px  abajo={params['barra_abajo']}px  (límite en y={params['seam_y']}px)")
    if params.get("splitscreen"):
        print(f"         Layout  : Caso C — split-screen (facecam {_FACECAM_ALTO_PCT:.0%} / contenido {1 - _FACECAM_ALTO_PCT:.0%})")

    zoom_filter = _build_vf_zoom(momento_enfasis_seg, source_width, source_height)
    if zoom_filter:
        print(f"         Zoom    : punch-in en t={momento_enfasis_seg:.1f}s (±{_ZOOM_VENTANA_SEG:.0f}s)")

    def _con_zoom(filtro: str) -> str:
        return f"{zoom_filter},{filtro}" if zoom_filter else filtro

    musica_path = _pick_music_track(mood)
    if musica_path:
        print(f"         Música  : mood='{mood}' → {musica_path.name}")

    efecto_path = (
        _pick_sound_effect(efecto_sonido)
        if efecto_sonido and momento_enfasis_seg is not None else None
    )
    if efecto_sonido and momento_enfasis_seg is None:
        print(f"         Efecto  : '{efecto_sonido}' pedido pero sin momento_enfasis_seg → omitido")
    elif efecto_sonido and not efecto_path:
        print(f"         Efecto  : tipo='{efecto_sonido}' sin assets en {_EFECTOS_SONIDO_DIR} → omitido")
    elif efecto_path:
        print(f"         Efecto  : tipo='{efecto_sonido}' → {efecto_path.name}  (en t={momento_enfasis_seg:.1f}s)")

    if layout == "imagen" and not imagen_relleno_path:
        print(f"         Imagen  : layout='imagen' pedido pero sin assets en {_IMAGENES_RELLENO_DIR} → respaldo pillarbox")
    elif imagen_relleno_path:
        print(f"         Imagen  : mood='{mood}' → {imagen_relleno_path.name}")

    def _ffmpeg_cmd(filter_complex_video: str, extra_inputs: list[Path]) -> list[str]:
        """
        Arma el comando ffmpeg completo a partir de un filtro de video ya
        armado (debe terminar en [outv]): agrega los inputs de imagen que
        ese filtro referencia, mezcla música de fondo y/o efecto de sonido
        si hay alguno elegido (N pistas de audio en vez de máximo 2), y
        arma el mapeo final de video+audio.
        """
        inputs = ["-ss", inicio, "-i", str(video_path)]
        for p in extra_inputs:
            inputs += ["-i", str(p)]

        fc       = filter_complex_video
        map_args = ["-map", "[outv]"]

        audio_labels = ["0:a"]
        next_idx     = 1 + len(extra_inputs)

        if musica_path:
            inputs += ["-stream_loop", "-1", "-i", str(musica_path)]
            fc += f";[{next_idx}:a]volume={_MUSICA_VOLUMEN}[music_low]"
            audio_labels.append("music_low")
            next_idx += 1

        if efecto_path:
            delay_ms = int(momento_enfasis_seg * 1000)
            inputs += ["-i", str(efecto_path)]
            fc += f";[{next_idx}:a]adelay={delay_ms}:all=1,volume={_EFECTO_VOLUMEN}[sfx]"
            audio_labels.append("sfx")
            next_idx += 1

        if len(audio_labels) > 1:
            joined = "".join(f"[{l}]" for l in audio_labels)
            fc += f";{joined}amix=inputs={len(audio_labels)}:duration=first:dropout_transition=0:normalize=0[outa]"
            map_args += ["-map", "[outa]"]
        else:
            map_args += ["-map", "0:a"]

        return [
            "ffmpeg", *inputs,
            "-t", str(duracion), "-v", "error",
            "-filter_complex", fc,
            *map_args,
            "-c:v", "libx264", "-c:a", "aac", "-y",
            str(output_path),
        ]

    if _MARCA_AGUA_PATH.exists():
        print(f"         Marca   : {_MARCA_AGUA_PATH.name}")

    def _armar_intento(filtro: str, incluir_imagen: bool = True) -> list[str]:
        # imagen_extra_inputs (Fase 13) ocupa el índice [1:v] si está activo
        # y este intento realmente lo referencia (vf lo incluye; vf_animado
        # solo, sin título, no) — la marca de agua toma el siguiente índice
        # libre, cualquiera sea.
        extra_previos = imagen_extra_inputs if incluir_imagen else []
        filtro_marca, extras_marca = _con_marca_agua(filtro, start_index=1 + len(extra_previos))
        return _ffmpeg_cmd(f"[0:v]{filtro_marca}[outv]", extra_previos + extras_marca)

    if vf_animado and estilo_texto == "dinamico_con_titulo":
        print(f"         Subtítulos: animados + título fijo ({len(words)} palabras)")
        combinado = f"{vf},{vf_animado}"
        attempts.append(("animado", _armar_intento(_con_zoom(combinado), incluir_imagen=True)))
    elif vf_animado:
        print(f"         Subtítulos: animados por palabra ({len(words)} palabras)")
        attempts.append(("animado", _armar_intento(_con_zoom(vf_animado), incluir_imagen=False)))

    label_estatico = "sin texto" if estilo_estatico == "sin_texto" else "con subtítulo"
    attempts.append((label_estatico, _armar_intento(_con_zoom(vf), incluir_imagen=True)))

    attempts.append(("sin subtítulo", _ffmpeg_cmd(
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2[outv]",
        [],
    )))

    for label, cmd in attempts:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode == 0:
            if label == "sin subtítulo" and len(attempts) > 1:
                print(f"  ⚠️  Subtítulo falló — clip guardado sin texto")
            elif label in ("con subtítulo", "sin texto") and attempts[0][0] == "animado":
                print(f"  ⚠️  Subtítulo animado falló — clip guardado con texto estático")
            return True
        if label != "sin subtítulo":
            print(f"  ⚠️  {label.capitalize()} falló ({result.stderr.split(chr(10))[-2][:80]}), reintentando...")

    print(f"  ❌ FFmpeg error:\n{result.stderr[-600:]}")
    return False


def _cut_compilation(
    video_path: Path, segmentos: list[dict],
    linea1: str, linea2: str,
    output_path: Path, font_rel: str,
    has_letterbox: bool, bar_height: int,
    session_dir: Path | None = None,
    mood: str = "neutral",
    estilo_texto: str = "fijo",
    source_width: int = 0,
    source_height: int = 0,
    cta_texto: str = "",
    palabras_clave: list[str] | None = None,
    layout: str = "pillarbox",
    layout_streaming: dict | None = None,
) -> bool:
    """
    MOTOR de compilación multi-segmento (Fase 11, solo el lado de Agente 4
    — Agente 2/3 todavía no producen `segmentos`, esto se verificó con un
    contenido.json sintético). Corta N segmentos DISJUNTOS por separado
    (reutilizando _cut_clip para cada uno — misma resolución 1080x1920
    garantizada en todos) y los concatena con el demuxer `concat` de
    FFmpeg (`-c copy`, sin recodificar, porque todos los segmentos ya
    comparten el mismo códec/parámetros de salida de _cut_clip).

    Contrato esperado de `segmentos`: lista de dicts con al menos
    {"inicio", "fin"} en el mismo formato de timestamp que rango_original.

    El hook (linea1/linea2) se quema SOLO en el primer segmento, como
    título de apertura de la compilación — el resto sale sin ese texto.
    El CTA (si hay) se quema solo en el ÚLTIMO segmento. MVP sin stinger
    de transición entre cortes (corte duro) — pendiente si hace falta.

    Retorna False si algún segmento falla en cortarse o si la
    concatenación falla — nunca publica una compilación a medias.
    """
    if not segmentos:
        print("  ❌ Compilación sin segmentos — nada que cortar")
        return False

    tmp_dir = output_path.parent / f"_tmp_{output_path.stem}"
    tmp_dir.mkdir(exist_ok=True)
    tmp_paths: list[Path] = []

    try:
        for i, seg in enumerate(segmentos):
            seg_path   = tmp_dir / f"seg_{i:02d}.mp4"
            es_primero = i == 0
            es_ultimo  = i == len(segmentos) - 1
            print(f"         Segmento {i + 1}/{len(segmentos)} : {seg.get('inicio')} → {seg.get('fin')}")

            ok = _cut_clip(
                video_path, seg["inicio"], seg["fin"],
                linea1 if es_primero else "", linea2 if es_primero else "",
                seg_path, font_rel, has_letterbox, bar_height,
                session_dir=session_dir, mood=mood,
                estilo_texto=(estilo_texto if es_primero else "sin_texto"),
                source_width=source_width, source_height=source_height,
                cta_texto=(cta_texto if es_ultimo else ""),
                palabras_clave=(palabras_clave if es_primero else None),
                layout=layout, layout_streaming=layout_streaming,
            )
            if not ok:
                print(f"  ❌ Falló el segmento {i + 1}/{len(segmentos)} de la compilación")
                return False
            tmp_paths.append(seg_path)

        lista_path = tmp_dir / "lista.txt"
        lista_path.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in tmp_paths),
            encoding="utf-8",
        )
        result = subprocess.run(
            ["ffmpeg", "-f", "concat", "-safe", "0", "-i", str(lista_path),
             "-c", "copy", "-v", "error", "-y", str(output_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            print(f"  ❌ FFmpeg error al concatenar:\n{result.stderr[-600:]}")
            return False
        return True
    finally:
        for p in tmp_paths:
            p.unlink(missing_ok=True)
        (tmp_dir / "lista.txt").unlink(missing_ok=True)
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


def run_agent(
    contenido_path: str,
    video_path_override: Path | None = None,
    clips_dir_override:  Path | None = None,
    clip_offset: int = 0,
    clip_prefix: str | None = None,
) -> list[dict]:
    """
    video_path_override — usar este video en lugar de buscarlo en session_dir
    clips_dir_override  — guardar clips aquí en lugar de session_dir/clips/
    clip_offset         — continuar numeración desde este índice (clip_{offset+1:03d})
    clip_prefix         — si se da, nombra {prefix}_01, {prefix}_02... (ignora clip_offset);
                          el pipeline lo usa por chunk — ver core/clip_ids.py
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
        mood     = item.get("mood",                "neutral")
        estilo_texto = item.get("estilo_texto",    "fijo")
        momento_enfasis = rango.get("momento_enfasis_seg")
        cta_texto      = item.get("cta_texto",     "")
        palabras_clave = item.get("palabras_clave", [])
        layout         = item.get("layout",        "pillarbox")
        layout_streaming = item.get("layout_streaming")
        efecto_sonido  = item.get("efecto_sonido")
        segmentos      = item.get("segmentos")

        clip_id   = f"{clip_prefix}_{i + 1:02d}" if clip_prefix else f"clip_{i + 1 + clip_offset:03d}"
        clip_name = f"{clip_id}.mp4"
        meta_name = f"{clip_id}.json"
        clip_path = clips_dir / clip_name
        meta_path = clips_dir / meta_name

        print(f"[AGENT4] Clip {i + 1}/{len(a_publicar)}  →  {clip_name}")
        if segmentos:
            duracion = item.get("duracion_total") or sum(
                _timestamp_to_seconds(s["fin"]) - _timestamp_to_seconds(s["inicio"]) for s in segmentos
            )
            print(f"         Compilación : {len(segmentos)} segmentos  ({duracion}s total)")
        else:
            print(f"         Rango   : {inicio} → {fin}  ({duracion}s)")
        print(f"         Línea 1 : {linea1}")
        print(f"         Línea 2 : {linea2}")
        print(f"         Texto   : '{_sanitize_text(linea1)}' / '{_sanitize_text(linea2)}'  (sanitizado)")

        if segmentos:
            ok = _cut_compilation(
                video_path, segmentos, linea1, linea2, clip_path, font_rel, has_lb, bar_h,
                session_dir=session_dir, mood=mood, estilo_texto=estilo_texto,
                source_width=vid_info["width"], source_height=vid_info["height"],
                cta_texto=cta_texto, palabras_clave=palabras_clave,
                layout=layout, layout_streaming=layout_streaming,
            )
        else:
            ok = _cut_clip(
                video_path, inicio, fin, linea1, linea2, clip_path, font_rel, has_lb, bar_h,
                session_dir=session_dir, mood=mood, estilo_texto=estilo_texto,
                momento_enfasis_seg=momento_enfasis,
                source_width=vid_info["width"], source_height=vid_info["height"],
                cta_texto=cta_texto, palabras_clave=palabras_clave,
                layout=layout, layout_streaming=layout_streaming,
                efecto_sonido=efecto_sonido,
            )

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
        resultados.append({"ok": ok, "meta": meta, "path": str(clip_path), "clip_id": clip_id})

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
