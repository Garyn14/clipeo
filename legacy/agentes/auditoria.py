"""
auditoria.py — ¿Qué momentos buenos NO le llegaron al juez? Lee la transcripción completa de
un chunk con la memoria del nicho y lista los momentos de tipos que funcionan que no están
entre los rangos que pasaron el A2. Mide la cobertura del A1/A2 (lo que el juez no puede
rescatar porque nunca lo ve). Bajo demanda; no forma parte del flujo.

Uso:
    python -m agentes.auditoria <session_id> [--chunk chunk_001]

Escribe stream_data/<session>/chunks/<chunk>/auditoria.json.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from ai_client import AIRetryableError, get_client  # noqa: E402
from investigacion import comun  # noqa: E402

MODEL = "claude-sonnet-4-6"

PROMPT = """Eres el AUDITOR de un pipeline que recorta clips de un nicho de redes sociales.
Recibes la transcripción COMPLETA de un tramo de video y la lista de momentos que el pipeline
ya detectó. Tu trabajo es encontrar los momentos que se le ESCAPARON: los que pertenecen a
alguno de los tipos_que_funcionan de la memoria y NO están (ni solapados) en la lista.

MEMORIA DEL NICHO:
{memoria}

Sé estricto: solo momentos con algo en juego y que se entiendan solos. Si no se escapó nada,
devuelve una lista vacía.

Responde SOLO JSON válido:
{{"perdidos": [{{"timestamp": "00:10:07", "tipo": "...", "en_juego": "...", "por_que": "una frase"}}]}}"""


def auditar(chunk_dir: Path, canal_id: str) -> dict:
    memoria = comun.cargar_memoria(canal_id)
    if memoria is None:
        raise SystemExit(f"El nicho {canal_id} no tiene memoria (investigacion/{canal_id}/referencias.yaml)")
    texto = next((p.read_text(encoding="utf-8") for p in
                  (chunk_dir / "transcripcion_enriquecida.txt", chunk_dir / "transcripcion_completa.txt")
                  if p.exists()), None)
    if texto is None:
        raise SystemExit(f"Sin transcripción en {chunk_dir}")
    rangos_p = chunk_dir / "rangos.json"
    rangos = json.loads(rangos_p.read_text(encoding="utf-8")).get("rangos", []) if rangos_p.exists() else []
    detectados = [f"- {r.get('inicio')} → {r.get('fin')}" for r in rangos if r.get("conservar")]

    resp = get_client().messages.create(
        model=MODEL,
        max_tokens=2000,
        system=PROMPT.format(memoria=memoria),
        messages=[{"role": "user", "content": (
            "MOMENTOS YA DETECTADOS:\n" + ("\n".join(detectados) or "(ninguno)")
            + "\n\nTRANSCRIPCIÓN COMPLETA:\n" + texto
        )}],
    )
    raw = resp.content[0].text
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(m.group()) if m else None
    except json.JSONDecodeError:
        data = None
    if not isinstance((data or {}).get("perdidos"), list):
        raise AIRetryableError(f"[AUDITORIA] respuesta sin JSON de perdidos: {raw[:200]}")

    resultado = {"detectados": len(detectados), "perdidos": data["perdidos"]}
    (chunk_dir / "auditoria.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultado


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("session_id")
    ap.add_argument("--chunk", help="un chunk (default: todos los de la sesión)")
    args = ap.parse_args()

    session_dir = Path(__file__).resolve().parents[1] / "stream_data" / args.session_id
    estado = json.loads((session_dir / "pipeline_estado.json").read_text(encoding="utf-8"))
    canal_id = estado.get("config") or "default"
    chunks = [args.chunk] if args.chunk else sorted(estado.get("chunks", {}))
    for chunk_id in chunks:
        r = auditar(session_dir / "chunks" / chunk_id, canal_id)
        print(f"\n[{chunk_id}] llegaron al juez: {r['detectados']} · se escaparon: {len(r['perdidos'])}")
        for p in r["perdidos"]:
            print(f"  ⚠ {p.get('timestamp')} [{p.get('tipo')}] {p.get('en_juego')} — {p.get('por_que')}")


if __name__ == "__main__":
    main()
