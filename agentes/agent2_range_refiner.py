"""
===========================================
  IDEA MILLONARIA - Pipeline Paso 3
  Agent 2: Refinador de Rangos de Clips
===========================================

Lee picos.json, extrae contexto de ±45s por pico,
llama a Claude para refinar el rango exacto del clip
y guarda los resultados en rangos.json.

Uso:
  python agent2_range_refiner.py stream_data/<session_id>/picos.json
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import re
import anthropic
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.utils import _timestamp_to_seconds, _seconds_to_timestamp, _parse_segments

# ─────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────
MODEL = "claude-sonnet-4-6"

# Instrucción que se añade al prompt base para el modo agrupado
_AGRUPADO_SUFFIX = """

INSTRUCCIÓN ESPECIAL — MODO AGRUPADO:
Recibirás TODOS los picos del chunk juntos.
Analiza si alguno se solapa o cuenta la misma historia — en ese caso
fusiónalos en un solo rango más completo o descarta el redundante.
Devuelve un rango por cada momento DISTINTO que valga la pena clipear.

FORMATO DE RESPUESTA (modo agrupado) — solo JSON válido:
{
  "rangos": [
    {
      "pico_timestamp": "10:23",
      "conservar": true,
      "inicio": "00:10:11",
      "fin": "00:12:00",
      "duracion_segundos": 109,
      "razon": "...",
      "gancho": "..."
    },
    {
      "pico_timestamp": "14:06",
      "conservar": false,
      "razon": "no hay contexto suficiente"
    }
  ]
}
"""
# ─────────────────────────────────────────


def _extract_context(
    segments: list[tuple[int, str]],
    center_secs: int,
    antes: int,
    despues: int,
) -> str:
    """
    Extrae líneas dentro de [center - antes, center + despues].
    """
    start = max(0, center_secs - antes)
    end   = center_secs + despues
    lines = [line for secs, line in segments if start <= secs <= end]
    return "\n".join(lines)


def _call_claude(
    client: anthropic.Anthropic,
    pico: dict,
    context: str,
    prompt: str,
    antes: int,
    despues: int,
) -> dict:
    """Llama a Claude con el contexto del pico y retorna el dict de refinamiento."""
    user_message = (
        f"Momento marcado:\n"
        f"  Timestamp : {pico.get('timestamp')}\n"
        f"  Razón A1  : {pico.get('razon')}\n"
        f"  Confianza : {pico.get('confianza')}\n\n"
        f"Contexto (-{antes}s/+{despues}s):\n{context}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"  ⚠️  Respuesta no es JSON válido: {raw[:200]}")
        return {"conservar": False, "razon": "respuesta no parseable"}

    try:
        result = json.loads(m.group())
        # Normalize timestamps in case the LLM returns e.g. "00::10"
        for key in ("inicio", "fin"):
            if key in result:
                result[key] = re.sub(r":+", ":", str(result[key]).strip())
        return result
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Error parseando JSON: {e}")
        return {"conservar": False, "razon": f"JSON inválido: {e}"}


def _call_claude_agrupado(
    client: anthropic.Anthropic,
    picos_con_contexto: list[tuple[dict, str]],
    prompt: str,
    antes: int,
    despues: int,
) -> list[dict]:
    """
    Una sola llamada con todos los picos del chunk.
    Retorna lista de rangos (puede ser menor que picos si hubo fusiones).
    """
    bloques = []
    for i, (pico, ctx) in enumerate(picos_con_contexto, 1):
        ctx_label = ctx if ctx.strip() else "(sin contexto en transcripción)"
        bloques.append(
            f"{'─'*40}\n"
            f"PICO {i} [{pico.get('timestamp')}]\n"
            f"Razón     : {pico.get('razon', '')}\n"
            f"Confianza : {pico.get('confianza', '')}\n"
            f"Tipo      : {pico.get('tipo', '')}\n\n"
            f"Contexto (-{antes}s/+{despues}s):\n{ctx_label}"
        )

    user_message = (
        f"Picos a refinar: {len(picos_con_contexto)}\n\n"
        + "\n\n".join(bloques)
    )

    agrupado_prompt = prompt + _AGRUPADO_SUFFIX

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{
            "type": "text",
            "text": agrupado_prompt,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()

    # Buscar el objeto {"rangos": [...]}
    m = re.search(r'\{"rangos"\s*:\s*\[.*?\]\s*\}', raw, re.DOTALL)
    if not m:
        m = re.search(r'\{.*\}', raw, re.DOTALL)

    if not m:
        print(f"  ⚠️  Respuesta no parseable: {raw[:300]}")
        return []

    try:
        result = json.loads(m.group())
        rangos = result.get("rangos", [])
        for rango in rangos:
            for key in ("inicio", "fin"):
                if key in rango:
                    rango[key] = re.sub(r":+", ":", str(rango[key]).strip())
        return rangos
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Error parseando JSON agrupado: {e}")
        return []


def run_agent(picos_path: str, config: dict) -> list[dict]:
    """
    Lee picos.json y transcripcion_completa.txt, refina cada pico y guarda rangos.json.
    Toda lógica de negocio proviene del config dict.
    """
    picos_file = Path(picos_path)
    if not picos_file.exists():
        print(f"[AGENT2] ❌ No se encontró: {picos_file}")
        sys.exit(1)

    session_dir   = picos_file.parent
    transcripcion = session_dir / "transcripcion_completa.txt"

    if not transcripcion.exists():
        print(f"[AGENT2] ❌ No se encontró: {transcripcion}")
        sys.exit(1)

    prompt   = config["refinamiento"]["prompt"]
    antes    = config["refinamiento"]["contexto_antes_segundos"]
    despues  = config["refinamiento"]["contexto_despues_segundos"]
    dur_min  = config["refinamiento"]["duracion_minima_segundos"]
    dur_max  = config["refinamiento"]["duracion_maxima_segundos"]

    picos    = json.loads(picos_file.read_text(encoding="utf-8")).get("picos", [])
    text     = transcripcion.read_text(encoding="utf-8")
    segments = _parse_segments(text)

    print(f"\n[AGENT2] Sesión   : {session_dir.name}")
    print(f"[AGENT2] Picos    : {len(picos)}")
    print(f"[AGENT2] Contexto : -{antes}s / +{despues}s  |  duración {dur_min}–{dur_max}s")
    print(f"[AGENT2] {'─'*40}\n")

    client = anthropic.Anthropic()

    # Preparar todos los picos con su contexto
    picos_con_contexto = []
    for pico in picos:
        ts          = pico.get("timestamp", "00:00")
        center_secs = _timestamp_to_seconds(ts)
        ctx         = _extract_context(segments, center_secs, antes, despues)
        picos_con_contexto.append((pico, ctx))

    print(f"[AGENT2] Refinamiento agrupado — {len(picos)} picos en 1 llamada")

    rangos_raw = _call_claude_agrupado(client, picos_con_contexto, prompt, antes, despues)

    # Mapear pico_original por timestamp para enriquecer cada rango
    pico_by_ts = {p.get("timestamp"): p for p in picos}

    rangos = []
    for rango in rangos_raw:
        pico_ts              = rango.pop("pico_timestamp", None)
        rango["pico_original"] = pico_by_ts.get(pico_ts, {})
        rangos.append(rango)

    conservados = sum(1 for r in rangos if r.get("conservar"))
    descartados = sum(1 for r in rangos if not r.get("conservar"))
    fusionados  = max(0, len(picos) - len(rangos))

    print(f"[AGENT2] Resultado: {conservados} rangos conservados, {descartados} descartados")
    if fusionados:
        print(f"         ({fusionados} fusionados por solapamiento)")
    print()

    for rango in rangos:
        if rango.get("conservar"):
            inicio = rango.get("inicio", "?")
            fin    = rango.get("fin", "?")
            dur    = rango.get("duracion_segundos", "?")
            print(f"  ✅ Conservado — {inicio} → {fin} ({dur}s)")
            print(f"     Gancho: {rango.get('gancho', '')}")
        else:
            print(f"  ❌ Descartado — {rango.get('razon', '')}")
    print()

    output_path = session_dir / "rangos.json"
    output_path.write_text(
        json.dumps({"rangos": rangos}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[AGENT2] {'─'*40}")
    print(f"[AGENT2] ✅ {conservados} conservados  |  ❌ {descartados} descartados")
    print(f"[AGENT2] Rangos guardados en {output_path}\n")

    return rangos


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUso: python agent2_range_refiner.py <picos.json> [canal_id]")
        print("Ejemplo: python agent2_range_refiner.py stream_data/test/picos.json papi_jhos\n")
        sys.exit(1)

    from contexto.config_loader import ConfigLoader

    canal_id = sys.argv[2] if len(sys.argv) >= 3 else None
    cfg      = ConfigLoader(config_dir=str(Path(__file__).parent.parent / "config"))
    config   = cfg.load(canal_id)

    print(f"[AGENT2] Canal : {cfg.get('meta', 'id')}  (config: {cfg.loaded_file.name})")

    run_agent(sys.argv[1], config)
