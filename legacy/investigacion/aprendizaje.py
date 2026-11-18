"""
aprendizaje.py — CLIP-49 (Q5): ¿qué tipos de momento rinden de verdad en los clips de Clipeo?

    python -m investigacion.aprendizaje zapatillas_peru

Toma la última medición de cada clip publicado (`metricas_publicados.jsonl`, CLIP-48), calcula su outlier contra la
mediana de su plataforma y agrupa por el tipo que le asignó el juez. El resultado es un reporte para el operador:
qué tipos están por encima o por debajo de lo normal y si eso confirma o contradice la memoria del nicho
(`referencias.yaml`). **No cambia la memoria solo**: los cambios se aprueban, como en CLIP-30 y CLIP-35.
Solo cuenta clips con al menos `--dias-min` días publicados (vistas maduras).
"""

from __future__ import annotations

import argparse
import json
from statistics import median

from investigacion import comun

MIN_POR_TIPO = 3


def ultima_por_clip(filas: list[dict], dias_min: float = 3) -> list[dict]:
    """La medición más reciente de cada (plataforma, clip), solo si el video ya tiene vistas maduras. Puro."""
    ultimas: dict[tuple, dict] = {}
    for f in filas:
        clave = (f.get("plataforma"), f.get("clave"))
        if clave not in ultimas or (f.get("medido") or "") >= (ultimas[clave].get("medido") or ""):
            ultimas[clave] = f
    return [f for f in ultimas.values() if (f.get("edad_dias") or 0) >= dias_min and f.get("vistas") is not None]


def con_outlier(filas: list[dict]) -> list[dict]:
    """Agrega `outlier` = vistas ÷ mediana de su plataforma. Puro."""
    salida = []
    for plataforma in {f["plataforma"] for f in filas}:
        grupo = [f for f in filas if f["plataforma"] == plataforma]
        med = median(f["vistas"] for f in grupo) or 1
        salida += [{**f, "outlier": round(f["vistas"] / med, 2)} for f in grupo]
    return salida


def por_tipo(filas: list[dict]) -> list[dict]:
    """[{plataforma, tipo, n, mediana_outlier, sobre_lo_normal}] ordenado por mediana. Puro."""
    grupos: dict[tuple, list[float]] = {}
    for f in filas:
        grupos.setdefault((f["plataforma"], f.get("tipo") or "?"), []).append(f["outlier"])
    tabla = [{"plataforma": p, "tipo": t, "n": len(v), "mediana_outlier": round(median(v), 2),
              "sobre_lo_normal": round(sum(1 for x in v if x >= 1) / len(v), 2)} for (p, t), v in grupos.items()]
    return sorted(tabla, key=lambda r: (r["plataforma"], -r["mediana_outlier"]))


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-49: rendimiento real por tipo de momento")
    ap.add_argument("nicho")
    ap.add_argument("--dias-min", type=float, default=3)
    args = ap.parse_args()
    archivo = comun.carpeta_nicho(args.nicho) / "metricas_publicados.jsonl"
    if not archivo.exists():
        print("[APRENDIZAJE] Sin mediciones: corre primero `python -m investigacion.medir_publicados <nicho>`.")
        return
    filas = [json.loads(l) for l in archivo.read_text(encoding="utf-8").splitlines() if l.strip()]
    tabla = por_tipo(con_outlier(ultima_por_clip(filas, args.dias_min)))
    if not tabla:
        print(f"[APRENDIZAJE] Ningún clip con ≥ {args.dias_min:g} días publicado todavía.")
        return
    print(f"[APRENDIZAJE] Rendimiento por tipo (outlier = vistas ÷ mediana de la plataforma, clips ≥ {args.dias_min:g} días):")
    for r in tabla:
        aviso = "" if r["n"] >= MIN_POR_TIPO else "  (pocos clips: solo una pista)"
        print(f"  {r['plataforma']:8s} {r['tipo']:24s} n={r['n']:2d}  mediana {r['mediana_outlier']:5.2f}x  "
              f"sobre lo normal {r['sobre_lo_normal']:.0%}{aviso}")
    print("\nCompara con `tipos_que_funcionan` de referencias.yaml; los cambios a la memoria los aprueba el operador.")


if __name__ == "__main__":
    main()
