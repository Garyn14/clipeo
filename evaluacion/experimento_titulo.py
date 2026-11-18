"""
experimento_titulo.py — CLIP-44: ¿rinde mejor el título sin caja (con contorno) que el de siempre?

Cruza las etiquetas por audiencia (`evaluacion/casos/<nicho>.audiencia.yaml`: clave `sesión/clip` → outlier real) con
la variante de título de cada clip (`stream_data/<sesión>/clips/<clip>.json`, campo `estilo_titulo`).

    python -m evaluacion.experimento_titulo zapatillas_peru

Primero: publicar clips con su link pegado en la revisión y correr `python -m evaluacion.etiquetar_audiencia
<nicho> --escribir`. Con pocos clips por variante el resultado es solo una pista (se avisa).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import median

import yaml

from evaluacion import _legacy

MIN_POR_VARIANTE = 10


def _stream_data() -> Path:
    env = os.environ.get("CLIPEO_STREAM_DATA")
    if env:
        return Path(env).resolve()
    raiz = _legacy.LEGACY.parent / "stream_data"
    return raiz if raiz.exists() else _legacy.LEGACY / "stream_data"


def comparar(etiquetas: list[dict], stream_data: Path) -> dict[str, list[float]]:
    """{variante: [outliers]} de los clips etiquetados que tienen variante registrada."""
    grupos: dict[str, list[float]] = {}
    for e in etiquetas:
        clave, outlier = e.get("clave_correccion"), e.get("outlier")
        if not clave or outlier is None or "/" not in clave:
            continue
        sesion, clip = clave.split("/", 1)
        try:
            meta = json.loads((stream_data / sesion / "clips" / f"{clip}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("estilo_titulo"):
            grupos.setdefault(meta["estilo_titulo"], []).append(float(outlier))
    return grupos


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-44: experimento de título (caja vs contorno)")
    ap.add_argument("nicho")
    args = ap.parse_args()
    ruta = Path(__file__).resolve().parent / "casos" / f"{args.nicho}.audiencia.yaml"
    etiquetas = yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    grupos = comparar(etiquetas or [], _stream_data())
    if not grupos:
        print("[TITULO] Todavía no hay clips del experimento con resultado de audiencia.")
        return
    for variante, valores in sorted(grupos.items()):
        sobre_normal = sum(1 for v in valores if v >= 1) / len(valores)
        print(f"  {variante:9s} n={len(valores):3d}  mediana outlier {median(valores):6.2f}  "
              f"sobre lo normal {sobre_normal:.0%}")
    if any(len(v) < MIN_POR_VARIANTE for v in grupos.values()):
        print(f"[TITULO] ⚠ Menos de {MIN_POR_VARIANTE} clips en alguna variante: es solo una pista, no una conclusión.")


if __name__ == "__main__":
    main()
