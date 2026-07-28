"""
feedback.py — Interfaz de feedback manual para clips generados.

Uso:
  python feedback.py --session 20260609_203135
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import re
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv
load_dotenv()

STREAM_DATA  = Path("stream_data")
APRENDIZAJES = Path(__file__).parent / "aprendizajes"
MODEL        = "claude-sonnet-4-6"


# ─────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────

def _load_clips(session_dir: Path) -> list[dict]:
    clips = []
    for subdir in ("clips", "clips_custom"):
        d = session_dir / subdir
        if not d.exists():
            continue
        for mp4 in sorted(d.glob("*.mp4")):
            json_path = mp4.with_suffix(".json")
            metadata  = {}
            if json_path.exists():
                try:
                    metadata = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            clips.append({
                "mp4":      mp4,
                "nombre":   mp4.name,
                "metadata": metadata,
                "subdir":   subdir,
            })
    return clips


def _detect_canal_id(session_dir: Path) -> str | None:
    estado = session_dir / "pipeline_estado.json"
    if estado.exists():
        try:
            return json.loads(estado.read_text(encoding="utf-8")).get("config")
        except Exception:
            pass
    return None


def _build_user_content(canal_id: str, feedbacks: list[dict]) -> str:
    fecha = date.today().isoformat()
    lines = [f"Nicho: {canal_id}", f"Fecha: {fecha}", "", "Feedback recibido:"]
    for i, fb in enumerate(feedbacks, 1):
        lines.append(f"\nClip {i}: {fb['clip_name']}")
        lines.append(f"  Score sistema : {fb['score_sistema']}/10")
        lines.append(f"  Score usuario : {fb.get('score_usuario', 'N/A')}")
        lines.append(f"  Texto sistema : L1={fb['linea1']} | L2={fb['linea2']}")
        if fb.get("titulo_alt_l1") or fb.get("titulo_alt_l2"):
            lines.append(
                f"  Título alt    : L1={fb.get('titulo_alt_l1', '—')} "
                f"| L2={fb.get('titulo_alt_l2', '—')}"
            )
        lines.append(f"  Razón         : {fb.get('razon', 'Sin comentario')}")
    return "\n".join(lines)


def _call_claude(canal_id: str, feedbacks: list[dict]) -> dict:
    system_prompt = (
        "Eres un asistente que destila aprendizajes\n"
        "de contenido viral peruano en reglas concisas.\n\n"
        "Recibirás feedback de un creador de contenido\n"
        "sobre clips generados automáticamente.\n\n"
        "Tu tarea es analizar ese feedback y generar:\n"
        "1. Un registro completo para el historial\n"
        "2. Una regla resumida (máx 2 líneas) para\n"
        "   el archivo optimizado\n\n"
        "IMPORTANTE:\n"
        "- El aprendizaje es COMPLEMENTARIO, no reemplaza nada existente\n"
        "- La regla debe ser accionable y específica\n"
        "- Si el feedback es muy específico de un clip\n"
        "  y no generalizable → indicarlo claramente\n"
        "- Responde SOLO en JSON válido\n\n"
        "FORMATO:\n"
        "{\n"
        '  "registro_completo": "texto para historial...",\n'
        '  "regla_resumida": "texto corto para optimizado...",\n'
        '  "es_generalizable": true,\n'
        '  "razon": "por qué es o no generalizable"\n'
        "}"
    )
    client   = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": _build_user_content(canal_id, feedbacks)}],
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r'^```(?:json)?\n?', '', raw)
        raw = re.sub(r'\n?```$', '', raw)
    raw = raw.strip()
    m   = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"Respuesta no es JSON válido: {raw[:300]}")
    return json.loads(m.group())


# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="feedback.py")
    parser.add_argument("--session", required=True, metavar="SESSION_ID")
    args = parser.parse_args()

    session_dir = STREAM_DATA / args.session
    if not session_dir.exists():
        print(f"❌ Sesión no encontrada: {session_dir}")
        sys.exit(1)

    canal_id = _detect_canal_id(session_dir)
    if not canal_id:
        try:
            canal_id = input("Canal ID no detectado. Ingresá el canal_id (ej: zapatillas_peru): ").strip()
        except EOFError:
            canal_id = ""
        if not canal_id:
            canal_id = "default"

    clips = _load_clips(session_dir)
    if not clips:
        print(f"❌ No se encontraron clips en {session_dir}/clips/ ni clips_custom/")
        sys.exit(1)

    border = "═" * 40
    print(f"\n{border}")
    print(f"  FEEDBACK — IDEA MILLONARIA")
    print(f"  Sesión: {args.session}")
    print(f"  Canal : {canal_id}")
    print(f"  Clips encontrados: {len(clips)}")
    print(f"{border}\n")

    feedbacks = []

    for i, clip in enumerate(clips, 1):
        meta     = clip["metadata"]
        nombre   = clip["nombre"]
        score    = meta.get("score", "?")
        linea1   = meta.get("texto_linea1", "—")
        linea2   = meta.get("texto_linea2", "—")
        duracion = meta.get("duracion_segundos", "?")
        inicio   = meta.get("inicio")
        fin      = meta.get("fin")
        rango_str = (
            f"{inicio} → {fin} ({duracion}s)" if inicio and fin
            else f"({duracion}s)"
        )

        print(f"  {'─'*38}")
        print(f"  Clip {i}/{len(clips)} — {nombre}")
        print(f"  Score sistema : {score}/10")
        print(f"  Línea 1       : {linea1}")
        print(f"  Línea 2       : {linea2}")
        print(f"  Rango         : {rango_str}")
        print(f"  {'─'*38}")

        try:
            resp = input("  ¿Dar feedback a este clip? [s/N]: ").strip().lower()
        except EOFError:
            resp = "n"

        if resp not in ("s", "si", "sí", "y", "yes"):
            print()
            continue

        fb = {
            "clip_name":    nombre,
            "score_sistema": score,
            "linea1":        linea1,
            "linea2":        linea2,
        }

        try:
            score_u = input("  Tu evaluación [1-10] (Enter para omitir): ").strip()
            if score_u:
                fb["score_usuario"] = score_u

            razon = input("  ¿Por qué? (describe lo que viste): ").strip()
            if razon:
                fb["razon"] = razon

            alt_l1 = input("  ¿Título alternativo línea 1? (Enter omitir): ").strip()
            if alt_l1:
                fb["titulo_alt_l1"] = alt_l1

            alt_l2 = input("  ¿Título alternativo línea 2? (Enter omitir): ").strip()
            if alt_l2:
                fb["titulo_alt_l2"] = alt_l2

        except EOFError:
            pass

        feedbacks.append(fb)
        print()

    if not feedbacks:
        print("[FEEDBACK] Sin feedbacks dados — saliendo sin cambios.\n")
        sys.exit(0)

    # ── Llamar a Claude ──────────────────────────────────────
    print(f"[FEEDBACK] Analizando {len(feedbacks)} feedback(s) con Claude...")
    try:
        resultado = _call_claude(canal_id, feedbacks)
    except Exception as e:
        print(f"[FEEDBACK] ❌ Error al llamar a Claude: {e}")
        sys.exit(1)

    registro_completo = resultado.get("registro_completo", "")
    regla_resumida    = resultado.get("regla_resumida", "")
    es_generalizable  = resultado.get("es_generalizable", False)
    razon_claude      = resultado.get("razon", "")

    print(f"\n{border}")
    print(f"  PROPUESTA DE APRENDIZAJE")
    print(f"{border}\n")
    print(f"REGISTRO PARA HISTORIAL:\n{registro_completo}\n")
    print(f"REGLA PARA OPTIMIZADO:\n{regla_resumida}\n")
    print(f"¿Es generalizable?: {'Sí' if es_generalizable else 'No'}")
    print(f"Razón: {razon_claude}\n")
    print(f"{border}")

    try:
        aprobar = input("¿Aprobar y guardar? [S/n]: ").strip().lower()
    except EOFError:
        aprobar = "s"

    if aprobar in ("n", "no"):
        print("[FEEDBACK] Cancelado — sin cambios.\n")
        sys.exit(0)

    try:
        editar = input("¿Editar regla optimizada? [s/N]: ").strip().lower()
    except EOFError:
        editar = "n"

    if editar in ("s", "si", "sí", "y", "yes"):
        try:
            nueva_regla = input("Nueva versión de la regla: ").strip()
            if nueva_regla:
                regla_resumida = nueva_regla
        except EOFError:
            pass

    # ── Guardar en archivos ──────────────────────────────────
    fecha_hoy  = date.today().isoformat()
    hist_path  = APRENDIZAJES / f"{canal_id}.md"
    opt_path   = APRENDIZAJES / f"{canal_id}_optimizado.md"
    reglas_agregadas = 0

    appendix = (
        f"\n---\n\n"
        f"### {fecha_hoy} — Feedback manual sesión {args.session}\n"
        f"{registro_completo}\n"
    )
    if hist_path.exists():
        hist_path.write_text(
            hist_path.read_text(encoding="utf-8") + appendix,
            encoding="utf-8",
        )
        print(f"\n  ✅ aprendizajes/{canal_id}.md actualizado")
    else:
        hist_path.write_text(
            f"# Aprendizajes — Nicho: {canal_id}\n" + appendix,
            encoding="utf-8",
        )
        print(f"\n  ✅ aprendizajes/{canal_id}.md creado")

    if es_generalizable:
        seccion = "## Aprendizajes de feedback"
        if opt_path.exists():
            contenido_opt = opt_path.read_text(encoding="utf-8").rstrip()
            if seccion in contenido_opt:
                contenido_opt += f"\n- {regla_resumida}\n"
            else:
                contenido_opt += f"\n\n{seccion}\n- {regla_resumida}\n"
            opt_path.write_text(contenido_opt, encoding="utf-8")
        else:
            opt_path.write_text(
                f"# Reglas activas — {canal_id}\n\n{seccion}\n- {regla_resumida}\n",
                encoding="utf-8",
            )
        print(f"  ✅ aprendizajes/{canal_id}_optimizado.md")
        print(f"     actualizado (regla generalizable)")
        reglas_agregadas = 1
    else:
        print(f"  ⚠️  Regla no generalizable — solo en historial")

    print(f"\n{border}")
    print(f"  FEEDBACK COMPLETADO")
    print(f"  Clips revisados  : {len(clips)}")
    print(f"  Feedbacks dados  : {len(feedbacks)}")
    print(f"  Reglas agregadas : {reglas_agregadas}")
    print(f"{border}\n")


if __name__ == "__main__":
    main()
