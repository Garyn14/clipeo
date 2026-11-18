"""
retirar.py — CLIP-36 (R-01): retiro inmediato ante una solicitud de un canal o una persona.

    python -m investigacion.retirar --canal "Panorama" [--aplicar]
    python -m investigacion.retirar --persona "Tío Fritz" [--aplicar]

Lista todos los clips de ese canal o persona (sesiones en stream_data/) y su estado en las colas de
publicación, con el link si ya salió. Con --aplicar: cancela lo que sigue en cola y agrega el canal o la persona a
config/exclusion.yaml (así no se vuelve a procesar, aprobar ni enviar). Lo ya publicado se baja a mano en cada
plataforma (las APIs no permiten borrar en TikTok): el reporte deja la lista con los links.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from core import exclusion

LEGACY = Path(__file__).resolve().parent.parent


def _stream_data() -> Path:
    env = os.environ.get("CLIPEO_STREAM_DATA")
    return Path(env).resolve() if env else LEGACY / "stream_data"


def _leer(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _coincide(sesion: dict, item: dict, canal: str | None, persona: str | None) -> bool:
    n = exclusion.normalizar
    fuente = item.get("fuente") or sesion.get("fuente") or {}
    canales = {n(fuente.get("canal_origen")), n((sesion.get("video") or {}).get("canal"))} - {""}
    if canal and n(canal) in canales:
        return True
    return bool(persona) and n(persona) == n(fuente.get("sobre"))


def buscar_clips(stream_data: Path, canal: str | None, persona: str | None) -> list[dict]:
    """Clips (cortados) de las sesiones que coinciden con el canal o la persona."""
    encontrados = []
    for estado_p in sorted(stream_data.glob("*/pipeline_estado.json")):
        sesion = _leer(estado_p)
        for item in _leer(estado_p.parent / "contenido_final.json").get("contenido", []):
            if item.get("clip_id") and _coincide(sesion, item, canal, persona):
                links = [v.get("url") for v in (item.get("publicado") or {}).values() if v.get("url")]
                encontrados.append({"session_id": estado_p.parent.name, "clip_id": item["clip_id"],
                                    "titulo": " / ".join(x for x in (item.get("texto_linea1"),
                                                                     item.get("texto_linea2")) if x),
                                    "links": links})
    return encontrados


def _publicaciones(conn, clips: list[dict]) -> dict[tuple, list[dict]]:
    por_clip: dict[tuple, list[dict]] = {}
    for c in clips:
        filas = conn.execute("SELECT plataforma, estado FROM publicaciones WHERE session_id = ? AND clip_id = ?",
                             (c["session_id"], c["clip_id"])).fetchall()
        por_clip[(c["session_id"], c["clip_id"])] = [dict(f) for f in filas]
    return por_clip


def retirar(canal: str | None, persona: str | None, aplicar: bool, stream_data: Path | None = None,
            conn=None) -> dict:
    clips = buscar_clips(stream_data or _stream_data(), canal, persona)
    cerrar = conn is None
    if conn is None:
        sys.path.insert(0, str(LEGACY / "backend"))
        os.environ.setdefault("PUBLICACION_MOTOR", "0")
        from app.publicacion import db
        conn = db.conectar()
    try:
        from app.publicacion import cola
        motivo = f"retiro R-01: {canal or persona}"
        antes = _publicaciones(conn, clips)
        cancelados = 0
        if aplicar:
            for c in clips:
                if any(p["estado"] == "en_cola" for p in antes[(c["session_id"], c["clip_id"])]):
                    cola.cancelar_por_clip(conn, c["session_id"], c["clip_id"], motivo)
                    cancelados += 1
            exclusion.agregar(canal=canal, persona=persona)
        for c in clips:
            c["colas"] = _publicaciones(conn, [c])[(c["session_id"], c["clip_id"])]
        return {"clips": clips, "cancelados": cancelados,
                "a_mano": [c for c in clips if c["links"] or any(p["estado"] in ("en_bandeja", "sin_confirmar")
                                                                  for p in c["colas"])]}
    finally:
        if cerrar:
            conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-36: retiro inmediato de clips de un canal o persona (R-01)")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--canal", help="canal de origen (uploader de yt-dlp)")
    grupo.add_argument("--persona", help="persona o entidad (de quién trata el video)")
    ap.add_argument("--aplicar", action="store_true", help="cancelar lo que sigue en cola y agregar a la exclusión")
    args = ap.parse_args()

    r = retirar(args.canal, args.persona, args.aplicar)
    quien = args.canal or args.persona
    print(f"[RETIRO] {quien}: {len(r['clips'])} clip(s)")
    for c in r["clips"]:
        colas = ", ".join(f"{p['plataforma']}={p['estado']}" for p in c["colas"]) or "sin cola"
        print(f"  · {c['session_id']}/{c['clip_id']}  «{c['titulo']}»  [{colas}]")
        for link in c["links"]:
            print(f"      publicado: {link}")
    if args.aplicar:
        print(f"[RETIRO] {r['cancelados']} clip(s) cancelados en cola · «{quien}» agregado a config/exclusion.yaml")
    else:
        print("[RETIRO] Vista previa: nada cambió. Usa --aplicar para cancelar y excluir.")
    if r["a_mano"]:
        print(f"[RETIRO] ⚠ {len(r['a_mano'])} clip(s) ya salieron: bajarlos a mano en cada plataforma (links arriba).")


if __name__ == "__main__":
    sys.exit(main())
