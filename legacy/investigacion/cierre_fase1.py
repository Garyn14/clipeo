"""
cierre_fase1.py — CLIP-59: ¿se cumplen los criterios para cerrar la Fase 1? (docs/ROADMAP.md v0.5 §1)

    python -m investigacion.cierre_fase1 zapatillas_peru [--dias 14]

  1. Calidad: ≥ 60% de los clips revisados se aprueban sin editar (últimos --dias días; cada momento cuenta una vez).
  2. Publicación: aprobar = publicado (YouTube) / borrador (TikTok). Cumplido en el S10.
  3. Aprendizaje: ≥ 30 clips publicados medidos (≥ 3 días) y al menos un cambio de memoria hecho con esa evidencia.
  4. Operación estable: un comando, sin variables a mano, guía. Cumplido en el S12.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta

from investigacion import comun

META_APROBACION = 0.60
META_MEDIDOS = 30


def tasa_aprobacion(registros: list[dict], desde: datetime) -> dict:
    """Última decisión por (sesión, título propuesto) dentro del período → conteos y tasa sin editar. Puro."""
    ultimas: dict[tuple, dict] = {}
    for r in registros:
        try:
            fecha = datetime.fromisoformat(r.get("fecha", ""))
        except ValueError:
            continue
        if fecha < desde:
            continue
        j = r.get("juez") or {}
        ultimas[(r.get("session_id"), j.get("linea1"), j.get("linea2"))] = r
    conteo = {"aprobado": 0, "editado": 0, "descartado": 0}
    for r in ultimas.values():
        if r.get("accion") in conteo:
            conteo[r["accion"]] += 1
    total = sum(conteo.values())
    return {**conteo, "total": total, "tasa": round(conteo["aprobado"] / total, 2) if total else None}


def clips_medidos(filas: list[dict]) -> int:
    """Clips publicados distintos con alguna medición de ≥ 3 días. Puro."""
    return len({(f.get("plataforma"), f.get("clave")) for f in filas if (f.get("edad_dias") or 0) >= 3})


def _ultimo_cambio_memoria(nicho: str) -> str | None:
    ruta = comun.carpeta_nicho(nicho) / "referencias.yaml"
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%cs %s", "--", str(ruta)],
                           capture_output=True, text=True, encoding="utf-8", cwd=str(ruta.parent), timeout=30)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-59: criterios de cierre de la Fase 1")
    ap.add_argument("nicho")
    ap.add_argument("--dias", type=int, default=14)
    args = ap.parse_args()

    carpeta = comun.carpeta_nicho(args.nicho)
    leer = lambda nombre: [json.loads(l) for l in (carpeta / nombre).read_text(encoding="utf-8").splitlines()
                           if l.strip()] if (carpeta / nombre).exists() else []
    t = tasa_aprobacion(leer("correcciones.jsonl"), datetime.now() - timedelta(days=args.dias))
    medidos = clips_medidos(leer("metricas_publicados.jsonl"))
    memoria = _ultimo_cambio_memoria(args.nicho)

    ok1 = t["tasa"] is not None and t["tasa"] >= META_APROBACION and t["total"] >= 10
    print(f"[FASE 1] Criterios de cierre ({args.nicho}, últimos {args.dias} días)\n")
    tasa_txt = f"{t['tasa']:.0%}" if t["tasa"] is not None else "—"
    print(f"  {'✅' if ok1 else '⏳'} 1. Calidad: {tasa_txt} aprobados sin editar "
          f"({t['aprobado']} de {t['total']}: {t['editado']} editados, {t['descartado']} descartados) · meta ≥ 60% con ≥ 10 clips")
    print("  ✅ 2. Publicación: YouTube automático, TikTok a la bandeja (S10)")
    ok3 = medidos >= META_MEDIDOS
    print(f"  {'✅' if ok3 else '⏳'} 3. Aprendizaje: {medidos} de {META_MEDIDOS} clips medidos · "
          f"último cambio de memoria: {memoria or '—'} (debe venir de `investigacion.aprendizaje`)")
    print("  ✅ 4. Operación estable: `python -m herramientas.levantar` + docs/OPERACION.md (S12)")
    print("\n  " + ("🎉 La Fase 1 puede cerrarse." if ok1 and ok3 else "La Fase 1 sigue abierta: hace falta más uso real."))


if __name__ == "__main__":
    main()
