"""
===========================================
  IDEA MILLONARIA — Pipeline v2.0
  Orquestador: Captura + ConfigLoader + 4 Agentes
===========================================

Uso:
  python pipeline.py --live  https://tiktok.com/@usuario/live  [--config papi_jhos]
  python pipeline.py --video https://tiktok.com/@usuario/live  [--config canal_id]
  python pipeline.py --test  stream_data/test/                 [--config papi_jhos]

  --config omitido → usa config/default.yaml
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

try:
    import yaml
except ImportError:
    import subprocess as _sp, sys as _sys
    _sp.run([_sys.executable, "-m", "pip", "install", "pyyaml"], check=True)
    import yaml

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from contexto.config_loader  import ConfigLoader
from contexto.context_loader import ContextLoader
from agentes.agent1_peak_detector import run_agent as agent1
from agentes.agent2_range_refiner  import run_agent as agent2
from agentes.agent3_viral_scorer   import run_agent as agent3
from edicion_video.agent4_video_cutter   import run_agent as agent4
from agentes.agent0_speaker_identifier import identify_speakers as agent0

STREAM_DATA = Path("stream_data")

_BASE_DIR = Path(__file__).parent


def _load_config(canal_id: str | None, base_dir: Path | None = None):
    """
    Selecciona automáticamente el loader correcto:
      - Si existe contexto/nichos/{canal_id}.yaml → ContextLoader (v2)
      - Sino → ConfigLoader (v1, fallback)

    Retorna (config_dict, loader_instance).
    El loader es compatible en API: .get(), .loaded_file, .get_ecosystem_type(),
    .enrich_with_speakers().
    """
    bd    = base_dir or _BASE_DIR
    canal = canal_id or "default"

    contexto_nicho = bd / "contexto" / "nichos" / f"{canal}.yaml"
    if contexto_nicho.exists():
        ctx    = ContextLoader(contexto_dir=str(bd / "contexto"))
        config = ctx.load_nicho(canal)
        print(f"[CONFIG] Módulo Contexto v2 → {canal}")
        return config, ctx
    else:
        cfg    = ConfigLoader(config_dir=str(bd / "config"))
        config = cfg.load(canal_id)
        print(f"[CONFIG] ConfigLoader v1 → {canal} (fallback)")
        return config, cfg


# ─────────────────────────────────────────
#  MODO --REVISAR
# ─────────────────────────────────────────

def _guardar_evento_correccion(clip: dict, l1_nuevo: str, l2_nuevo: str,
                                inicio_nuevo: str, fin_nuevo: str,
                                session_dir: Path, config: dict) -> None:
    """Guarda la corrección de título y/o rango como evento en el Módulo Contexto."""
    l1_original     = clip.get("texto_linea1", "")
    l2_original     = clip.get("texto_linea2", "")
    rango_original  = clip.get("rango_original", {})
    inicio_original = rango_original.get("inicio", "")
    fin_original    = rango_original.get("fin", "")

    cambio_titulo = (l1_nuevo != l1_original or l2_nuevo != l2_original)
    cambio_rango  = (inicio_nuevo != inicio_original or fin_nuevo != fin_original)

    if not cambio_titulo and not cambio_rango:
        return

    nicho_id = (config.get("meta") or {}).get("id", "default")
    fecha    = datetime.now().strftime("%Y-%m-%d")

    aprendizajes = []
    if cambio_titulo:
        aprendizajes.append(
            f"El sistema propuso el título '{l1_original} / {l2_original}' "
            f"pero el editor corrigió a '{l1_nuevo} / {l2_nuevo}'"
        )
    if cambio_rango:
        aprendizajes.append(
            f"El sistema propuso el rango {inicio_original}→{fin_original} "
            f"pero el editor corrigió a {inicio_nuevo}→{fin_nuevo}"
        )

    if cambio_titulo and cambio_rango:
        tipo = "correccion_titulo_y_rango"
    elif cambio_rango:
        tipo = "correccion_rango"
    else:
        tipo = "correccion_titulo"

    evento = {
        "evento": {
            "tipo": tipo,
            "fecha": fecha,
            "nicho": nicho_id,
            "titulo_original":  {"linea1": l1_original, "linea2": l2_original},
            "titulo_corregido": {"linea1": l1_nuevo,    "linea2": l2_nuevo},
            "rango_original":   {"inicio": inicio_original, "fin": fin_original},
            "rango_corregido":  {"inicio": inicio_nuevo,    "fin": fin_nuevo},
            "rango":            rango_original,
            "aprendizaje": " | ".join(aprendizajes),
        }
    }

    eventos_dir = _BASE_DIR / "contexto" / "eventos" / datetime.now().strftime("%Y-%m")
    eventos_dir.mkdir(parents=True, exist_ok=True)

    ts   = datetime.now().strftime("%H%M%S")
    path = eventos_dir / f"correccion_{nicho_id}_{ts}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(evento, f, allow_unicode=True, default_flow_style=False)


def _guardar_evento_descarte(clip: dict, razon: str,
                              session_dir: Path, config: dict) -> None:
    """Guarda el descarte manual como evento en el Módulo Contexto."""
    nicho_id = (config.get("meta") or {}).get("id", "default")
    fecha    = datetime.now().strftime("%Y-%m-%d")

    evento = {
        "evento": {
            "tipo": "descarte_manual",
            "fecha": fecha,
            "nicho": nicho_id,
            "clip_descartado": {
                "linea1": clip.get("texto_linea1", ""),
                "linea2": clip.get("texto_linea2", ""),
                "score":  clip.get("score", 0),
            },
            "razon_descarte": razon,
            "rango":          clip.get("rango_original", {}),
            "aprendizaje": (
                f"Score {clip.get('score', 0)} pero editor descartó — {razon}"
            ),
        }
    }

    eventos_dir = _BASE_DIR / "contexto" / "eventos" / datetime.now().strftime("%Y-%m")
    eventos_dir.mkdir(parents=True, exist_ok=True)

    ts   = datetime.now().strftime("%H%M%S")
    path = eventos_dir / f"descarte_{nicho_id}_{ts}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(evento, f, allow_unicode=True, default_flow_style=False)


def _revisar_clips(contenido: list[dict], session_dir: Path,
                   config: dict, loader) -> list[dict]:
    """
    Modo interactivo: muestra cada clip candidato y pide aprobación antes de cortar.
    Retorna lista de clips aprobados (con posibles ediciones de texto).
    Las correcciones y descartes se guardan como eventos en el Módulo Contexto.
    """
    clips_aprobados = []
    candidatos = [(i, c) for i, c in enumerate(contenido) if c.get("publicar")]

    if not candidatos:
        print("[REVISAR] Sin clips candidatos para revisar.")
        return []

    print(f"\n[REVISAR] {len(candidatos)} clips para revisar\n")

    for orden, (i, clip) in enumerate(candidatos, 1):
        rango = clip.get("rango_original", {})
        print(
            f"{'─'*42}\n"
            f"Clip {orden}/{len(candidatos)} — Score {clip.get('score', 0)}/10\n"
            f"Rango  : {rango.get('inicio', '?')} → {rango.get('fin', '?')}"
            f"  ({rango.get('duracion_segundos', '?')}s)\n"
            f"Línea 1: {clip.get('texto_linea1', '')}\n"
            f"Línea 2: {clip.get('texto_linea2', '')}\n"
            f"{'─'*42}\n"
            f"[A]probar  [T]ítulo  [R]ango  [E]ditar ambos  [D]escartar"
        )

        while True:
            try:
                accion = input("→ ").strip().upper()
            except EOFError:
                accion = "A"

            if accion == "A":
                clips_aprobados.append(clip)
                print("✅ Aprobado")
                break

            elif accion == "T":
                try:
                    l1 = input("Línea 1: ").strip()
                    l2 = input("Línea 2: ").strip()
                except EOFError:
                    l1, l2 = clip.get("texto_linea1", ""), clip.get("texto_linea2", "")
                _guardar_evento_correccion(
                    clip, l1, l2,
                    rango.get("inicio", ""), rango.get("fin", ""),
                    session_dir, config,
                )
                clip["texto_linea1"] = l1
                clip["texto_linea2"] = l2
                clips_aprobados.append(clip)
                print("✅ Título actualizado y aprendizaje guardado")
                break

            elif accion == "R":
                try:
                    inicio = input("Nuevo inicio (HH:MM:SS): ").strip()
                    fin    = input("Nuevo fin   (HH:MM:SS): ").strip()
                except EOFError:
                    inicio, fin = rango.get("inicio", ""), rango.get("fin", "")
                _guardar_evento_correccion(
                    clip,
                    clip.get("texto_linea1", ""), clip.get("texto_linea2", ""),
                    inicio, fin,
                    session_dir, config,
                )
                clip["rango_original"]["inicio"] = inicio
                clip["rango_original"]["fin"]    = fin
                clips_aprobados.append(clip)
                print("✅ Rango actualizado y aprendizaje guardado")
                break

            elif accion == "E":
                try:
                    l1     = input("Línea 1: ").strip()
                    l2     = input("Línea 2: ").strip()
                    inicio = input("Nuevo inicio (HH:MM:SS): ").strip()
                    fin    = input("Nuevo fin   (HH:MM:SS): ").strip()
                except EOFError:
                    l1, l2 = clip.get("texto_linea1", ""), clip.get("texto_linea2", "")
                    inicio, fin = rango.get("inicio", ""), rango.get("fin", "")
                _guardar_evento_correccion(
                    clip, l1, l2, inicio, fin,
                    session_dir, config,
                )
                clip["texto_linea1"]             = l1
                clip["texto_linea2"]             = l2
                clip["rango_original"]["inicio"] = inicio
                clip["rango_original"]["fin"]    = fin
                clips_aprobados.append(clip)
                print("✅ Título y rango actualizados y aprendizaje guardado")
                break

            elif accion == "D":
                try:
                    razon = input("Razón (Enter para omitir): ").strip()
                except EOFError:
                    razon = ""
                if razon:
                    _guardar_evento_descarte(clip, razon, session_dir, config)
                    print("✅ Descarte registrado como aprendizaje")
                else:
                    print("⏭ Clip descartado")
                break

            else:
                print("Opción no válida. Usa A, T, R, E o D.")

        print()

    print(f"[REVISAR] {len(clips_aprobados)}/{len(candidatos)} clips aprobados\n")
    return clips_aprobados


# ─────────────────────────────────────────
#  HELPERS DE DISPLAY
# ─────────────────────────────────────────

def _banner(cfg: ConfigLoader, mode: str, url: str = None) -> None:
    canal_id    = cfg.get("meta", "id",          default="default")
    descripcion = cfg.get("meta", "descripcion", default="—")
    config_file = cfg.loaded_file.name if cfg.loaded_file else "default.yaml"

    print(f"\n{'═' * 47}")
    print(f"  IDEA MILLONARIA — Pipeline v2.0")
    print(f"{'═' * 47}")
    print(f"  Modo    : {mode}")
    print(f"  Config  : {canal_id}  ({config_file})")
    print(f"  Canal   : {descripcion}")
    if url:
        print(f"  URL     : {url}")
    print(f"{'═' * 47}\n")


def _step(n: int, label: str) -> None:
    print(f"\n{'─' * 47}")
    print(f"  PASO {n}: {label}")
    print(f"{'─' * 47}\n")


# ─────────────────────────────────────────
#  PIPELINE PRINCIPAL
# ─────────────────────────────────────────

def run_pipeline(
    cfg,
    config: dict,
    url: str = None,
    test_dir: str = None,
    mode: str = "live",
    revisar: bool = False,
    usar_colab: bool = False,
    manual: bool = False,
) -> None:

    _banner(cfg, mode, url)

    # ── MODO TEST ────────────────────────────────────────────
    if test_dir:
        session_dir   = Path(test_dir)
        transcripcion = session_dir / "transcripcion_completa.txt"

        print(f"[PIPELINE] Sesión : {session_dir}\n")

        if not transcripcion.exists():
            print(f"[PIPELINE] ❌ No se encontró: {transcripcion}")
            sys.exit(1)

        # PASO 2: Agente 1
        _step(2, "DETECCIÓN DE PICOS VIRALES  (Agente 1)")
        peaks = agent1(str(transcripcion), config)

        if not peaks:
            print(f"\n{'═' * 47}")
            print("  PIPELINE FINALIZADO — Sin picos virales")
            print(f"{'═' * 47}\n")
            return

        # PASO 3: Agente 2
        _step(3, "REFINAMIENTO DE RANGOS  (Agente 2)")
        rangos      = agent2(str(session_dir / "picos.json"), config)
        conservados = [r for r in rangos if r.get("conservar")]

        if not conservados:
            print(f"\n{'═' * 47}")
            print("  PIPELINE FINALIZADO — Todos los rangos descartados")
            print(f"{'═' * 47}\n")
            return

        # PASO 4: Agente 3
        _step(4, "SCORING Y GENERACIÓN DE CONTENIDO  (Agente 3)")
        contenido  = agent3(str(session_dir / "rangos.json"), config)
        a_publicar = [c for c in contenido if c.get("publicar")]

        # PASO 5: Agente 4  (técnico puro — no recibe config)
        _step(5, "CORTE DE VIDEO  (Agente 4)")
        agent4(str(session_dir / "contenido.json"))

        # Resumen final
        clips_dir = session_dir / "clips"
        n_clips   = len(list(clips_dir.glob("*.mp4"))) if clips_dir.exists() else 0

        print(f"\n{'═' * 47}")
        print(f"  PIPELINE COMPLETADO  (modo test)")
        print(f"  Session  : {session_dir.name}")
        print(f"  Config   : {cfg.get('meta', 'id')}")
        print(f"  Picos    : {len(peaks)} detectados")
        print(f"  Rangos   : {len(conservados)} conservados")
        print(f"  Clips    : {n_clips} generados")
        print(f"  Carpeta  : {clips_dir}")
        print(f"{'═' * 47}")
        print(f"  Revisá los clips y dá tu OK para publicar.\n")

    # ── MODO VIDEO ───────────────────────────────────────────
    elif mode == "video":
        _run_video_chunks(cfg, config, url, revisar=revisar, usar_colab=usar_colab, manual=manual)

    # ── MODO LIVE ─────────────────────────────────────────────
    else:
        canal_id = cfg.get("meta", "id", default="default")

        _step(1, f"CAPTURA + ANÁLISIS EN TIEMPO REAL  (config: {canal_id})")
        print("[PIPELINE] capture_pipeline.py maneja todo:")
        print("[PIPELINE]   Proceso A — video completo en background")
        print("[PIPELINE]   Proceso B — audio chunks + Whisper + Agents 1–4 por chunk")
        print("[PIPELINE] Presioná Ctrl+C cuando quieras detener la grabación.\n")

        existing = {d for d in STREAM_DATA.glob("*") if d.is_dir()} if STREAM_DATA.exists() else set()

        capture_cmd = [sys.executable, "capture_pipeline.py", url]
        if canal_id != "default":
            capture_cmd += ["--config", canal_id]

        proc = subprocess.Popen(capture_cmd)
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.wait()

        current  = {d for d in STREAM_DATA.glob("*") if d.is_dir()} if STREAM_DATA.exists() else set()
        new_dirs = current - existing

        if new_dirs:
            session_dir = max(new_dirs, key=lambda p: p.stat().st_mtime)
            clips_dir   = session_dir / "clips"
            n_clips     = len(list(clips_dir.glob("*.mp4"))) if clips_dir.exists() else 0

            cands_file = session_dir / "clips_candidatos.json"
            n_cands    = 0
            if cands_file.exists():
                data    = json.loads(cands_file.read_text(encoding="utf-8"))
                n_cands = len([c for c in data.get("contenido", []) if c.get("publicar")])

            print(f"\n{'═' * 47}")
            print(f"  PIPELINE COMPLETADO")
            print(f"  Session    : {session_dir.name}")
            print(f"  Config     : {canal_id}")
            print(f"  Candidatos : {n_cands}")
            print(f"  Clips      : {n_clips} generados")
            print(f"  Carpeta    : {clips_dir}")
            print(f"{'═' * 47}")
            print(f"  Revisá los clips y dá tu OK para publicar.\n")


# ─────────────────────────────────────────
#  VIDEO CON CHUNKS
# ─────────────────────────────────────────

def _split_transcription(trans_path: Path, inicio_s: int, fin_s: int) -> str:
    """Extrae líneas con timestamp en [inicio_s, fin_s) de una transcripción existente."""
    import re
    lines = []
    for line in trans_path.read_text(encoding="utf-8").splitlines(keepends=True):
        m = re.match(r"\[(\d+):(\d+)\]", line)
        if m:
            ts = int(m.group(1)) * 60 + int(m.group(2))
            if inicio_s <= ts < fin_s:
                lines.append(line)
    return "".join(lines)


def _run_video_chunks(
    cfg, config: dict, url: str, revisar: bool = False, usar_colab: bool = False,
    manual: bool = False,
) -> None:
    from core.chunk_manager    import ChunkManager
    from transcripcion.audio_chunker    import extract_audio_chunk
    from transcripcion.video_transcriber import transcribe_chunk

    canal_id = cfg.get("meta", "id", default="default")
    print(f"[PIPELINE] Modo transcripción: {'COLAB (GPU remota)' if usar_colab else 'WHISPERX (local, CPU)'}")

    # ── 1. Resolver input: ruta local o URL ─────────────────
    video_local      = Path(url) if Path(url).exists() else None
    resumed_from_url = False   # True si ya confirmamos retomar por URL match

    if video_local:
        session_dir = video_local.parent
        video_path  = video_local
        print(f"[PIPELINE] Video local: {video_path.name}")
    else:
        # Buscar sesión previa con esta misma URL ANTES de descargar
        session_dir = None
        video_path  = None

        if STREAM_DATA.exists():
            for estado_p in sorted(STREAM_DATA.glob("*/pipeline_estado.json"), reverse=True):
                try:
                    estado_data = json.loads(estado_p.read_text(encoding="utf-8"))
                    if estado_data.get("url") == url:
                        cand_dir   = estado_p.parent
                        cand_video = cand_dir / "stream_completo.mp4"
                        if cand_video.exists():
                            chunks_e = estado_data.get("chunks", {})
                            total_e  = len(chunks_e)
                            comp_e   = sum(1 for v in chunks_e.values() if v["estado"] == "completado")
                            print(f"\n[PIPELINE] Sesión previa encontrada: {cand_dir.name}")
                            print(f"[PIPELINE] Progreso: {comp_e}/{total_e} chunks completados")
                            if not sys.stdin.isatty():
                                resp = "s"
                            else:
                                try:
                                    resp = input("¿Continuar esa sesión? [S/n] ").strip().lower()
                                except EOFError:
                                    resp = "s"
                            if resp not in ("n", "no"):
                                session_dir      = cand_dir
                                video_path       = cand_video
                                resumed_from_url = True
                                print(f"[PIPELINE] Retomando {cand_dir.name}...")
                            break
                except Exception:
                    pass

        if session_dir is None:
            from captura.video_capture import download_video
            session_id  = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = STREAM_DATA / session_id
            _step(1, "DESCARGA DE VIDEO")
            try:
                info = download_video(url, session_dir)
            except RuntimeError as e:
                print(f"\n[PIPELINE] ❌ Descarga fallida:\n{e}")
                sys.exit(1)
            video_path = info["video_path"]
            if info.get("titulo"):
                print(f"\n[PIPELINE] Título: {info['titulo']}")

    # ── 2. Duración del video ────────────────────────────────
    dur_r = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(video_path),
    ], capture_output=True, text=True)
    try:
        duracion = int(float(dur_r.stdout.strip()))
    except (ValueError, AttributeError):
        print("[PIPELINE] ❌ No se pudo obtener la duración del video.")
        sys.exit(1)

    # ── 3. ChunkManager — carga o crea plan ─────────────────
    chunk_mgr    = ChunkManager(session_dir, duracion, chunk_minutos=30)
    estado_exist = chunk_mgr.cargar_estado()

    if estado_exist:
        if resumed_from_url:
            # Ya confirmamos retomar en el paso de búsqueda por URL — no preguntar de nuevo
            chunks_e = estado_exist["chunks"]
            comp_e   = sum(1 for v in chunks_e.values() if v["estado"] == "completado")
            print(f"[PIPELINE] Estado cargado ({comp_e}/{len(chunks_e)} chunks completados).")
        else:
            chunks_e = estado_exist["chunks"]
            total_e  = len(chunks_e)
            comp_e   = sum(1 for v in chunks_e.values() if v["estado"] == "completado")
            if not sys.stdin.isatty():
                resp = "s"
            else:
                try:
                    resp = input(
                        f"\nSesión previa encontrada ({comp_e}/{total_e} chunks). ¿Continuar? [S/n] "
                    ).strip().lower()
                except EOFError:
                    resp = "s"
            if resp in ("n", "no"):
                chunk_mgr.crear_plan(url=url, config=canal_id, modo="manual" if manual else "automatico")
                print("[PIPELINE] Sesión nueva iniciada.")
            else:
                print("[PIPELINE] Retomando sesión previa...")
    else:
        chunk_mgr.crear_plan(url=url, config=canal_id, modo="manual" if manual else "automatico")

    # ── 4. Banner ────────────────────────────────────────────
    all_chunks = chunk_mgr._estado["chunks"]
    total      = len(all_chunks)
    comp       = sum(1 for v in all_chunks.values() if v["estado"] == "completado")
    pendientes = chunk_mgr.get_pendientes()
    border     = "═" * 40

    print(f"\n{border}")
    print(f"  PROCESAMIENTO POR CHUNKS")
    print(f"  Total   : {total} chunk(s) de {chunk_mgr.chunk_minutos} min")
    print(f"  Completados: {comp} | Pendientes: {len(pendientes)}")
    if estado_exist and comp > 0 and pendientes:
        print(f"  Retomando desde {pendientes[0]['id']}...")
    print(f"{border}\n")

    # ── 5. Transcripción base para split ─────────────────────
    trans_base = None
    for cand in ("transcripcion_enriquecida.txt", "transcripcion_raw.txt"):
        p = session_dir / cand
        if p.exists():
            trans_base = p
            break

    contenido_chunks_dir = session_dir / "contenido_chunks"
    contenido_chunks_dir.mkdir(exist_ok=True)

    # ── 6. Procesar chunks pendientes ────────────────────────
    for chunk in pendientes:
        chunk_id  = chunk["id"]
        inicio_s  = chunk["inicio_segundos"]
        fin_s     = chunk["fin_segundos"]
        inicio_ts = chunk["inicio_ts"]
        fin_ts    = chunk["fin_ts"]
        dur_chunk = (fin_s - inicio_s) // 60

        chunk_dir   = session_dir / "chunks" / chunk_id
        chunk_dir.mkdir(parents=True, exist_ok=True)
        trans_chunk = chunk_dir / "transcripcion_completa.txt"

        print(f"\n{'─' * 40}")
        print(f"  {chunk_id.upper()} — {inicio_ts} → {fin_ts}  ({dur_chunk} min)")
        print(f"{'─' * 40}\n")

        try:
            # ── Transcripción ──────────────────────────────
            if trans_chunk.exists():
                n = len(trans_chunk.read_text(encoding="utf-8").splitlines())
                print(f"[{chunk_id}] Transcripción existente ({n} líneas).")
            elif trans_base:
                print(f"[{chunk_id}] Dividiendo transcripción existente...")
                texto = _split_transcription(trans_base, inicio_s, fin_s)
                trans_chunk.write_text(texto, encoding="utf-8")
                print(f"[{chunk_id}] ✅ {len(texto.splitlines())} líneas extraídas")
            else:
                audio_dir   = session_dir / "audio_chunks"
                audio_dir.mkdir(exist_ok=True)
                audio_chunk = audio_dir / f"{chunk_id}.mp3"

                if not audio_chunk.exists():
                    print(f"[{chunk_id}] Extrayendo audio {inicio_ts} → {fin_ts}...")
                    extract_audio_chunk(video_path, inicio_ts, fin_ts, audio_chunk)
                    sz = audio_chunk.stat().st_size / (1024 * 1024)
                    print(f"[{chunk_id}] ✅ Audio: {sz:.1f} MB")

                print(f"[{chunk_id}] Transcribiendo con Whisper...")
                transcribe_chunk(audio_chunk, chunk_dir, chunk_id, inicio_s, usar_colab=usar_colab)

            # ── Limpieza de nombres (ecosistemas con personajes) ──
            if config.get("personajes") and trans_chunk.exists():
                from transcripcion.transcript_cleaner import clean_known_names
                raw_text   = trans_chunk.read_text(encoding="utf-8")
                clean_text = clean_known_names(raw_text, config)
                if clean_text != raw_text:
                    trans_chunk.write_text(clean_text, encoding="utf-8")

            # ── Modo manual: sin Claude — solo transcripción ─
            if manual:
                print(f"[{chunk_id}] Modo manual — sin Agente 0 ni Agentes 1-4 (cero llamadas a Claude)")
                print(f"[{chunk_id}] Transcripción lista: {trans_chunk}")
                chunk_mgr.marcar_completado(chunk_id)
                continue

            # ── Agent 0 (solo si transcripción viene de whisper) ─
            raw_chunk     = chunk_dir / "transcripcion_raw.txt"
            metadata_path = session_dir / "metadata.json"
            if raw_chunk.exists() and metadata_path.exists():
                try:
                    agent0(raw_chunk, metadata_path, chunk_dir, config)
                    enr = chunk_dir / "transcripcion_enriquecida.txt"
                    if enr.exists():
                        enr.replace(trans_chunk)
                except Exception as e:
                    print(f"[{chunk_id}] ⚠ Agent0 omitido: {e}")

            # ── Agent 1 ────────────────────────────────────
            peaks = agent1(str(trans_chunk), config)

            if not peaks:
                print(f"[{chunk_id}] Sin picos — marcando completado.")
                chunk_mgr.marcar_completado(chunk_id)
                continue

            # ── Agent 2 ────────────────────────────────────
            picos_p  = chunk_dir / "picos.json"
            rangos   = agent2(str(picos_p), config)
            conservados = [r for r in rangos if r.get("conservar")]

            if not conservados:
                print(f"[{chunk_id}] Todos los rangos descartados.")
                chunk_mgr.marcar_completado(chunk_id)
                continue

            # ── Agent 3 ────────────────────────────────────
            rangos_p  = chunk_dir / "rangos.json"
            contenido = agent3(str(rangos_p), config)

            # ── Revisión manual (si --revisar activo) ────────
            if revisar:
                a_pub = _revisar_clips(contenido, chunk_dir, config, cfg)
                # Actualizar flags de publicar según lo aprobado en revisión
                approved_ids = {id(c) for c in a_pub}
                for c in contenido:
                    c["publicar"] = (id(c) in approved_ids)
                # Reescribir contenido.json con resultados de revisión
                (chunk_dir / "contenido.json").write_text(
                    json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                a_pub = [c for c in contenido if c.get("publicar")]

            # Guardar resumen del chunk (después de revisión si aplica)
            chunk_contenido_path = contenido_chunks_dir / f"{chunk_id}.json"
            chunk_contenido_path.write_text(
                json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # ── Agent 4 (inmediato, por chunk) ──────────────
            clips_dir_global = session_dir / "clips"
            clips_dir_global.mkdir(exist_ok=True)
            if a_pub:
                offset   = len(list(clips_dir_global.glob("clip_*.mp4")))
                agent4(
                    str(chunk_dir / "contenido.json"),
                    video_path_override=video_path,
                    clips_dir_override=clips_dir_global,
                    clip_offset=offset,
                )
                n_nuevos = len(list(clips_dir_global.glob("clip_*.mp4"))) - offset
                print(f"[{chunk_id.upper()}] ✅ {n_nuevos} clip(s) cortados y listos")
                print(f"[{chunk_id.upper()}] 📁 {clips_dir_global}")
            else:
                print(f"[{chunk_id.upper()}] Sin clips para publicar")

            print(f"[{chunk_id}] ✅ Completado — {len(a_pub)} clip(s) para publicar")
            chunk_mgr.marcar_completado(chunk_id)

        except KeyboardInterrupt:
            print(f"\n[PIPELINE] Interrumpido. {chunk_id} sigue pendiente.")
            sys.exit(0)
        except Exception as e:
            print(f"[{chunk_id}] ❌ Error: {e}")
            chunk_mgr.marcar_fallido(chunk_id, str(e))

    if manual:
        chunk_mgr.resumen()
        print(f"\n{'═' * 47}")
        print(f"  TRANSCRIPCIÓN LISTA — MODO MANUAL")
        print(f"  Session          : {session_dir.name}")
        print(f"  Config           : {canal_id}")
        print(f"  Transcripciones  : {session_dir / 'chunks'}")
        print(f"{'═' * 47}")
        print(f"  Cero llamadas a Claude en esta sesión (modo: manual).")
        print(f"  Para cortar tus clips y guardarlos como ejemplos, usá:")
        print(f"    python clip_manual.py --video {video_path} \\")
        print(f"      --inicio HH:MM:SS --fin HH:MM:SS \\")
        print(f"      --linea1 \"...\" --linea2 \"...\" \\")
        print(f"      --config {canal_id} --entrenamiento")
        print(f"{'═' * 47}\n")
        return

    # ── 7. Merge contenido_chunks → contenido_final.json ────
    todo = []
    for f in sorted(contenido_chunks_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        todo.extend(data.get("contenido", []))

    todo.sort(key=lambda c: c.get("score", 0), reverse=True)

    contenido_final = session_dir / "contenido_final.json"
    contenido_final.write_text(
        json.dumps({"contenido": todo}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    a_pub_total = [c for c in todo if c.get("publicar")]
    print(f"\n[PIPELINE] contenido_final.json — {len(todo)} clips, {len(a_pub_total)} para publicar")

    # ── Resumen ──────────────────────────────────────────────
    clips_dir = session_dir / "clips"
    n_clips   = len(list(clips_dir.glob("clip_*.mp4"))) if clips_dir.exists() else 0

    chunk_mgr.resumen()
    print(f"\n{'═' * 47}")
    print(f"  PIPELINE COMPLETADO")
    print(f"  Session          : {session_dir.name}")
    print(f"  Config           : {canal_id}")
    print(f"  Total clips      : {n_clips} generados")
    print(f"  Carpeta          : {clips_dir}")
    print(f"{'═' * 47}\n")


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description="IDEA MILLONARIA — Pipeline v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python pipeline.py --live  https://tiktok.com/@papi.jhos/live --config papi_jhos\n"
            "  python pipeline.py --video https://tiktok.com/@usuario/live\n"
            "  python pipeline.py --test  stream_data/test/ --config papi_jhos\n"
        ),
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--live",  metavar="URL", help="TikTok Live en vivo")
    mode_group.add_argument("--video", metavar="URL", help="Video grabado / URL directa")
    mode_group.add_argument("--test",  metavar="DIR", help="Directorio de sesión existente")

    parser.add_argument(
        "--config", metavar="CANAL_ID", default=None,
        help="ID del canal en config/  (ej: papi_jhos).  Default: default.yaml",
    )
    parser.add_argument(
        "--revisar", action="store_true", default=False,
        help="Modo revisión: pide aprobación de cada clip antes de cortar con FFmpeg",
    )
    parser.add_argument(
        "--colab", action="store_true", default=False,
        help="Transcribe vía GPU remota de Colab (COLAB_TRANSCRIBE_URL) en vez de WhisperX local",
    )
    parser.add_argument(
        "--manual", action="store_true", default=False,
        help="Solo --video: descarga + transcribe y se detiene. Sin Agente 0 ni Agentes 1-4 "
             "(cero llamadas a Claude). Usar junto con clip_manual.py --entrenamiento.",
    )

    args = parser.parse_args()

    # Cargar configuración antes de cualquier procesamiento
    config, cfg = _load_config(args.config)

    if args.test:
        run_pipeline(cfg, config, test_dir=args.test, mode="test", revisar=args.revisar)
    elif args.live:
        run_pipeline(cfg, config, url=args.live, mode="live", revisar=args.revisar)
    else:
        run_pipeline(
            cfg, config, url=args.video, mode="video",
            revisar=args.revisar, usar_colab=args.colab, manual=args.manual,
        )
