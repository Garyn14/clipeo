"""
exportar_casos.py — Arma los casos de evaluación de un nicho con los datos del piloto.

Se ejecuta UNA VEZ en la laptop del operador, donde están las transcripciones (stream_data/ y
investigacion/<nicho>/muestra/, que no se suben al repo). Escribe evaluacion/casos/<nicho>.yaml
con fragmentos de texto (sin videos ni secretos), listo para subir.

Fuentes:
  - correcciones.jsonl: lo que el editor aprobó/editó (publicar) o descartó (no publicar).
  - muestra.jsonl + muestra/<id>/transcripcion.txt: clips de TikTok medidos; top y propia_top
    (rindieron muy por encima de su cuenta) = publicar, fondo = no publicar.

Uso (desde la raíz del repo):
    python -m evaluacion.exportar_casos zapatillas_peru
    python -m evaluacion.exportar_casos zapatillas_peru --stream-data legacy/stream_data
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from evaluacion import _legacy
from evaluacion import casos as casos_mod

MARGEN_SEGUNDOS = 30          # contexto alrededor del candidato (para A1/A2 en S2)
_LINEA = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]")


def _a_segundos(ts: str) -> int:
    s = 0
    for p in str(ts).strip().split(":"):
        s = s * 60 + int(p)
    return s


def _mmss(segundos: int) -> str:
    h, r = divmod(int(segundos), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def ventana(transcripcion: str, inicio: str, fin: str, margen: int = MARGEN_SEGUNDOS) -> str:
    """Líneas `[MM:SS] ...` entre inicio-margen y fin+margen."""
    desde, hasta = _a_segundos(inicio) - margen, _a_segundos(fin) + margen
    lineas = []
    for linea in transcripcion.splitlines():
        m = _LINEA.match(linea)
        if m and desde <= _a_segundos(m.group(1)) <= hasta:
            lineas.append(linea)
    return "\n".join(lineas)


def _leer_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _transcripcion_chunk(chunk_dir: Path) -> str | None:
    for nombre in ("transcripcion_enriquecida.txt", "transcripcion_completa.txt", "transcripcion_raw.txt"):
        p = chunk_dir / nombre
        if p.exists():
            return p.read_text(encoding="utf-8")
    return None


def _buscar_clip(session_dir: Path, clip_id: str) -> tuple[Path, dict] | None:
    """(chunk_file, item de contenido) del clip, con la misma numeración que usó el Agente 4
    (misma lógica que legacy/backend/app/services/clip_index.py, sin importar el backend)."""
    from core.clip_ids import asignar_clip_ids

    archivos = sorted((session_dir / "contenido_chunks").glob("*.json"))
    chunks = [(cf, _leer_json(cf).get("contenido", [])) for cf in archivos]
    contenido = dict(chunks)
    for cf, pos, cid in asignar_clip_ids(chunks, lambda it: it.get("publicar") or it.get("revision_descartado")):
        if cid == clip_id:
            return cf, contenido[cf][pos]
    return None


def casos_de_correcciones(nicho: str, stream_data: Path) -> tuple[list[dict], list[str]]:
    from investigacion import comun

    archivo = comun.carpeta_nicho(nicho) / "correcciones.jsonl"
    if not archivo.exists():
        return [], [f"sin {archivo}"]
    casos, avisos = [], []
    registros = [json.loads(l) for l in archivo.read_text(encoding="utf-8").splitlines() if l.strip()]
    vistos: set[str] = set()
    for r in reversed(registros):                       # la última decisión sobre un clip manda
        clave = f"{r.get('session_id')}/{r.get('clip_id')}"
        if clave in vistos:
            continue
        vistos.add(clave)
        session_dir = stream_data / r["session_id"]
        encontrado = _buscar_clip(session_dir, r["clip_id"]) if session_dir.exists() else None
        if encontrado is None:
            avisos.append(f"{clave}: no está en {stream_data}")
            continue
        chunk_file, item = encontrado
        rango = item.get("rango") or {}
        inicio, fin = item.get("inicio") or rango.get("inicio"), item.get("fin") or rango.get("fin")
        texto = _transcripcion_chunk(session_dir / "chunks" / chunk_file.stem)
        if not (inicio and fin and texto):
            avisos.append(f"{clave}: sin rango o sin transcripción")
            continue
        meta = _leer_json(session_dir / "metadata.json")
        aprobado = r.get("accion") in ("aprobado", "editado")
        j = r.get("juez") or {}
        casos.append({
            "id": f"{nicho[:2]}-corr-{len(casos) + 1:03d}",
            "nicho": nicho,
            "origen": "correccion",
            "fuente": f"correcciones.jsonl · {r['session_id']} · {r['clip_id']}",
            "clave_correccion": clave,
            "video": {"titulo": meta.get("title") or meta.get("fulltitle"),
                      "canal": meta.get("uploader") or meta.get("channel")},
            "candidato": {"inicio": inicio, "fin": fin},
            "transcripcion": ventana(texto, inicio, fin),
            "esperado": {"publicar": aprobado, **({"tipo": j["tipo"]} if aprobado and j.get("tipo") else {})},
            "evidencia": f"{r.get('accion')} por el editor" + (f": {r['razon']}" if r.get("razon") else ""),
        })
    return list(reversed(casos)), avisos


def casos_de_muestra(nicho: str) -> tuple[list[dict], list[str]]:
    from investigacion import comun

    carpeta = comun.carpeta_nicho(nicho)
    archivo = carpeta / "muestra.jsonl"
    if not archivo.exists():
        return [], [f"sin {archivo}"]
    casos, avisos = [], []
    for fila in (json.loads(l) for l in archivo.read_text(encoding="utf-8").splitlines() if l.strip()):
        trans = carpeta / "muestra" / str(fila["id"]) / "transcripcion.txt"
        if not trans.exists():
            avisos.append(f"muestra {fila['id']}: sin transcripcion.txt")
            continue
        texto = trans.read_text(encoding="utf-8").strip()
        if not texto:
            avisos.append(f"muestra {fila['id']}: transcripción vacía")
            continue
        grupo = fila.get("grupo")
        casos.append({
            "id": f"{nicho[:2]}-mues-{len(casos) + 1:03d}",
            "nicho": nicho,
            "origen": "muestra",
            "fuente": f"muestra.jsonl · @{fila.get('cuenta')} · {fila['id']}",
            # Sin la descripción del clip: es el gancho que escribió el clipper y adelantaría la respuesta.
            "video": {"titulo": None, "canal": fila.get("universo")},
            "candidato": {"inicio": "00:00", "fin": _mmss(fila.get("duracion_s") or 60)},
            "transcripcion": texto,
            "esperado": {"publicar": grupo in ("top", "propia_top")},
            "evidencia": f"grupo {grupo} · outlier {fila.get('outlier')} · {fila.get('vistas')} vistas",
        })
    return casos, avisos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("nicho")
    ap.add_argument("--stream-data", type=Path, default=_legacy.LEGACY / "stream_data",
                    help="carpeta de sesiones del piloto (default: legacy/stream_data)")
    args = ap.parse_args(argv)

    corr, avisos_c = casos_de_correcciones(args.nicho, args.stream_data)
    mues, avisos_m = casos_de_muestra(args.nicho)
    todos = corr + mues
    for aviso in avisos_c + avisos_m:
        print(f"  ⚠ {aviso}")
    if not todos:
        print("No se pudo armar ningún caso.")
        return 1
    salida = casos_mod.DIR_CASOS / f"{args.nicho}.yaml"
    casos_mod.guardar(todos, salida)
    buenos = sum(1 for c in todos if c["esperado"]["publicar"])
    print(f"[EXPORT] {len(todos)} casos ({len(corr)} de correcciones, {len(mues)} de la muestra) · "
          f"{buenos} publicar / {len(todos) - buenos} no publicar → {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
