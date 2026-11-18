"""
comun.py — Utilidades compartidas por los scripts de investigación del nicho.

Índice outlier: vistas de un video ÷ mediana de vistas de su cuenta. Mide cuánto rindió un
clip respecto de lo normal para esa cuenta (100K vistas es un éxito para una cuenta chica y
un fracaso para Yolu). Los videos con 0 vistas exactas son privados y se excluyen.
"""

import collections
import json
import statistics
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
EDAD_MINIMA_DIAS = 3  # los videos más nuevos todavía están juntando vistas


def carpeta_nicho(nicho: str) -> Path:
    return RAIZ / "investigacion" / nicho


# ── Memoria del nicho (la usan A1, A2, el juez y la auditoría) ──────────────

def ruta_memoria(nicho: str) -> Path:
    return carpeta_nicho(nicho) / "referencias.yaml"


def cargar_memoria(nicho: str) -> str | None:
    """referencias.yaml del nicho (evidencia de mercado), o None si el nicho no tiene memoria."""
    p = ruta_memoria(nicho)
    return p.read_text(encoding="utf-8") if p.exists() else None


# ── Correcciones del editor (tu criterio, desde la Revisión) ─────────────────

def registrar_correccion(nicho: str, registro: dict) -> None:
    """Agrega una decisión de la revisión a investigacion/<nicho>/correcciones.jsonl."""
    archivo = carpeta_nicho(nicho) / "correcciones.jsonl"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    with archivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def registrar_publicado(nicho: str, registro: dict) -> None:
    """CLIP-33: enlace clip ↔ video publicado (pegado en la revisión) en investigacion/<nicho>/publicados.jsonl."""
    archivo = carpeta_nicho(nicho) / "publicados.jsonl"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    with archivo.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def cargar_correcciones(nicho: str, n: int = 30) -> str:
    """Las últimas `n` decisiones del editor, resumidas en una línea cada una ("" si no hay)."""
    archivo = carpeta_nicho(nicho) / "correcciones.jsonl"
    if not archivo.exists():
        return ""
    todos = [json.loads(l) for l in archivo.read_text(encoding="utf-8").splitlines() if l.strip()]
    # CLIP-53: un mismo momento revisado dos veces (p. ej. re-aprobado tras re-cortar, con otro clip_id) cuenta una
    # sola vez: vale la última decisión por (sesión, título propuesto)
    ultimos: dict[tuple, dict] = {}
    for r in todos:
        j = r.get("juez") or {}
        ultimos.pop((r.get("session_id"), j.get("linea1"), j.get("linea2")), None)
        ultimos[(r.get("session_id"), j.get("linea1"), j.get("linea2"))] = r
    registros = list(ultimos.values())[-n:]
    lineas = []
    for r in registros:
        j = r.get("juez") or {}
        propuesto = " / ".join(x for x in (j.get("linea1"), j.get("linea2")) if x) or "(sin título)"
        meta = f"tipo {j.get('tipo') or '?'}, fuerza {j.get('fuerza') if j.get('fuerza') is not None else '?'}"
        accion = r.get("accion")
        if accion == "descartado":
            lineas.append(f"- DESCARTÓ «{propuesto}» ({meta})" + (f": {r['razon']}" if r.get("razon") else ""))
        elif accion == "editado":
            lineas.append(f"- CAMBIÓ el título «{propuesto}» por «{r.get('titulo_final', '')}» ({meta})")
        elif accion == "aprobado":
            lineas.append(f"- APROBÓ «{propuesto}» ({meta})")
    return "\n".join(lineas)


def leer_videos(nicho: str) -> list[dict]:
    archivo = carpeta_nicho(nicho) / "videos.jsonl"
    if not archivo.exists():
        return []
    return [json.loads(l) for l in archivo.read_text(encoding="utf-8").splitlines() if l.strip()]


def calcular_outliers(filas: list[dict]) -> list[dict]:
    """
    Videos públicos y maduros (>= EDAD_MINIMA_DIAS, vistas > 0) con su `outlier` recalculado
    contra la mediana de su cuenta (sin privados). Devuelve copias; no modifica `filas`.
    """
    maduros = [dict(f) for f in filas if (f.get("edad_dias") or 0) >= EDAD_MINIMA_DIAS and (f.get("vistas") or 0) > 0]
    por_cuenta: dict[str, list[int]] = collections.defaultdict(list)
    for f in maduros:
        por_cuenta[f["cuenta"]].append(f["vistas"])
    for f in maduros:
        f["outlier"] = round(f["vistas"] / (statistics.median(por_cuenta[f["cuenta"]]) or 1), 2)
    return maduros
