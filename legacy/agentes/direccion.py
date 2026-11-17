"""
direccion.py — Dirección editorial (CLIP-31): piensa el corte de cada candidato antes del juez.

Por cada rango conservado por el A2 decide, con la memoria del nicho:
  - dónde arranca el clip: donde aparece lo que está en juego ("arrancar en el conflicto");
  - qué tramos de relleno se recortan (muletillas, pausas, presentación, logística);
  - estructura: "lineal" o "gancho_primero" (2–4 s del remate al inicio y luego la historia).

Devuelve un plan de edición por candidato en `rango["plan_edicion"]` = {estructura, segmentos, por_que}, con los
segmentos en orden de montaje. El Agente 4 ya sabe montar varios segmentos (`_cut_compilation`), así que este paso
solo decide; nunca corta video.

Un plan inválido (tiempos fuera del rango, tramos muy cortos, duración fuera de los límites del config) se descarta
y el candidato sigue con su rango original: este paso nunca rompe el pipeline.

Encendida por defecto (decisión del operador, 2026-11-17: demo 3/3 mejor y +recall del juez sin perder precisión).
Se apaga con DIRECCION_EDITORIAL=0; apagada, el pipeline queda como antes. Corre dentro del paso "juez" (pipeline.py).
"""

from __future__ import annotations

import json
import os
import re

from ai_client import get_client
from core.utils import _parse_segments, _seconds_to_timestamp, _timestamp_to_seconds
from investigacion import comun

MODEL = "claude-sonnet-4-6"
MARGEN_S = 20          # la dirección puede mover los bordes hasta ±20 s del rango del A2
MIN_SEGMENTO_S = 2
GANCHO_MIN_S, GANCHO_MAX_S = 2, 5

PROMPT = """Eres el DIRECTOR EDITORIAL de una cuenta de clips de un nicho de redes sociales.
No decides SI un momento se publica (eso lo hace el juez): decides CÓMO se corta para que funcione.

MEMORIA DEL NICHO (qué funciona y por qué):
{memoria}

Para CADA candidato recibes su transcripción con ±{margen} s de margen. Decide:
1. ARRANQUE: el clip empieza donde se escucha lo que está en juego (una cifra, una pregunta incómoda, una emoción),
   en los primeros 3–4 segundos. Corta la presentación, los saludos y el contexto que no hace falta.
2. RELLENO: quita tramos internos que no aportan (muletillas repetidas "a ver, a ver", pausas, logística, gente
   hablando de otra cosa). Solo si quitarlos NO rompe la historia. Si el momento fluye, déjalo en un solo segmento.
3. FINAL: termina en el remate o la reacción, no a mitad de frase.
4. ESTRUCTURA: "gancho_primero" SOLO si el remate es muy fuerte y se entiende solo en 2–4 s (una frase o reacción
   memorable); entonces indica ese tramo como "gancho" y el clip lo muestra primero. Si no, "lineal".

Reglas de tiempos: usa los timestamps de la transcripción (MM:SS o HH:MM:SS); cada segmento dura al menos
{min_seg} s; los segmentos van en orden cronológico y no se solapan; el total queda entre {dur_min} y {dur_max} s.

Responde SOLO JSON válido, un objeto por candidato y en el mismo orden:
{{"candidatos": [{{"n": 1, "estructura": "lineal", "segmentos": [{{"inicio": "12:07", "fin": "12:31"}}],
  "gancho": null, "por_que": "una frase"}}]}}"""


_TS = re.compile(r"^\s*\d{1,2}(:\d{1,2}){1,2}\s*$")


def _seg(ts) -> int:
    """Segundos de un timestamp MM:SS o HH:MM:SS; ValueError si no lo es (no se convierte en 0 en silencio)."""
    if not _TS.match(str(ts)):
        raise ValueError(f"timestamp inválido: {ts!r}")
    return _timestamp_to_seconds(str(ts))


def validar_plan(plan: dict, rango: dict, dur_min: int, dur_max: int) -> tuple[list[dict] | None, str]:
    """Segmentos en orden de montaje si el plan es válido; (None, motivo) si no."""
    try:
        r0, r1 = _seg(rango["inicio"]) - MARGEN_S, _seg(rango["fin"]) + MARGEN_S
        segs = [(_seg(s["inicio"]), _seg(s["fin"])) for s in plan.get("segmentos") or []]
    except (KeyError, TypeError, ValueError) as e:
        return None, f"tiempos ilegibles ({e})"
    if not segs:
        return None, "sin segmentos"
    for a, b in segs:
        if not (r0 <= a < b <= r1):
            return None, f"segmento {a}-{b}s fuera del rango"
        if b - a < MIN_SEGMENTO_S:
            return None, f"segmento de {b - a}s (< {MIN_SEGMENTO_S}s)"
    if any(segs[i][1] > segs[i + 1][0] for i in range(len(segs) - 1)):
        return None, "segmentos solapados o fuera de orden"
    total = sum(b - a for a, b in segs)

    gancho = None
    if plan.get("estructura") == "gancho_primero" and plan.get("gancho"):
        try:
            g0, g1 = _seg(plan["gancho"]["inicio"]), _seg(plan["gancho"]["fin"])
        except (KeyError, TypeError, ValueError):
            return None, "gancho ilegible"
        if not (r0 <= g0 < g1 <= r1 and GANCHO_MIN_S <= g1 - g0 <= GANCHO_MAX_S):
            return None, "gancho fuera del rango o de duración inválida"
        gancho = (g0, g1)
        total += g1 - g0
    if not (dur_min <= total <= dur_max):
        return None, f"duración total {total}s fuera de {dur_min}–{dur_max}s"

    orden = ([gancho] if gancho else []) + segs
    return [{"inicio": _seconds_to_timestamp(a), "fin": _seconds_to_timestamp(b)} for a, b in orden], "ok"


def texto_del_plan(segmentos_transcripcion: list, segmentos_plan: list[dict]) -> str:
    """Texto del clip dirigido, en orden de montaje, con una marca en cada corte."""
    partes = []
    for s in segmentos_plan:
        a, b = _seg(s["inicio"]), _seg(s["fin"])
        lineas = [linea for t, linea in segmentos_transcripcion if a <= t <= b]
        partes.append("\n".join(lineas) or "(sin texto en el tramo)")
    return "\n[— corte —]\n".join(partes)


def _ventana(segmentos_transcripcion: list, rango: dict) -> str:
    a, b = _seg(rango["inicio"]) - MARGEN_S, _seg(rango["fin"]) + MARGEN_S
    return "\n".join(linea for t, linea in segmentos_transcripcion if a <= t <= b)


def _parsear(raw: str, n: int) -> list[dict]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        data = {}
    por_n = {c.get("n"): c for c in data.get("candidatos") or [] if isinstance(c, dict)}
    return [por_n.get(i, {}) for i in range(1, n + 1)]


def activada() -> bool:
    return os.environ.get("DIRECCION_EDITORIAL", "1").strip().lower() not in ("0", "false", "no")


def run_direccion(rangos: list[dict], *, transcripcion: str, config: dict) -> list[dict]:
    """Agrega `plan_edicion` a cada rango conservado con un plan válido. Devuelve la lista (modificada)."""
    canal_id = (config.get("meta") or {}).get("id", "default")
    memoria = comun.cargar_memoria(canal_id) or "(el nicho no tiene memoria: aplica el criterio general)"
    ref = config.get("refinamiento") or {}
    dur_min = int(ref.get("direccion_duracion_minima_segundos") or ref.get("duracion_minima_segundos", 15))
    dur_max = int(ref.get("duracion_maxima_segundos", 90))
    candidatos = [r for r in rangos if r.get("conservar") and r.get("inicio") and r.get("fin")]
    if not candidatos:
        return rangos

    segs = _parse_segments(transcripcion)
    bloques = [f"=== CANDIDATO {n} (rango del detector {r['inicio']} → {r['fin']}) ===\n{_ventana(segs, r)}\n"
               for n, r in enumerate(candidatos, 1)]
    system = PROMPT.format(memoria=memoria, margen=MARGEN_S, min_seg=MIN_SEGMENTO_S, dur_min=dur_min, dur_max=dur_max)
    print(f"[DIRECCION] {len(candidatos)} candidato(s)...")
    resp = get_client().messages.create(
        model=MODEL, max_tokens=4000, system=system,
        messages=[{"role": "user", "content": "\n".join(bloques)}],
    )
    for r, plan in zip(candidatos, _parsear(resp.content[0].text, len(candidatos))):
        segmentos, motivo = validar_plan(plan, r, dur_min, dur_max)
        if segmentos is None:
            print(f"  ↺ {r['inicio']}→{r['fin']}: plan descartado ({motivo}); se usa el rango original")
            continue
        r["plan_edicion"] = {"estructura": plan.get("estructura", "lineal"), "segmentos": segmentos,
                             "por_que": plan.get("por_que")}
        print(f"  ✂ {r['inicio']}→{r['fin']}: {plan.get('estructura', 'lineal')}, {len(segmentos)} segmento(s) — "
              f"{plan.get('por_que', '')}")
    return rangos
