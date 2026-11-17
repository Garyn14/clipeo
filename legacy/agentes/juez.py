"""
juez.py — Único filtro de calidad del chunk: decide qué rangos del Agente 2 se publican y
con qué título, contra la MEMORIA DEL NICHO (investigacion/<canal_id>/referencias.yaml:
clips reales medidos en TikTok) y las CORRECCIONES DEL EDITOR (correcciones.jsonl, lo que
se aprobó/editó/descartó en la Revisión).

Flujo por chunk: A1 detecta amplio → A2 ajusta bordes (sin juzgar calidad) → JUEZ decide →
A3 escribe el copy solo de los aprobados → corte. El juez ve todos los candidatos juntos y
decide de forma estructurada: tipo de momento viral, qué está en juego, a qué referencias
reales se parece. Sin memoria para el nicho, el paso se omite y el A3 decide como antes.

Uso interno (pipeline.py, paso "juez"):
    from agentes.juez import run_juez
    resultado = run_juez(rangos, transcripcion=texto, config=config,
                         session_dir=session_dir, chunk_dir=chunk_dir)
"""

import json
import re
from pathlib import Path

from agentes.agent3_viral_scorer import _extract_clip, _parse_segments
from ai_client import AIRetryableError, get_client
from investigacion import comun

MODEL = "claude-sonnet-4-6"

JUEZ_PROMPT = """Eres el JUEZ editorial de una cuenta de clips de un nicho de redes sociales.
Decides qué momentos de un video se publican como clip. Eres el ÚNICO filtro de calidad: los
pasos anteriores buscaron amplio a propósito, así que muchos candidatos no van a servir.
Tu criterio NO es tu opinión general: es la MEMORIA DEL NICHO de abajo, construida con clips
reales medidos en TikTok (outlier = cuántas veces rindió lo normal de su cuenta).

MEMORIA DEL NICHO:
{memoria}
{correcciones}
CÓMO DECIDES (para CADA candidato, en orden):
1. tipo: a cuál de tipos_que_funcionan de la memoria pertenece, o "ninguno".
   Anuncios de tiendas, pitch de productos, precios, aperturas, logística o instrucciones
   internas sin conflicto ni emoción son "ninguno" aunque mencionen cifras. El tipo que
   sugiere el detector es solo una pista.
2. en_juego: qué está en juego en una frase (dinero de alguien humilde, el orgullo de alguien,
   una relación, un reto…). Si no hay nada en juego, dilo.
3. parecidos: los 2 títulos de la memoria más parecidos a este momento (cópialos tal cual),
   o [] si es "ninguno".
4. publicar: true SOLO si el tipo no es "ninguno", hay algo en juego y el momento se entiende
   solo. No hay tope de clips: publica todos los que cumplan, ninguno si ninguno cumple.
5. fuerza: 1–10 comparando con los outliers de los parecidos (no con tu intuición). Un
   "ninguno" no pasa de 4.
6. titulo: 2 líneas con la formula_titulo, NOMBRANDO al personaje. Va quemado en el video:
   cada línea entre 4 y 7 palabras, con peso parecido (diferencia máxima de 2 palabras); el
   remate o el emoji va en la línea 2. Para saber quién habla usa,
   en este orden: los HABLANTES IDENTIFICADOS, el canal y el título del video (el dueño del
   canal suele ser quien habla y quien regala/vende/reta). Un hablante "posible" es solo una
   pista: si nombra a un personaje distinto del dueño del CANAL, prevalece el dueño del canal
   salvo que la transcripción lo contradiga de forma explícita (ej. alguien lo llama por su
   nombre). Mencionar a otro personaje no lo convierte en quien habla.
   Corrige palabras mal transcritas; nunca copies texto ilegible.

Responde SOLO JSON válido, un objeto por candidato y en el mismo orden:
{{"candidatos": [{{"n": 1, "tipo": "...", "en_juego": "...", "parecidos": ["...", "..."],
  "publicar": true, "fuerza": 8, "linea1": "...", "linea2": "...", "por_que": "una frase"}}]}}"""

_BLOQUE_CORRECCIONES = """
CORRECCIONES DEL EDITOR (decisiones reales en la revisión; pesan tanto como la memoria —
si el editor descartó o corrigió algo parecido, ajusta tu criterio):
{lineas}
"""


def _leer_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _contexto_video(session_dir: Path, chunk_dir: Path) -> str:
    meta = _leer_json(session_dir / "metadata.json")
    lineas = [
        f"VIDEO: «{meta.get('title') or meta.get('fulltitle') or '(sin título)'}»",
        f"CANAL: {meta.get('uploader') or meta.get('channel') or '(desconocido)'}",
    ]
    speakers = _leer_json(chunk_dir / "speaker_map.json")
    identificados = [
        f"  {spk}: {info.get('nombre')} ({info.get('estado')}, {info.get('confianza')})"
        for spk, info in speakers.items()
        if isinstance(info, dict) and info.get("nombre")
    ]
    if identificados:
        lineas.append("HABLANTES IDENTIFICADOS:\n" + "\n".join(identificados))
    return "\n".join(lineas)


def _parsear(raw: str, n_esperados: int) -> list[dict]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group()) if m else None
    except json.JSONDecodeError:
        data = None
    candidatos = (data or {}).get("candidatos")
    if not isinstance(candidatos, list):
        raise AIRetryableError(f"[JUEZ] respuesta sin JSON de candidatos: {raw[:200]}")
    por_n = {c.get("n"): c for c in candidatos if isinstance(c, dict)}
    faltan = [n for n in range(1, n_esperados + 1) if n not in por_n]
    if faltan:
        raise AIRetryableError(f"[JUEZ] faltan veredictos para los candidatos {faltan}")
    return [por_n[n] for n in range(1, n_esperados + 1)]


def system_prompt(canal_id: str) -> str | None:
    """Prompt del juez con la memoria y las correcciones del nicho, o None sin memoria."""
    memoria = comun.cargar_memoria(canal_id)
    if memoria is None:
        return None
    correcciones = comun.cargar_correcciones(canal_id)
    bloque = _BLOQUE_CORRECCIONES.format(lineas=correcciones) if correcciones else ""
    return JUEZ_PROMPT.format(memoria=memoria, correcciones=bloque)


def run_juez(
    rangos: list[dict],
    *,
    transcripcion: str,
    config: dict,
    session_dir: Path,
    chunk_dir: Path,
) -> dict:
    """
    Juzga los rangos conservados por el A2 y escribe chunk_dir/juez.json (una decisión por
    candidato, con su rango completo — es lo que consume el A3 en modo copy).
    Devuelve el dict de resultado del paso ({"salidas", "nota"} u {"omitido", "nota"}).
    """
    canal_id = (config.get("meta") or {}).get("id", "default")
    system = system_prompt(canal_id)
    if system is None:
        ruta = comun.ruta_memoria(canal_id).relative_to(comun.RAIZ).as_posix()
        return {"omitido": True, "nota": f"nicho sin memoria ({ruta})"}
    candidatos = [r for r in rangos if r.get("conservar")]
    if not candidatos:
        return {"omitido": True, "nota": "sin candidatos"}

    segmentos = _parse_segments(transcripcion)
    bloques = [_contexto_video(session_dir, chunk_dir), ""]
    for n, r in enumerate(candidatos, 1):
        inicio, fin = r.get("inicio", "00:00"), r.get("fin", "00:00")
        pico = r.get("pico_original") or {}
        pista = ", ".join(x for x in (
            f"tipo sugerido: {pico['tipo']}" if pico.get("tipo") else "",
            f"en juego: {pico['en_juego']}" if pico.get("en_juego") else "",
        ) if x)
        texto = _extract_clip(segmentos, inicio, fin) or "(sin texto en el rango)"
        bloques.append(
            f"=== CANDIDATO {n} ({inicio} → {fin}, {r.get('duracion_segundos')}s)"
            + (f" — {pista}" if pista else "") + f" ===\n{texto}\n"
        )

    print(f"[JUEZ] {len(candidatos)} candidato(s) contra la memoria de {canal_id}...")
    resp = get_client().messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": "\n".join(bloques)}],
    )
    veredictos = _parsear(resp.content[0].text, len(candidatos))

    decisiones = []
    for n, (r, v) in enumerate(zip(candidatos, veredictos), 1):
        publicar = bool(v.get("publicar"))
        marca = "✅" if publicar else "❌"
        print(f"  {marca} {v.get('fuerza')}/10 [{v.get('tipo')}] {v.get('linea1', '')} — {v.get('por_que', '')}")
        decisiones.append({
            "n": n,
            "inicio": r.get("inicio"),
            "fin": r.get("fin"),
            "publicar": publicar,
            "linea1": v.get("linea1"),
            "linea2": v.get("linea2"),
            **{k: v.get(k) for k in ("tipo", "en_juego", "parecidos", "fuerza", "por_que")},
            "rango": r,
        })

    juez_path = chunk_dir / "juez.json"
    juez_path.write_text(
        json.dumps({"memoria": comun.ruta_memoria(canal_id).relative_to(comun.RAIZ).as_posix(),
                    "decisiones": decisiones}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n_pub = sum(1 for d in decisiones if d["publicar"])
    return {"salidas": [juez_path], "nota": f"{n_pub}/{len(decisiones)} para publicar"}


def bloque_juez(decision: dict) -> dict:
    """El veredicto resumido que viaja en cada item de contenido.json."""
    return {k: decision.get(k) for k in ("tipo", "en_juego", "parecidos", "fuerza", "por_que", "linea1", "linea2")}
