"""
cobertura.py — Mide la cobertura del detector del piloto (A1 → A2) sobre chunks completos.

De los momentos que el editor aprobó en un chunk, ¿cuántos vuelve a proponer el detector?
El juez solo elige entre lo que el detector le pasa: lo que se escapa aquí se pierde.

Casos: evaluacion/casos/<nicho>.cobertura.yaml (los genera exportar_casos.py en la laptop).

    - id: zp-cob-001
      nicho: zapatillas_peru
      fuente: "20261003_232147 · chunk_001"
      transcripcion: |            # chunk completo
        [00:00] ...
      esperados:   [{inicio: "12:04", fin: "12:50", clip_id: clip_c001_01}]
      descartados: [{inicio: "20:00", fin: "20:30", clip_id: clip_c001_02}]

Uso (desde la raíz del repo):
    python -m evaluacion.cobertura zapatillas_peru [--repeticiones 3] [--solape 0.5]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from evaluacion import _legacy
from evaluacion.casos import DIR_CASOS, CasoInvalido

DIR_RESULTADOS = Path(__file__).resolve().parent / "resultados"
SOLAPE_MINIMO = 0.5


def _seg(ts: str) -> int:
    s = 0
    for p in str(ts).strip().split(":"):
        s = s * 60 + int(p)
    return s


def solape(esperado: dict, propuesto: dict) -> float:
    """Fracción de la duración del esperado cubierta por el propuesto (0–1)."""
    a0, a1 = _seg(esperado["inicio"]), _seg(esperado["fin"])
    b0, b1 = _seg(propuesto["inicio"]), _seg(propuesto["fin"])
    dur = max(a1 - a0, 1)
    return max(0, min(a1, b1) - max(a0, b0)) / dur


def encontrado(esperado: dict, propuestos: list[dict], minimo: float = SOLAPE_MINIMO) -> bool:
    return any(solape(esperado, p) >= minimo for p in propuestos)


# ── Casos ────────────────────────────────────────────────────────────────────

def validar(caso: dict) -> dict:
    ident = caso.get("id") or "(sin id)"
    for campo in ("id", "nicho", "transcripcion"):
        if not caso.get(campo):
            raise CasoInvalido(f"{ident}: falta '{campo}'")
    if not caso.get("esperados"):
        raise CasoInvalido(f"{ident}: un caso de cobertura necesita al menos un 'esperado'")
    for r in caso["esperados"] + (caso.get("descartados") or []):
        if not (r.get("inicio") and r.get("fin")):
            raise CasoInvalido(f"{ident}: cada rango necesita inicio y fin")
    return caso


def ruta_casos(nicho: str) -> Path:
    return DIR_CASOS / f"{nicho}.cobertura.yaml"


def cargar(nicho: str) -> list[dict]:
    ruta = ruta_casos(nicho)
    if not ruta.exists():
        return []
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or []
    return [validar(c) for c in datos]


def guardar(casos: list[dict], ruta: Path) -> None:
    for c in casos:
        validar(c)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump(casos, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


# ── Ejecución del detector del piloto ────────────────────────────────────────

def cargar_config(nicho: str) -> dict:
    """Config del nicho con el mismo loader que usa el pipeline (contexto v2)."""
    from contexto.context_loader import ContextLoader

    return ContextLoader(contexto_dir=str(_legacy.LEGACY / "contexto")).load_nicho(nicho)


def detectar(transcripcion: str, config: dict) -> list[dict]:
    """A1 → A2 sobre una transcripción; devuelve los rangos con conservar=true."""
    from agentes import agent1_peak_detector as a1
    from agentes import agent2_range_refiner as a2

    with tempfile.TemporaryDirectory() as tmp:
        trans = Path(tmp) / "transcripcion_completa.txt"
        trans.write_text(transcripcion, encoding="utf-8")
        picos = a1.run_agent(str(trans), config)
        if not picos:
            return []
        rangos = a2.run_agent(str(Path(tmp) / "picos.json"), config)
    return [r for r in rangos if r.get("conservar") and r.get("inicio") and r.get("fin")]


def evaluar_caso(caso: dict, config: dict, minimo: float = SOLAPE_MINIMO) -> dict:
    try:
        propuestos = detectar(caso["transcripcion"], config)
    except (Exception, SystemExit) as e:  # noqa: BLE001 — un caso fallido no detiene la evaluación
        return {"id": caso["id"], "error": f"{type(e).__name__}: {e}"}
    esperados = caso["esperados"]
    descartados = caso.get("descartados") or []
    no_encontrados = [e for e in esperados if not encontrado(e, propuestos, minimo)]
    return {
        "id": caso["id"],
        "esperados": len(esperados),
        "encontrados": len(esperados) - len(no_encontrados),
        "propuestos": len(propuestos),
        "descartados_repropuestos": sum(1 for d in descartados if encontrado(d, propuestos, minimo)),
        "no_encontrados": [{k: e.get(k) for k in ("inicio", "fin", "clip_id")} for e in no_encontrados],
        "rangos_propuestos": [{"inicio": p["inicio"], "fin": p["fin"]} for p in propuestos],
    }


def resumir(resultados: list[dict]) -> dict:
    validos = [r for r in resultados if "error" not in r]
    esperados = sum(r["esperados"] for r in validos)
    encontrados = sum(r["encontrados"] for r in validos)
    return {
        "casos": len(resultados),
        "evaluados": len(validos),
        "errores": len(resultados) - len(validos),
        "esperados": esperados,
        "encontrados": encontrados,
        "cobertura": round(encontrados / esperados, 3) if esperados else None,
        "propuestos_por_chunk": round(statistics.mean(r["propuestos"] for r in validos), 1) if validos else None,
        "descartados_repropuestos": sum(r["descartados_repropuestos"] for r in validos),
    }


def variacion(corridas: list[dict], metrica: str) -> dict | None:
    """Media, mínimo y máximo de una métrica del resumen entre corridas."""
    valores = [c["resumen"][metrica] for c in corridas if c["resumen"].get(metrica) is not None]
    if not valores:
        return None
    return {"media": round(statistics.mean(valores), 3), "min": min(valores), "max": max(valores)}


def inestables(corridas: list[dict]) -> list[str]:
    """Casos cuyo número de encontrados cambia entre corridas."""
    por_caso: dict[str, set] = {}
    for c in corridas:
        for r in c["resultados"]:
            if "error" not in r:
                por_caso.setdefault(r["id"], set()).add(r["encontrados"])
    return sorted(cid for cid, vals in por_caso.items() if len(vals) > 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nicho")
    ap.add_argument("--repeticiones", type=int, default=1)
    ap.add_argument("--solape", type=float, default=SOLAPE_MINIMO, help="fracción mínima del esperado cubierta")
    ap.add_argument("--proveedor", help="AI_PROVIDER para esta corrida")
    ap.add_argument("--no-guardar", action="store_true")
    args = ap.parse_args(argv)

    if args.proveedor:
        os.environ["AI_PROVIDER"] = args.proveedor
    os.environ.setdefault("AI_PROVIDER", "claude_cli")

    casos = cargar(args.nicho)
    if not casos:
        print(f"Sin casos de cobertura en {ruta_casos(args.nicho)} (se generan con exportar_casos.py)")
        return 1
    config = cargar_config(args.nicho)

    corridas = []
    for n in range(1, args.repeticiones + 1):
        print(f"[COBERTURA] Corrida {n}/{args.repeticiones} · {len(casos)} chunk(s) · {os.environ['AI_PROVIDER']}")
        resultados = [evaluar_caso(c, config, args.solape) for c in casos]
        corridas.append({"resultados": resultados, "resumen": resumir(resultados)})

    print("\n" + "═" * 60)
    for i, c in enumerate(corridas, 1):
        r = c["resumen"]
        print(f"  Corrida {i}: cobertura {r['cobertura']} ({r['encontrados']}/{r['esperados']}) · "
              f"{r['propuestos_por_chunk']} candidatos/chunk · errores {r['errores']}")
    var = variacion(corridas, "cobertura")
    inest = inestables(corridas)
    if args.repeticiones > 1:
        print(f"  Variación de cobertura: {var} · casos inestables: {inest or 'ninguno'}")
    for r in corridas[-1]["resultados"]:
        for e in r.get("no_encontrados", []):
            print(f"  ✗ {r['id']}: no encontró {e['inicio']}–{e['fin']} ({e.get('clip_id')})")
    print("═" * 60)

    if not args.no_guardar:
        DIR_RESULTADOS.mkdir(exist_ok=True)
        salida = DIR_RESULTADOS / f"{datetime.now():%Y%m%d_%H%M%S}_{args.nicho}_cobertura.json"
        salida.write_text(json.dumps({
            "nicho": args.nicho, "fecha": datetime.now().isoformat(timespec="seconds"),
            "proveedor": os.environ["AI_PROVIDER"], "solape_minimo": args.solape,
            "variacion_cobertura": var, "inestables": inest, "corridas": corridas,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[COBERTURA] Resultados: {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
