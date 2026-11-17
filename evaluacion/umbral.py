"""
umbral.py — CLIP-32: ¿qué umbral de fuerza conviene al juez?

Lee un resultado de `evaluacion.evaluar` y muestra, por umbral de fuerza, precisión, recall y acierto contra las
etiquetas actuales (incluidas las de audiencia), comparado con la tasa base ("publicar todo"), y el AUC de la fuerza
(0,5 = no separa buenos de malos; 1 = separa perfecto).

    python -m evaluacion.umbral evaluacion/resultados/<archivo>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluacion import casos as casos_mod


def pares(resultado: dict, esperado: dict[str, bool]) -> list[tuple[int, bool]]:
    """(fuerza, debía_publicarse) de cada decisión de todas las corridas."""
    return [(int(r.get("fuerza") or 0), esperado[r["id"]])
            for corrida in resultado["corridas"] for r in corrida["resultados"]
            if r["id"] in esperado and r.get("obtenido_publicar") is not None]


def metricas(datos: list[tuple[int, bool]], umbral: int) -> dict:
    vp = sum(1 for f, e in datos if e and f >= umbral)
    fp = sum(1 for f, e in datos if not e and f >= umbral)
    fn = sum(1 for f, e in datos if e and f < umbral)
    vn = len(datos) - vp - fp - fn
    return {"umbral": umbral, "precision": vp / (vp + fp) if vp + fp else 0.0,
            "recall": vp / (vp + fn) if vp + fn else 0.0, "acierto": (vp + vn) / len(datos) if datos else 0.0}


def auc(datos: list[tuple[int, bool]]) -> float:
    pos = [f for f, e in datos if e]
    neg = [f for f, e in datos if not e]
    if not pos or not neg:
        return 0.5
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def main() -> None:
    ap = argparse.ArgumentParser(description="Precisión/recall del juez por umbral de fuerza")
    ap.add_argument("resultado", type=Path)
    args = ap.parse_args()
    resultado = json.loads(args.resultado.read_text(encoding="utf-8"))
    esperado = {c["id"]: c["esperado"]["publicar"] for c in casos_mod.cargar_nicho(resultado["nicho"])}
    datos = pares(resultado, esperado)
    base = sum(e for _, e in datos) / len(datos)
    print(f"Decisiones: {len(datos)} · tasa base (publicar todo): precisión {base:.2f} · AUC fuerza: {auc(datos):.2f}")
    for u in range(1, 11):
        m = metricas(datos, u)
        print(f"  fuerza ≥ {u:<2}  precisión {m['precision']:.2f} ({m['precision'] - base:+.2f} vs base)  "
              f"recall {m['recall']:.2f}  acierto {m['acierto']:.2f}")


if __name__ == "__main__":
    main()
