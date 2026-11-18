"""
===========================================
  IDEA MILLONARIA — Pipeline v2.0
  Orquestador: Captura + ConfigLoader + 4 Agentes
===========================================

Uso:
  python pipeline.py --live  https://tiktok.com/@usuario/live  [--config zapatillas_peru]
  python pipeline.py --video https://tiktok.com/@usuario/live  [--config canal_id]
  python pipeline.py --test  stream_data/test/                 [--config zapatillas_peru]

  --config omitido → usa config/default.yaml
"""

import os
import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import shutil
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
from agentes.agent3_viral_scorer   import run_agent as agent3, run_copy as agent3_copy
from agentes.juez                  import run_juez
from agentes                       import direccion
from edicion_video.agent4_video_cutter   import run_agent as agent4
from agentes.agent0_speaker_identifier import identify_speakers as agent0
from core.chunk_manager import PASOS_CHUNK, PASOS_SESION
from core.clip_ids import prefijo_chunk
from core import fuente as fuente_mod
from core.pasos import ErrorPaso, PasoFallido, Subpasos, ejecutar_paso

from core.config_local import ruta as _ruta_config
STREAM_DATA = _ruta_config("CLIPEO_STREAM_DATA", Path("stream_data"))   # CLIP-54: del .env; si no, relativo al cwd

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
    session_id: str | None = None,
    reintentar: str | None = None,
    chunk_reintentar: str | None = None,
    fuente_nueva: dict | None = None,
) -> None:

    _banner(cfg, mode, url)

    # ── MODO TEST ────────────────────────────────────────────
    if test_dir:
        _run_test(cfg, config, Path(test_dir), revisar=revisar,
                  reintentar=reintentar, chunk_reintentar=chunk_reintentar)

    # ── MODO VIDEO ───────────────────────────────────────────
    elif mode == "video":
        _run_video_chunks(
            cfg, config, url, revisar=revisar, usar_colab=usar_colab, manual=manual,
            session_id=session_id, reintentar=reintentar, chunk_reintentar=chunk_reintentar,
            fuente_nueva=fuente_nueva,
        )

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


def _leer_lista(path: Path, clave: str) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get(clave, [])


def _borrar_salidas(session_dir: Path, salidas: list[str]) -> None:
    for rel in salidas:
        p = session_dir / rel
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink(missing_ok=True)
        except OSError as e:
            print(f"[PIPELINE] ⚠ No se pudo borrar {p}: {e}")


def _aplicar_reintento(mgr, reintentar: str | None, chunk_reintentar: str | None) -> None:
    """--reintentar: vuelve el paso (y los siguientes) a pendiente y borra lo que produjeron."""
    if not reintentar:
        return
    chunks = [c.strip() for c in chunk_reintentar.split(",") if c.strip()] if chunk_reintentar else [None]
    for chunk_id in chunks:
        donde = f"{chunk_id}/{reintentar}" if chunk_id else reintentar
        print(f"[PIPELINE] Reintentando desde {donde}...")
        _borrar_salidas(mgr.session_dir, mgr.resetear_desde(reintentar, chunk_id))


def _procesar_chunk(
    mgr, chunk: dict, *,
    session_dir: Path, video_path: Path | None, config: dict, cfg, revisar: bool,
    usar_colab: bool, manual: bool, trans_base: Path | None, modo_test: bool = False,
) -> None:
    """
    Corre los pasos de un chunk (transcripcion → agente0..3 → corte) vía core/pasos.py.
    Cada paso lee su entrada de disco, no de memoria: así un paso ya 'ok' se salta y la
    corrida retoma exactamente donde quedó. Lanza PasoFallido si un paso queda en error.
    """
    from transcripcion.audio_chunker     import extract_audio_chunk
    from transcripcion.video_transcriber import transcribe_chunk

    chunk_id    = chunk["id"]
    chunk_dir   = session_dir if modo_test else session_dir / "chunks" / chunk_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    trans_chunk = chunk_dir / "transcripcion_completa.txt"
    raw_chunk   = chunk_dir / "transcripcion_raw.txt"
    picos_p     = chunk_dir / "picos.json"
    rangos_p    = chunk_dir / "rangos.json"
    contenido_p = chunk_dir / "contenido.json"
    contenido_chunk_p = session_dir / "contenido_chunks" / f"{chunk_id}.json"
    clips_dir   = session_dir / "clips"

    def paso(nombre: str, fn) -> None:
        ejecutar_paso(mgr, chunk_id, nombre, fn, trace_dir=chunk_dir / "trazas" / nombre)

    def omitir(*nombres: str, nota: str) -> None:
        for n in nombres:
            if mgr.paso(chunk_id, n)["estado"] == "pendiente":
                mgr.actualizar_paso(chunk_id, n, estado="omitido", nota=nota)

    # ── Transcripción ───────────────────────────────────
    def _transcribir():
        if modo_test:
            if not trans_chunk.exists():
                raise ErrorPaso(f"No se encontró {trans_chunk}")
            return {"omitido": True, "nota": "modo test: transcripción existente"}

        salidas = [trans_chunk, raw_chunk, chunk_dir / "palabras.json"]
        if trans_chunk.exists():
            nota = f"existente ({len(trans_chunk.read_text(encoding='utf-8').splitlines())} líneas)"
        elif trans_base:
            print(f"[{chunk_id}] Dividiendo transcripción existente...")
            texto = _split_transcription(trans_base, chunk["inicio_segundos"], chunk["fin_segundos"])
            trans_chunk.write_text(texto, encoding="utf-8")
            nota = f"dividida de {trans_base.name} ({len(texto.splitlines())} líneas)"
        else:
            audio_chunk = session_dir / "audio_chunks" / f"{chunk_id}.mp3"
            audio_chunk.parent.mkdir(exist_ok=True)
            if not audio_chunk.exists():
                print(f"[{chunk_id}] Extrayendo audio {chunk['inicio_ts']} → {chunk['fin_ts']}...")
                extract_audio_chunk(video_path, chunk["inicio_ts"], chunk["fin_ts"], audio_chunk)
            print(f"[{chunk_id}] Transcribiendo con {'Colab' if usar_colab else 'WhisperX'}...")
            transcribe_chunk(audio_chunk, chunk_dir, chunk_id, chunk["inicio_segundos"], usar_colab=usar_colab)
            salidas.append(audio_chunk)
            nota = f"{len(trans_chunk.read_text(encoding='utf-8').splitlines())} líneas"

        # Limpieza de nombres (ecosistemas con personajes)
        if config.get("personajes") and trans_chunk.exists():
            from transcripcion.transcript_cleaner import clean_known_names
            raw_text   = trans_chunk.read_text(encoding="utf-8")
            clean_text = clean_known_names(raw_text, config)
            if clean_text != raw_text:
                trans_chunk.write_text(clean_text, encoding="utf-8")
        return {"salidas": salidas, "nota": nota}

    paso("transcripcion", _transcribir)

    if manual:
        omitir("agente0", "agente1", "agente2", "juez", "agente3", "corte",
               nota="modo --manual: solo transcripción, sin llamadas a Claude")
        print(f"[{chunk_id}] Modo manual — transcripción lista: {trans_chunk}")
        return

    # ── Agente 0 (solo si la transcripción viene de whisper, con metadata) ──
    def _agente0():
        metadata_path = session_dir / "metadata.json"
        if modo_test or not raw_chunk.exists() or not metadata_path.exists():
            return {"omitido": True, "nota": "sin transcripción con speakers o sin metadata.json"}
        agent0(raw_chunk, metadata_path, chunk_dir, config)
        enr = chunk_dir / "transcripcion_enriquecida.txt"
        if enr.exists():
            enr.replace(trans_chunk)
        return {"salidas": [chunk_dir / "speaker_map.json"]}

    paso("agente0", _agente0)

    # ── Agente 1 ────────────────────────────────────────
    def _agente1():
        peaks = agent1(str(trans_chunk), config)
        return {"salidas": [picos_p], "nota": f"{len(peaks)} pico(s)"}

    paso("agente1", _agente1)
    if not _leer_lista(picos_p, "picos"):
        omitir("agente2", "juez", "agente3", "corte", nota="sin picos")
        print(f"[{chunk_id}] Sin picos.")
        return

    # ── Agente 2 ────────────────────────────────────────
    def _agente2():
        rangos = agent2(str(picos_p), config)
        conservados = sum(1 for r in rangos if r.get("conservar"))
        return {"salidas": [rangos_p], "nota": f"{conservados}/{len(rangos)} rango(s) conservados"}

    paso("agente2", _agente2)
    if not any(r.get("conservar") for r in _leer_lista(rangos_p, "rangos")):
        omitir("juez", "agente3", "corte", nota="todos los rangos descartados")
        print(f"[{chunk_id}] Todos los rangos descartados.")
        return

    def _guardar_contenido(contenido: list[dict]) -> None:
        contenido_chunk_p.parent.mkdir(exist_ok=True)
        for destino in (contenido_p, contenido_chunk_p):
            destino.write_text(
                json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2), encoding="utf-8",
            )

    # ── Juez: único filtro de calidad, contra la memoria del nicho ──
    def _juez():
        texto = next(
            (p.read_text(encoding="utf-8") for p in (chunk_dir / "transcripcion_enriquecida.txt", trans_chunk)
             if p.exists()),
            "",
        )
        rangos = _leer_lista(rangos_p, "rangos")
        if direccion.activada():   # CLIP-31: dirección editorial antes del juez (encendida por defecto; DIRECCION_EDITORIAL=0 la apaga)
            rangos = direccion.run_direccion(rangos, transcripcion=texto, config=config)
            rangos_p.write_text(json.dumps({"rangos": rangos}, ensure_ascii=False, indent=2), encoding="utf-8")
        return run_juez(rangos, transcripcion=texto, config=config,
                        session_dir=session_dir, chunk_dir=chunk_dir)

    paso("juez", _juez)

    # ── Agente 3: copy de los aprobados por el juez (o score+copy sin memoria) ──
    def _agente3():
        juez_p = chunk_dir / "juez.json"
        advertencias: list[str] = []
        if mgr.paso(chunk_id, "juez")["estado"] == "ok" and juez_p.exists():
            contenido, advertencias = agent3_copy(str(juez_p), config)
        else:
            contenido = agent3(str(rangos_p), config)
        if revisar:
            a_pub = _revisar_clips(contenido, chunk_dir, config, cfg)
            approved_ids = {id(c) for c in a_pub}
            for c in contenido:
                c["publicar"] = (id(c) in approved_ids)
        _guardar_contenido(contenido)
        n_pub = sum(1 for c in contenido if c.get("publicar"))
        nota = f"{n_pub}/{len(contenido)} para publicar"
        if advertencias:
            nota += " · ⚠ " + "; ".join(advertencias)
        return {"salidas": [contenido_p, contenido_chunk_p], "nota": nota}

    paso("agente3", _agente3)

    # ── Agente 4: corte ─────────────────────────────────
    def _cortar():
        contenido = _leer_lista(contenido_chunk_p, "contenido")
        if not any(c.get("publicar") for c in contenido):
            return {"omitido": True, "nota": "sin clips para publicar"}

        # Nombres propios del chunk (core/clip_ids.py): reintentar solo pisa estos archivos
        prefijo = prefijo_chunk(chunk_id)
        clips_dir.mkdir(exist_ok=True)
        for viejo in clips_dir.glob(f"{prefijo}_*"):
            viejo.unlink()

        # Agente 4 lee contenido.json del chunk (y desde ahí palabras.json, etc.); se
        # sincroniza con contenido_chunks/ por si la revisión web lo editó.
        contenido_p.write_text(
            json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        resultados = agent4(
            str(contenido_p),
            video_path_override=video_path,
            clips_dir_override=clips_dir,
            clip_prefix=prefijo,
        )

        ids = iter(r["clip_id"] for r in resultados)
        for c in contenido:
            if c.get("publicar"):
                c["clip_id"] = next(ids)
            else:
                # Sin video: al re-cortar una sesión ya revisada, un descartado conservaba su clip_id viejo y chocaba
                # con el aprobado renumerado (demo S9, sesión del guardia: dos clip_c001_01)
                c.pop("clip_id", None)
        for destino in (contenido_chunk_p, contenido_p):
            destino.write_text(
                json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2), encoding="utf-8",
            )

        fallidos = [r["clip_id"] for r in resultados if not r["ok"]]
        if fallidos:
            raise ErrorPaso(f"FFmpeg falló al cortar {', '.join(fallidos)} — ver log", reintentable=False)

        salidas = [clips_dir / f"{r['clip_id']}{ext}" for r in resultados for ext in (".mp4", ".json")]
        return {"salidas": salidas, "nota": f"{len(resultados)} clip(s) cortados"}

    paso("corte", _cortar)


def _cerrar_sesion(mgr, session_dir: Path, revisar: bool) -> tuple[int, bool]:
    """
    Merge de contenido_chunks → contenido_final.json y estado del paso Revisión.
    Devuelve (clips_para_publicar, hubo_errores).
    """
    contenido_chunks_dir = session_dir / "contenido_chunks"
    todo = []
    for f in sorted(contenido_chunks_dir.glob("*.json")) if contenido_chunks_dir.exists() else []:
        todo.extend(_leer_lista(f, "contenido"))
    todo.sort(key=lambda c: c.get("score", 0), reverse=True)
    (session_dir / "contenido_final.json").write_text(
        json.dumps({"contenido": todo}, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    n_pub = sum(1 for c in todo if c.get("publicar"))
    print(f"\n[PIPELINE] contenido_final.json — {len(todo)} clips, {n_pub} para publicar")

    chunks       = mgr._estado.get("chunks", {}).values()
    hubo_errores = any(c["estado"] == "fallido" for c in chunks)
    terminado    = bool(chunks) and all(c["estado"] == "completado" for c in chunks)

    if terminado and mgr.paso(None, "revision")["estado"] == "pendiente":
        ahora = datetime.now().isoformat(timespec="seconds")
        if n_pub == 0:
            mgr.actualizar_paso(None, "revision", estado="omitido", nota="sin clips para revisar", fin=ahora)
            mgr.actualizar_paso(None, "fin", estado="ok", fin=ahora)
        elif revisar:
            mgr.actualizar_paso(None, "revision", estado="ok", nota="revisado en terminal (--revisar)", fin=ahora)
            mgr.actualizar_paso(None, "fin", estado="ok", fin=ahora)
        else:
            mgr.actualizar_paso(None, "revision", estado="esperando", inicio=ahora,
                                nota=f"{n_pub} clip(s) por revisar")
    return n_pub, hubo_errores


def _procesar_pendientes(mgr, session_dir: Path, **kwargs) -> None:
    pendientes = mgr.get_pendientes()
    for chunk in pendientes:
        chunk_id = chunk["id"]
        print(f"\n{'─' * 40}")
        print(f"  {chunk_id.upper()} — {chunk['inicio_ts']} → {chunk['fin_ts']}")
        print(f"{'─' * 40}\n")
        try:
            _procesar_chunk(mgr, chunk, session_dir=session_dir, **kwargs)
            print(f"[{chunk_id}] ✅ Completado")
        except PasoFallido as e:
            print(f"[{chunk_id}] ❌ {e}")
        except KeyboardInterrupt:
            print(f"\n[PIPELINE] Interrumpido. {chunk_id} sigue pendiente.")
            sys.exit(0)


def _run_test(cfg, config: dict, session_dir: Path, revisar: bool = False,
              reintentar: str | None = None, chunk_reintentar: str | None = None) -> None:
    """--test: agentes 1→4 sobre una transcripcion_completa.txt existente, como un chunk único."""
    from core.chunk_manager import ChunkManager

    canal_id = cfg.get("meta", "id", default="default")
    print(f"[PIPELINE] Sesión : {session_dir}\n")

    mgr = ChunkManager(session_dir)
    if not mgr.cargar_estado() or not mgr.tiene_plan():
        mgr.iniciar(url=str(session_dir), config=canal_id, modo="test")
        mgr.crear_chunk_unico()
        for p in ("descarga", "plan"):
            mgr.actualizar_paso(None, p, estado="omitido", nota="modo test")
    _aplicar_reintento(mgr, reintentar, chunk_reintentar)

    _procesar_pendientes(
        mgr, session_dir, video_path=None, config=config, cfg=cfg, revisar=revisar,
        usar_colab=False, manual=False, trans_base=None, modo_test=True,
    )
    n_pub, hubo_errores = _cerrar_sesion(mgr, session_dir, revisar)

    clips_dir = session_dir / "clips"
    n_clips   = len(list(clips_dir.glob("*.mp4"))) if clips_dir.exists() else 0
    print(f"\n{'═' * 47}")
    print(f"  PIPELINE {'CON ERRORES' if hubo_errores else 'COMPLETADO'}  (modo test)")
    print(f"  Session  : {session_dir.name}")
    print(f"  Config   : {canal_id}")
    print(f"  Clips    : {n_clips} generados ({n_pub} para publicar)")
    print(f"  Carpeta  : {clips_dir}")
    print(f"{'═' * 47}\n")
    if hubo_errores:
        sys.exit(1)


def _duracion_video(video_path: Path) -> int:
    dur_r = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(video_path),
    ], capture_output=True, text=True)
    try:
        return int(float(dur_r.stdout.strip()))
    except (ValueError, AttributeError):
        raise ErrorPaso(f"No se pudo obtener la duración de {video_path}")


def _buscar_sesion_por_url(url: str) -> Path | None:
    """Sesión previa (de terminal) con esta misma URL y video ya descargado, si el usuario la acepta."""
    if not STREAM_DATA.exists():
        return None
    for estado_p in sorted(STREAM_DATA.glob("*/pipeline_estado.json"), reverse=True):
        try:
            estado_data = json.loads(estado_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if estado_data.get("url") != url or not (estado_p.parent / "stream_completo.mp4").exists():
            continue
        chunks_e = estado_data.get("chunks", {})
        comp_e   = sum(1 for v in chunks_e.values() if v["estado"] == "completado")
        print(f"\n[PIPELINE] Sesión previa encontrada: {estado_p.parent.name}")
        print(f"[PIPELINE] Progreso: {comp_e}/{len(chunks_e)} chunks completados")
        resp = "s"
        if sys.stdin.isatty():
            try:
                resp = input("¿Continuar esa sesión? [S/n] ").strip().lower()
            except EOFError:
                pass
        return None if resp in ("n", "no") else estado_p.parent
    return None


def _run_video_chunks(
    cfg, config: dict, url: str, revisar: bool = False, usar_colab: bool = False,
    manual: bool = False, session_id: str | None = None,
    reintentar: str | None = None, chunk_reintentar: str | None = None,
    fuente_nueva: dict | None = None,
) -> None:
    from core.chunk_manager import ChunkManager

    canal_id = cfg.get("meta", "id", default="default")
    modo     = "manual" if manual else "automatico"
    print(f"[PIPELINE] Modo transcripción: {'COLAB (GPU remota)' if usar_colab else 'WHISPERX (local, CPU)'}")

    # ── 1. Resolver sesión e input ──────────────────────────
    # Con --session-id (lo usa el backend) la sesión es siempre stream_data/<id>, también
    # para videos locales: así dos videos de la misma carpeta no comparten estado.
    video_local = Path(url) if Path(url).exists() else None
    retomada    = False

    if session_id:
        session_dir = STREAM_DATA / session_id
        video_path  = video_local or session_dir / "stream_completo.mp4"
        retomada    = True  # sin preguntas: el llamador decide
    elif video_local:
        session_dir = video_local.parent
        video_path  = video_local
        print(f"[PIPELINE] Video local: {video_path.name}")
    else:
        session_dir = _buscar_sesion_por_url(url)
        retomada    = session_dir is not None
        if session_dir is None:
            session_dir = STREAM_DATA / datetime.now().strftime("%Y%m%d_%H%M%S")
        video_path = session_dir / "stream_completo.mp4"

    mgr    = ChunkManager(session_dir, chunk_minutos=30)
    estado = mgr.cargar_estado()
    if estado and not retomada and sys.stdin.isatty():
        chunks_e = estado.get("chunks", {})
        comp_e   = sum(1 for v in chunks_e.values() if v["estado"] == "completado")
        try:
            resp = input(
                f"\nSesión previa encontrada ({comp_e}/{len(chunks_e)} chunks). ¿Continuar? [S/n] "
            ).strip().lower()
        except EOFError:
            resp = "s"
        if resp in ("n", "no"):
            estado = None
    if not estado:
        mgr.iniciar(url=url, config=canal_id, modo=modo)
        print(f"[PIPELINE] Sesión nueva: {session_dir.name}")
    else:
        print(f"[PIPELINE] Retomando {session_dir.name}...")

    # CLIP-27: la fuente queda en la sesión; retomar o reintentar nunca la pierde ni la cambia
    fuente_sesion = mgr._estado.get("fuente")
    if fuente_nueva and not fuente_sesion:
        mgr.actualizar_sesion(fuente=fuente_nueva)
        fuente_sesion = fuente_nueva
    elif fuente_nueva and fuente_sesion.get("sobre") != fuente_nueva.get("sobre"):
        print(f"[PIPELINE] ⚠ la sesión ya es de medios sobre «{fuente_sesion.get('sobre')}»; se conserva")
    if fuente_sesion:
        print(f"[PIPELINE] Fuente: {fuente_sesion['tipo']} · sobre {fuente_sesion.get('sobre')}")

    def _al_leer_metadata(video: dict) -> None:
        mgr.actualizar_sesion(video=video)
        if fuente_sesion and not fuente_sesion.get("canal_origen"):
            fuente_sesion["canal_origen"] = video.get("canal") or video.get("uploader") or video.get("channel")
            mgr.actualizar_sesion(fuente=fuente_sesion)
        # CLIP-36 (R-01): un canal o persona excluidos no se procesan (antes de bajar el video)
        from core import exclusion
        motivo = exclusion.motivo(canal=video.get("canal"), persona=(fuente_sesion or {}).get("sobre"))
        if motivo:
            raise ErrorPaso(f"No se procesa: {motivo}", reintentable=False)

    _aplicar_reintento(mgr, reintentar, chunk_reintentar)

    # ── 2. Pasos de sesión: descarga + plan ────────────────
    def _descargar():
        from captura.video_capture import SUBPASOS_DESCARGA, download_video
        _step(1, "DESCARGA DE VIDEO")
        info = download_video(
            url, session_dir,
            subpasos=Subpasos(mgr, None, "descarga", SUBPASOS_DESCARGA),
            on_metadata=_al_leer_metadata,
        )
        return {
            "salidas": [info["video_path"], info["audio_path"], session_dir / "metadata.json"],
            "nota":    info.get("titulo") or None,
        }

    def _planificar():
        duracion = _duracion_video(video_path)
        if not mgr.tiene_plan():
            mgr.duracion_total = duracion
            mgr.crear_plan(url=url, config=canal_id, modo=modo)
        n = len(mgr._estado["chunks"])
        return {"nota": f"{n} chunk(s) de {mgr.chunk_minutos} min · {duracion // 60} min de video"}

    descarga = mgr.paso(None, "descarga")
    if descarga["estado"] == "pendiente":
        if video_local:
            mgr.actualizar_paso(None, "descarga", estado="omitido", nota=f"video local: {video_local}")
        elif video_path.exists():
            mgr.actualizar_paso(None, "descarga", estado="ok", nota="video ya descargado")

    try:
        ejecutar_paso(mgr, None, "descarga", _descargar)
        ejecutar_paso(mgr, None, "plan", _planificar, reintentar_auto=False)
    except PasoFallido as e:
        print(f"\n[PIPELINE] ❌ {e}")
        sys.exit(1)

    # ── 3. Banner ────────────────────────────────────────────
    all_chunks = mgr._estado["chunks"]
    comp       = sum(1 for v in all_chunks.values() if v["estado"] == "completado")
    pendientes = mgr.get_pendientes()
    border     = "═" * 40
    print(f"\n{border}")
    print(f"  PROCESAMIENTO POR CHUNKS")
    print(f"  Total   : {len(all_chunks)} chunk(s) de {mgr.chunk_minutos} min")
    print(f"  Completados: {comp} | Pendientes: {len(pendientes)}")
    print(f"{border}\n")

    # ── 4. Chunks ────────────────────────────────────────────
    trans_base = None
    for cand in ("transcripcion_enriquecida.txt", "transcripcion_raw.txt"):
        if (session_dir / cand).exists():
            trans_base = session_dir / cand
            break

    _procesar_pendientes(
        mgr, session_dir, video_path=video_path, config=config, cfg=cfg, revisar=revisar,
        usar_colab=usar_colab, manual=manual, trans_base=trans_base,
    )

    if manual:
        mgr.resumen()
        print(f"\n{'═' * 47}")
        print(f"  TRANSCRIPCIÓN LISTA — MODO MANUAL")
        print(f"  Session          : {session_dir.name}")
        print(f"  Config           : {canal_id}")
        print(f"  Transcripciones  : {session_dir / 'chunks'}")
        print(f"{'═' * 47}")
        print(f"  Cero llamadas a Claude en esta sesión (modo: manual).")
        print(f"  Para cortar tus clips y guardarlos como ejemplos, usá:")
        print(f"    python entrenamiento/clip_manual.py --video {video_path} \\")
        print(f"      --inicio HH:MM:SS --fin HH:MM:SS \\")
        print(f"      --linea1 \"...\" --linea2 \"...\" \\")
        print(f"      --config {canal_id} --entrenamiento")
        print(f"{'═' * 47}\n")
        return

    # ── 5. Cierre: contenido_final.json + paso Revisión ─────
    n_pub, hubo_errores = _cerrar_sesion(mgr, session_dir, revisar)

    clips_dir = session_dir / "clips"
    n_clips   = len(list(clips_dir.glob("clip_*.mp4"))) if clips_dir.exists() else 0

    mgr.resumen()
    print(f"\n{'═' * 47}")
    print(f"  PIPELINE {'CON ERRORES' if hubo_errores else 'COMPLETADO'}")
    print(f"  Session          : {session_dir.name}")
    print(f"  Config           : {canal_id}")
    print(f"  Total clips      : {n_clips} generados ({n_pub} para publicar)")
    print(f"  Carpeta          : {clips_dir}")
    if hubo_errores:
        print(f"  Reintentar       : python pipeline.py --video \"{url}\" --session-id {session_dir.name} "
              f"--reintentar <paso> [--chunk <id>]")
    print(f"{'═' * 47}\n")
    if hubo_errores:
        sys.exit(1)


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description="IDEA MILLONARIA — Pipeline v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python pipeline.py --live  https://tiktok.com/@usuario/live --config zapatillas_peru\n"
            "  python pipeline.py --video https://tiktok.com/@usuario/live\n"
            "  python pipeline.py --test  stream_data/test/ --config zapatillas_peru\n"
        ),
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--live",  metavar="URL", help="TikTok Live en vivo")
    mode_group.add_argument("--video", metavar="URL", help="Video grabado / URL directa")
    mode_group.add_argument("--test",  metavar="DIR", help="Directorio de sesión existente")

    parser.add_argument(
        "--config", metavar="CANAL_ID", default=None,
        help="ID del canal en config/  (ej: zapatillas_peru).  Default: default.yaml",
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
             "(cero llamadas a Claude). Usar junto con entrenamiento/clip_manual.py --entrenamiento.",
    )
    parser.add_argument(
        "--session-id", metavar="ID", default=None,
        help="Solo --video: usa/retoma stream_data/<ID> sin preguntar (lo usa el backend web). "
             "También para videos locales: la sesión no se crea junto al archivo.",
    )
    parser.add_argument(
        "--reintentar", metavar="PASO", default=None, choices=PASOS_SESION + PASOS_CHUNK,
        help="Vuelve PASO (y los siguientes) a pendiente, borra lo que produjeron y retoma. "
             f"Pasos: {', '.join(PASOS_SESION + PASOS_CHUNK)}",
    )
    parser.add_argument(
        "--chunk", metavar="CHUNK_ID", default=None,
        help="Con --reintentar de un paso de chunk: solo ese chunk, o varios separados por coma "
             "(default: todos los chunks con ese paso en error)",
    )

    parser.add_argument(
        "--medios", action="store_true", default=False,
        help="Solo --video: el video es de TV/prensa (contenido de terceros, R-01). Requiere --sobre.",
    )
    parser.add_argument(
        "--sobre", metavar="ENTIDAD", default=None,
        help="Con --medios: de quién trata el video (id de contexto/entidades/, ej. fritz, o un nombre)",
    )

    args = parser.parse_args()
    if args.chunk and not args.reintentar:
        parser.error("--chunk solo tiene sentido junto con --reintentar")
    if args.medios and not args.video:
        parser.error("--medios solo funciona con --video")
    if args.medios and not args.sobre:
        parser.error("--medios requiere --sobre <entidad> (de quién trata el video)")
    if args.sobre and not args.medios:
        parser.error("--sobre solo tiene sentido junto con --medios")

    # Cargar configuración antes de cualquier procesamiento
    config, cfg = _load_config(args.config)

    if args.test:
        run_pipeline(
            cfg, config, test_dir=args.test, mode="test", revisar=args.revisar,
            reintentar=args.reintentar, chunk_reintentar=args.chunk,
        )
    elif args.live:
        run_pipeline(cfg, config, url=args.live, mode="live", revisar=args.revisar)
    else:
        usar_colab = args.colab
        if not usar_colab and os.environ.get("AI_PROVIDER", "").strip().lower() == "manual":
            usar_colab = True
            print(
                "[PIPELINE] AI_PROVIDER=manual detectado → forzando --colab "
                "(WhisperX local es demasiado lento para el flujo de prueba manual)"
            )
        run_pipeline(
            cfg, config, url=args.video, mode="video",
            revisar=args.revisar, usar_colab=usar_colab, manual=args.manual,
            session_id=args.session_id, reintentar=args.reintentar, chunk_reintentar=args.chunk,
            fuente_nueva=fuente_mod.nueva("medios", args.sobre, args.video) if args.medios else None,
        )


if __name__ == "__main__":
    main()
