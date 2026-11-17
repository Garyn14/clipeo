"""
===========================================
  REVISAR CLIPS YA GENERADOS — IDEA MILLONARIA
===========================================

Revisa manualmente los clips de una sesión que ya se procesó SIN
`--revisar`. No vuelve a correr transcripción ni Agentes 1-3: lee el
contenido ya generado (contenido_chunks/*.json) y los clips ya cortados
(clips/clip_NNN.mp4), y por cada uno pregunta la misma acción que el
modo --revisar del pipeline (aprobar / editar título / editar rango /
editar ambos / descartar).

- Aprobar: no toca el clip.
- Descartar: borra el .mp4 + .json y registra el descarte como evento.
- Editar título y/o rango: vuelve a cortar SOLO ese clip (ffmpeg) con el
  texto/rango nuevo, sobrescribiendo el .mp4, y registra la corrección
  como evento — igual que hace pipeline.py durante --revisar.

Al final reescribe contenido_chunks/<chunk>.json y regenera
contenido_final.json con los cambios.

Uso:
  python revisar_clips.py stream_data/<session_id>/ [--config <canal_id>]
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
from pathlib import Path

from pipeline import (
    _load_config,
    _guardar_evento_correccion,
    _guardar_evento_descarte,
)
from edicion_video.agent4_video_cutter import (
    _find_video,
    _detect_video_info,
    _prepare_font,
    _cut_clip,
)
from core.clip_ids import asignar_clip_ids
from core.utils import _timestamp_to_seconds


def _clip_paths(clips_dir: Path, clip_id: str) -> tuple[Path, Path]:
    return (
        clips_dir / f"{clip_id}.mp4",
        clips_dir / f"{clip_id}.json",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Revisa (aprueba/edita/descarta) los clips ya generados de una sesión sin re-procesar nada."
    )
    parser.add_argument("session_dir", help="Ruta a stream_data/<session_id>/")
    parser.add_argument("--config", default=None, help="canal_id (igual que en pipeline.py)")
    args = parser.parse_args()

    session_dir = Path(args.session_dir)
    if not session_dir.exists():
        print(f"[REVISAR] ❌ No existe la sesión: {session_dir}")
        sys.exit(1)

    contenido_chunks_dir = session_dir / "contenido_chunks"
    clips_dir = session_dir / "clips"
    if not contenido_chunks_dir.exists():
        print(f"[REVISAR] ❌ No hay contenido_chunks/ en: {session_dir}")
        sys.exit(1)

    config, _ = _load_config(args.config)

    chunk_files = sorted(contenido_chunks_dir.glob("*.json"))
    if not chunk_files:
        print(f"[REVISAR] ❌ contenido_chunks/ está vacío")
        sys.exit(1)

    # Recolectar, en orden global, solo las entradas marcadas publicar=true, con el
    # nombre de clip que les dio Agente 4 (ver core/clip_ids.py).
    chunk_data = {cf: json.loads(cf.read_text(encoding="utf-8")) for cf in chunk_files}
    chunks = [(cf, chunk_data[cf].get("contenido", [])) for cf in chunk_files]

    entradas = [  # cada item: {chunk_file, contenido, pos, clip_id}
        {"chunk_file": cf, "contenido": chunk_data[cf].get("contenido", []), "pos": pos, "clip_id": clip_id}
        for cf, pos, clip_id in asignar_clip_ids(chunks, lambda item: item.get("publicar"))
    ]

    faltantes = [e["clip_id"] for e in entradas if not (clips_dir / f"{e['clip_id']}.mp4").exists()]
    if faltantes:
        print(
            f"[REVISAR] ⚠ {len(faltantes)} clip(s) marcados 'publicar' en contenido_chunks/ "
            f"sin .mp4 en clips/ ({', '.join(faltantes[:5])}) — revisá manualmente antes de continuar."
        )
        sys.exit(1)

    video_path = _find_video(session_dir)
    if not video_path:
        print(f"[REVISAR] ❌ No se encontró el video original en: {session_dir}")
        sys.exit(1)

    font_rel, font_name = _prepare_font()
    vid_info = _detect_video_info(video_path)
    has_lb, bar_h = vid_info["has_letterbox"], vid_info["bar_height"]

    print(f"\n[REVISAR] Sesión : {session_dir.name}")
    print(f"[REVISAR] Video  : {video_path.name}")
    print(f"[REVISAR] Clips  : {len(entradas)} para revisar\n")

    chunks_modificados = set()
    n_aprobados = n_editados = n_descartados = 0

    for i, e in enumerate(entradas, 1):
        clip = e["contenido"][e["pos"]]
        rango = clip.get("rango_original", {})
        clip_path, meta_path = _clip_paths(clips_dir, e["clip_id"])

        print(
            f"{'─'*42}\n"
            f"Clip {i}/{len(entradas)} — {clip_path.name} — Score {clip.get('score', 0)}/10\n"
            f"Rango  : {rango.get('inicio', '?')} → {rango.get('fin', '?')}"
            f"  ({rango.get('duracion_segundos', '?')}s)\n"
            f"Línea 1: {clip.get('texto_linea1', '')}\n"
            f"Línea 2: {clip.get('texto_linea2', '')}\n"
            f"{'─'*42}\n"
            f"[A]probar  [T]ítulo  [R]ango  [E]ditar ambos  [D]escartar"
        )

        while True:
            try:
                accion = input("→ ").strip().upper()
            except EOFError:
                accion = "A"

            if accion == "A":
                print("✅ Aprobado (sin cambios)")
                n_aprobados += 1
                break

            elif accion in ("T", "R", "E"):
                l1, l2 = clip.get("texto_linea1", ""), clip.get("texto_linea2", "")
                inicio, fin = rango.get("inicio", ""), rango.get("fin", "")
                try:
                    if accion in ("T", "E"):
                        l1 = input("Línea 1: ").strip()
                        l2 = input("Línea 2: ").strip()
                    if accion in ("R", "E"):
                        inicio = input("Nuevo inicio (HH:MM:SS): ").strip()
                        fin    = input("Nuevo fin   (HH:MM:SS): ").strip()
                except EOFError:
                    pass

                _guardar_evento_correccion(
                    clip, l1, l2, inicio, fin, session_dir, config,
                )

                clip["texto_linea1"] = l1
                clip["texto_linea2"] = l2
                clip["rango_original"]["inicio"] = inicio
                clip["rango_original"]["fin"]    = fin
                nueva_dur = _timestamp_to_seconds(fin) - _timestamp_to_seconds(inicio)
                clip["rango_original"]["duracion_segundos"] = nueva_dur

                print(f"[REVISAR] Recortando de nuevo {clip_path.name}...")
                ok = _cut_clip(
                    video_path, inicio, fin, l1, l2,
                    clip_path, font_rel, has_lb, bar_h,
                )
                if ok:
                    meta = {
                        "clip": clip_path.name,
                        "texto_linea1": l1,
                        "texto_linea2": l2,
                        "hashtags": clip.get("hashtags", []),
                        "score": clip.get("score", 0),
                        "duracion_segundos": nueva_dur,
                        "listo_para_publicar": False,
                    }
                    meta_path.write_text(
                        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print("✅ Clip re-cortado y aprendizaje guardado")
                else:
                    print("❌ Falló el re-corte — revisá el clip manualmente")
                chunks_modificados.add(e["chunk_file"])
                n_editados += 1
                break

            elif accion == "D":
                try:
                    razon = input("Razón (Enter para omitir): ").strip()
                except EOFError:
                    razon = ""
                if razon:
                    _guardar_evento_descarte(clip, razon, session_dir, config)
                    print("✅ Descarte registrado como aprendizaje")
                else:
                    print("⏭ Clip descartado")

                clip["publicar"] = False
                clip_path.unlink(missing_ok=True)
                meta_path.unlink(missing_ok=True)
                chunks_modificados.add(e["chunk_file"])
                n_descartados += 1
                break

            else:
                print("Opción no válida. Usa A, T, R, E o D.")

        print()

    for cf in chunks_modificados:
        cf.write_text(
            json.dumps({"contenido": chunk_data[cf].get("contenido", [])}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # Regenerar contenido_final.json con los cambios
    todo = []
    for cf in chunk_files:
        todo.extend(chunk_data[cf].get("contenido", []))
    todo.sort(key=lambda c: c.get("score", 0), reverse=True)
    (session_dir / "contenido_final.json").write_text(
        json.dumps({"contenido": todo}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"{'═'*47}")
    print(f"  REVISIÓN COMPLETADA")
    print(f"  Aprobados  : {n_aprobados}")
    print(f"  Editados   : {n_editados}")
    print(f"  Descartados: {n_descartados}")
    print(f"  Clips en   : {clips_dir}")
    print(f"{'═'*47}\n")


if __name__ == "__main__":
    main()
