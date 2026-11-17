"""
evaluar.py — Evalúa el juez del piloto contra los casos de referencia de un nicho.

Por cada caso ejecuta `legacy/agentes/juez.py::run_juez` sobre el candidato, con la memoria del
nicho, y compara `publicar` (y `tipo`, si el caso lo trae) con lo esperado.

Sin filtración: en un caso que sale de una corrección del editor, esa misma corrección se quita
del prompt del juez mientras se evalúa (si no, el juez "vería la respuesta").

Uso (desde la raíz del repo):
    python -m evaluacion.evaluar zapatillas_peru                 # casos reales
    python -m evaluacion.evaluar zapatillas_peru --sinteticos    # + casos sintéticos de prueba
    python -m evaluacion.evaluar zapatillas_peru --proveedor manual

IA: AI_PROVIDER (por defecto claude_cli: Claude Code de la máquina, sin API de pago).
Escribe evaluacion/resultados/<fecha>_<nicho>.json e imprime un resumen.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from evaluacion import _legacy  # noqa: F401  (agrega legacy/ al sys.path)
from evaluacion import casos as casos_mod

DIR_RESULTADOS = Path(__file__).resolve().parent / "resultados"


def _a_segundos(ts: str) -> int:
    partes = [int(p) for p in str(ts).strip().split(":")]
    s = 0
    for p in partes:
        s = s * 60 + p
    return s


def _preparar_memoria(raiz_tmp: Path, nicho: str, excluir: str | None) -> None:
    """Copia la memoria del nicho a raiz_tmp/investigacion/<nicho>/, sin la corrección `excluir`."""
    from investigacion import comun

    origen = comun.carpeta_nicho(nicho)
    destino = raiz_tmp / "investigacion" / nicho
    destino.mkdir(parents=True, exist_ok=True)
    if (origen / "referencias.yaml").exists():
        shutil.copy(origen / "referencias.yaml", destino / "referencias.yaml")
    correcciones = origen / "correcciones.jsonl"
    if correcciones.exists():
        lineas = []
        for linea in correcciones.read_text(encoding="utf-8").splitlines():
            if not linea.strip():
                continue
            r = json.loads(linea)
            if excluir and f"{r.get('session_id')}/{r.get('clip_id')}" == excluir:
                continue
            lineas.append(linea)
        (destino / "correcciones.jsonl").write_text("\n".join(lineas) + ("\n" if lineas else ""), encoding="utf-8")


def evaluar_caso(caso: dict) -> dict:
    """Ejecuta el juez sobre un caso y devuelve el resultado (sin lanzar por errores de IA)."""
    from agentes import juez
    from investigacion import comun

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _preparar_memoria(tmp, caso["nicho"], caso.get("clave_correccion"))
        session_dir = tmp / "sesion"
        chunk_dir = session_dir / "chunks" / "chunk_001"
        chunk_dir.mkdir(parents=True)
        video = caso.get("video") or {}
        (session_dir / "metadata.json").write_text(
            json.dumps({"title": video.get("titulo"), "uploader": video.get("canal")}, ensure_ascii=False),
            encoding="utf-8",
        )
        cand = caso["candidato"]
        rangos = [{
            "conservar": True,
            "inicio": cand["inicio"],
            "fin": cand["fin"],
            "duracion_segundos": _a_segundos(cand["fin"]) - _a_segundos(cand["inicio"]),
        }]

        raiz_original = comun.RAIZ
        comun.RAIZ = tmp
        try:
            salida = juez.run_juez(
                rangos,
                transcripcion=caso["transcripcion"],
                config={"meta": {"id": caso["nicho"]}},
                session_dir=session_dir,
                chunk_dir=chunk_dir,
            )
            if salida.get("omitido"):
                return {"id": caso["id"], "error": f"juez omitido: {salida.get('nota')}"}
            decision = json.loads((chunk_dir / "juez.json").read_text(encoding="utf-8"))["decisiones"][0]
        except Exception as e:  # noqa: BLE001 — un caso fallido no detiene la evaluación
            return {"id": caso["id"], "error": f"{type(e).__name__}: {e}"}
        finally:
            comun.RAIZ = raiz_original

    esperado = caso["esperado"]
    resultado = {
        "id": caso["id"],
        "origen": caso["origen"],
        "esperado_publicar": esperado["publicar"],
        "obtenido_publicar": bool(decision.get("publicar")),
        "acierto": bool(decision.get("publicar")) == esperado["publicar"],
        "tipo_esperado": esperado.get("tipo"),
        "tipo_obtenido": decision.get("tipo"),
        "fuerza": decision.get("fuerza"),
        "titulo": " / ".join(x for x in (decision.get("linea1"), decision.get("linea2")) if x),
        "por_que": decision.get("por_que"),
    }
    if esperado.get("tipo"):
        resultado["acierto_tipo"] = decision.get("tipo") == esperado["tipo"]
    return resultado


def resumir(resultados: list[dict]) -> dict:
    validos = [r for r in resultados if "error" not in r]
    tp = sum(1 for r in validos if r["esperado_publicar"] and r["obtenido_publicar"])
    fp = sum(1 for r in validos if not r["esperado_publicar"] and r["obtenido_publicar"])
    tn = sum(1 for r in validos if not r["esperado_publicar"] and not r["obtenido_publicar"])
    fn = sum(1 for r in validos if r["esperado_publicar"] and not r["obtenido_publicar"])
    con_tipo = [r for r in validos if "acierto_tipo" in r]

    def _div(a: int, b: int) -> float | None:
        return round(a / b, 3) if b else None

    return {
        "casos": len(resultados),
        "evaluados": len(validos),
        "errores": len(resultados) - len(validos),
        "acierto": _div(tp + tn, len(validos)),
        "precision": _div(tp, tp + fp),   # de lo que el juez publica, cuánto debía publicarse
        "recall": _div(tp, tp + fn),      # de lo que debía publicarse, cuánto publica el juez
        "matriz": {"vp": tp, "fp": fp, "vn": tn, "fn": fn},
        "acierto_tipo": _div(sum(1 for r in con_tipo if r["acierto_tipo"]), len(con_tipo)),
    }


def _imprimir(resumen: dict, resultados: list[dict]) -> None:
    print("\n" + "═" * 60)
    for r in resultados:
        if "error" in r:
            print(f"  ⚠  {r['id']}: {r['error'][:120]}")
            continue
        marca = "✅" if r["acierto"] else "❌"
        print(f"  {marca} {r['id']:<16} esperado={'publicar' if r['esperado_publicar'] else 'no':<9} "
              f"juez={'publicar' if r['obtenido_publicar'] else 'no':<9} [{r['tipo_obtenido']}] {r['titulo'][:50]}")
    m = resumen["matriz"]
    print("─" * 60)
    print(f"  Casos: {resumen['casos']}  ·  evaluados: {resumen['evaluados']}  ·  errores: {resumen['errores']}")
    print(f"  Acierto: {resumen['acierto']}  ·  precisión: {resumen['precision']}  ·  recall: {resumen['recall']}")
    print(f"  VP={m['vp']} FP={m['fp']} VN={m['vn']} FN={m['fn']}  ·  acierto de tipo: {resumen['acierto_tipo']}")
    print("═" * 60)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nicho")
    ap.add_argument("--sinteticos", action="store_true", help="incluir casos sintéticos de prueba")
    ap.add_argument("--solo-sinteticos", action="store_true", help="solo los casos sintéticos")
    ap.add_argument("--proveedor", help="AI_PROVIDER para esta corrida (claude_cli, manual, anthropic)")
    ap.add_argument("--no-guardar", action="store_true", help="no escribir el archivo de resultados")
    args = ap.parse_args(argv)

    if args.proveedor:
        os.environ["AI_PROVIDER"] = args.proveedor
    os.environ.setdefault("AI_PROVIDER", "claude_cli")

    todos = casos_mod.cargar_nicho(args.nicho, incluir_sinteticos=args.sinteticos or args.solo_sinteticos)
    if args.solo_sinteticos:
        todos = [c for c in todos if c["origen"] == "sintetico"]
    if not todos:
        print(f"Sin casos para {args.nicho} en {casos_mod.DIR_CASOS}")
        return 1

    print(f"[EVAL] {len(todos)} caso(s) de {args.nicho} · proveedor: {os.environ['AI_PROVIDER']}")
    resultados = [evaluar_caso(c) for c in todos]
    resumen = resumir(resultados)
    _imprimir(resumen, resultados)

    if not args.no_guardar:
        DIR_RESULTADOS.mkdir(exist_ok=True)
        salida = DIR_RESULTADOS / f"{datetime.now():%Y%m%d_%H%M%S}_{args.nicho}.json"
        salida.write_text(json.dumps({
            "nicho": args.nicho,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "proveedor": os.environ["AI_PROVIDER"],
            "resumen": resumen,
            "resultados": resultados,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[EVAL] Resultados: {salida.relative_to(Path.cwd()) if salida.is_relative_to(Path.cwd()) else salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
