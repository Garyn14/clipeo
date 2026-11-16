"""
contexto_refresh.py — Busca noticias recientes de una entidad via web search
y permite aprobar eventos para guardar en contexto/eventos/.

DEPRECADO EN LA PRÁCTICA (2026-07-31): este script gasta API real de
Anthropic (la búsqueda web corre dentro de la llamada a Claude). Sigue
funcionando, pero para este tipo de investigación/curación hoy se prefiere
que un agente de Claude Code lo haga directo en sesión con su propio
WebSearch, sin gastar ANTHROPIC_API_KEY, guardando el resultado en el mismo
formato de archivo — ver .claude/skills/seo-refresh/SKILL.md como ejemplo
de este patrón (memoria: preferencia-claude-code-reemplaza-scripts-de-api).

Uso:
    python contexto_refresh.py fritz
    python contexto_refresh.py fritz --max-busquedas 8
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import re
import argparse
from datetime import date, datetime
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv
load_dotenv()

MODEL = "claude-sonnet-4-6"
CONTEXTO_DIR = Path(__file__).parent


def _load_entity(entity_id: str) -> dict:
    path = CONTEXTO_DIR / "entidades" / f"{entity_id}.yaml"
    if not path.exists():
        print(f"❌ No se encontró entidad: {path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _find_nichos(entity_id: str) -> list[dict]:
    nichos_dir = CONTEXTO_DIR / "nichos"
    if not nichos_dir.exists():
        return []
    nichos = []
    for path in nichos_dir.glob("*.yaml"):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        entidades = data.get("nicho", {}).get("entidades", [])
        if entity_id in entidades:
            nichos.append(data)
    return nichos


def _build_system_prompt(entity: dict, nichos: list[dict], today: str) -> str:
    ent  = entity.get("entidad", {})
    lore = entity.get("lore", {})

    nombre      = ent.get("nombre", ent.get("id", ""))
    nombre_real = ent.get("nombre_real", "")
    plataformas = ", ".join(ent.get("plataformas", []))
    descripcion = lore.get("descripcion", "").strip()

    nicho_desc = ""
    if nichos:
        nicho      = nichos[0].get("nicho", {})
        nicho_desc = (
            f"\nECOSISTEMA: {nicho.get('descripcion', '')}"
            f"\nNICHO ID: {nicho.get('id', '')}"
        )

    return f"""Eres un investigador de contenido viral para el ecosistema de zapatillas peruanas.

HOY: {today}

ENTIDAD: {nombre} ({nombre_real})
PLATAFORMAS: {plataformas}

PERFIL:
{descripcion}
{nicho_desc}

TAREA:
Busca noticias, eventos y novedades RECIENTES (últimas 4 semanas) sobre {nombre}.
Enfócate en:
- Polémicas, confrontaciones o rivalidades nuevas
- Eventos virales o logros destacados
- Cambios en el negocio, alianzas o colaboraciones
- Menciones en medios o redes sociales

Luego devuelve UN SOLO bloque JSON con esta estructura exacta:

{{
  "hallazgos": [
    {{
      "titulo": "Título breve del evento (máx 80 chars)",
      "descripcion": "Descripción detallada de lo que ocurrió",
      "fecha_aproximada": "2026-06-20",
      "relevancia": "Por qué esto es importante para el contenido viral",
      "fuente": "URL o nombre de la fuente"
    }}
  ]
}}

Sé conciso. Máximo 3 hallazgos de alta relevancia. Prefiere calidad sobre cantidad.
Descripción de cada hallazgo: máximo 3 líneas.

Si no encuentras noticias relevantes recientes, devuelve {{"hallazgos": []}}.
IMPORTANTE: Responde SOLO con el JSON válido, sin texto adicional antes ni después."""


def _extract_json(text: str) -> dict | None:
    m = re.search(r'\{"hallazgos"\s*:\s*\[.*?\]\s*\}', text, re.DOTALL)
    if not m:
        m = re.search(r'\{.*\}', text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _run_web_search(system_prompt: str, entity_name: str, max_uses: int) -> str:
    client = anthropic.Anthropic()

    messages = [{"role": "user", "content": f"Busca noticias recientes sobre {entity_name}."}]

    # Server-side web search: the API runs the tool loop internally.
    # pause_turn means the server hit its iteration limit — re-send to continue.
    for iteration in range(10):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1200,
            system=system_prompt,
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": max_uses,
            }],
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            return ""

        if response.stop_reason == "pause_turn":
            print(f"  [pausa del servidor, continuando iteración {iteration + 1}]")
            messages.append({"role": "assistant", "content": response.content})
            # Do NOT add a new user message — the trailing server_tool_use block
            # signals the API to resume automatically.
            continue

        # Unexpected stop reason
        print(f"  ⚠️  stop_reason inesperado: {response.stop_reason}")
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""

    print("  ⚠️  Máximo de iteraciones del cliente alcanzado")
    return ""


def _save_hallazgo(hallazgo: dict, entity_id: str, nicho_id: str | None) -> Path:
    today     = date.today()
    month_dir = CONTEXTO_DIR / "eventos" / today.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    ts    = datetime.now().strftime("%H%M%S")
    fname = f"refresh_{entity_id}_{ts}.yaml"
    path  = month_dir / fname

    data = {
        "evento": {
            "tipo":           "refresh_noticia",
            "entidad":        entity_id,
            "nicho":          nicho_id,
            "fecha_evento":   hallazgo.get("fecha_aproximada", str(today)),
            "fecha_registro": str(today),
            "titulo":         hallazgo.get("titulo", ""),
            "descripcion":    hallazgo.get("descripcion", "").strip(),
            "relevancia":     hallazgo.get("relevancia", "").strip(),
            "fuente":         hallazgo.get("fuente", ""),
        }
    }

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return path


def main():
    parser = argparse.ArgumentParser(
        description="Busca noticias recientes de una entidad y guarda los eventos aprobados."
    )
    parser.add_argument("entidad", help="ID de la entidad (ej: fritz)")
    parser.add_argument(
        "--max-busquedas", type=int, default=3,
        help="Máximo de búsquedas web que Claude puede hacer (default: 3)",
    )
    args = parser.parse_args()

    entity_id = args.entidad
    today     = str(date.today())

    print(f"\n[REFRESH] Entidad      : {entity_id}")
    print(f"[REFRESH] Fecha        : {today}")
    print(f"[REFRESH] Búsquedas    : hasta {args.max_busquedas}")
    print(f"[REFRESH] {'─'*40}\n")

    entity  = _load_entity(entity_id)
    nichos  = _find_nichos(entity_id)
    nombre  = entity.get("entidad", {}).get("nombre", entity_id)
    nicho_id = nichos[0].get("nicho", {}).get("id") if nichos else None

    print(f"[REFRESH] Nombre       : {nombre}")
    print(f"[REFRESH] Nicho        : {nicho_id or '(sin nicho)'}")
    print(f"[REFRESH] Buscando noticias recientes...\n")

    system_prompt = _build_system_prompt(entity, nichos, today)
    raw = _run_web_search(system_prompt, nombre, args.max_busquedas)

    if not raw:
        print("[REFRESH] ❌ No se obtuvo respuesta de la API")
        sys.exit(1)

    data = _extract_json(raw)
    if data is None:
        print("[REFRESH] ❌ No se pudo parsear JSON de la respuesta:")
        print(raw[:500])
        sys.exit(1)

    hallazgos = data.get("hallazgos", [])

    if not hallazgos:
        print("[REFRESH] ℹ️  No se encontraron noticias relevantes recientes.")
        sys.exit(0)

    print(f"[REFRESH] {'─'*40}")
    print(f"[REFRESH] {len(hallazgos)} hallazgo(s) encontrado(s).\n")

    guardados = 0
    for i, h in enumerate(hallazgos, 1):
        print(f"  [{i}/{len(hallazgos)}] {h.get('titulo', '(sin título)')}")
        print(f"  Fecha     : {h.get('fecha_aproximada', '?')}")
        print(f"  Fuente    : {h.get('fuente', '?')}")
        print(f"  Relevancia: {h.get('relevancia', '')}")
        print(f"  Descripción:")
        for line in h.get("descripcion", "").strip().splitlines():
            print(f"    {line}")
        print()

        try:
            resp = input("  ¿Guardar este hallazgo? [S/n] ").strip().lower()
        except EOFError:
            resp = "n"

        if resp in ("", "s", "y", "si", "sí", "yes"):
            path = _save_hallazgo(h, entity_id, nicho_id)
            print(f"  ✅ Guardado: {path.name}\n")
            guardados += 1
        else:
            print(f"  ⏭️  Descartado\n")

    print(f"[REFRESH] {'─'*40}")
    print(f"[REFRESH] ✅ {guardados}/{len(hallazgos)} hallazgos guardados")
    if guardados:
        print(f"[REFRESH] Directorio: contexto/eventos/{date.today().strftime('%Y-%m')}/")
    print()


if __name__ == "__main__":
    main()
