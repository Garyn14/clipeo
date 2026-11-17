"""
analizar.py — Desglosa un archivo de resultados del juez (evaluacion/resultados/*_<nicho>.json).

Por cada caso agrega las corridas (mayoría), y muestra: métricas por origen (correccion / muestra),
falsos positivos y negativos con el "por qué" del juez y los casos inestables.

Uso:
    python -m evaluacion.analizar evaluacion/resultados/20261117_..._zapatillas_peru.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from evaluacion import _legacy  # noqa: F401  (UTF-8 en la consola)
from evaluacion import casos as casos_mod
from evaluacion.evaluar import resumir


def por_caso(datos: dict) -> list[dict]:
    """Un resultado por caso: decisión por mayoría entre corridas, con la fracción de 'publicar'."""
    corridas = datos.get("corridas") or [{"resultados": datos.get("resultados", [])}]
    agrupado: dict[str, list[dict]] = defaultdict(list)
    for c in corridas:
        for r in c["resultados"]:
            if "error" not in r:
                agrupado[r["id"]].append(r)
    salida = []
    for cid, rs in agrupado.items():
        votos = sum(1 for r in rs if r["obtenido_publicar"])
        publicar = votos * 2 > len(rs) if len(rs) > 1 else bool(votos)
        base = dict(rs[-1])
        base.update({
            "obtenido_publicar": publicar,
            "acierto": publicar == base["esperado_publicar"],
            "fraccion_publicar": round(votos / len(rs), 2),
            "corridas": len(rs),
            "tipos": dict(Counter(r.get("tipo_obtenido") for r in rs)),
        })
        salida.append(base)
    return sorted(salida, key=lambda r: r["id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("resultados", type=Path)
    args = ap.parse_args(argv)

    datos = json.loads(args.resultados.read_text(encoding="utf-8"))
    casos = {c["id"]: c for c in casos_mod.cargar_nicho(datos["nicho"], incluir_sinteticos=True)}
    filas = por_caso(datos)

    print(f"Resultados: {args.resultados.name} · {len(filas)} casos · mayoría de {datos.get('repeticiones', 1)} corrida(s)")
    for origen in sorted({r["origen"] for r in filas}):
        sub = [r for r in filas if r["origen"] == origen]
        print(f"\n[{origen}] {resumir(sub)}")
    print(f"\n[total] {resumir(filas)}")

    for titulo, filtro in (("FALSOS POSITIVOS (publica y no debía)", lambda r: r["obtenido_publicar"] and not r["esperado_publicar"]),
                           ("FALSOS NEGATIVOS (no publica y debía)", lambda r: not r["obtenido_publicar"] and r["esperado_publicar"])):
        errores = [r for r in filas if filtro(r)]
        print(f"\n{titulo}: {len(errores)}")
        for r in errores:
            c = casos.get(r["id"], {})
            print(f"  · {r['id']} [{r['origen']}] tipo={r['tipos']} publicar={r['fraccion_publicar']} · {c.get('evidencia', '')}")
            print(f"      juez: {r.get('por_que')}")

    tipos = Counter(t for r in filas if r["esperado_publicar"] for t in r["tipos"])
    print(f"\nTipos asignados a casos buenos: {dict(tipos)}")
    inestables = [r["id"] for r in filas if 0 < r["fraccion_publicar"] < 1]
    print(f"Inestables ({len(inestables)}): {inestables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
