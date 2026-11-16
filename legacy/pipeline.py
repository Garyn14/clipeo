"""
===========================================
  IDEA MILLONARIA — Pipeline v2.0
  Orquestador: Captura + ConfigLoader + 4 Agentes
===========================================

Uso:
  python pipeline.py --video https://tiktok.com/@usuario/live  [--config canal_id]
  python pipeline.py --test  stream_data/test/                 [--config zapatillas_peru]

  --config omitido → usa config/default.yaml
"""

import os
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
    mode: str = "video",
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

    else:
        raise ValueError(f"Modo no soportado: {mode!r} (usar 'video' o 'test')")


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
            "  python pipeline.py --video https://tiktok.com/@usuario/live\n"
            "  python pipeline.py --test  stream_data/test/ --config zapatillas_peru\n"
        ),
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
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

    args = parser.parse_args()

    # Cargar configuración antes de cualquier procesamiento
    config, cfg = _load_config(args.config)

    if args.test:
        run_pipeline(cfg, config, test_dir=args.test, mode="test", revisar=args.revisar)
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
        )
