"""
clip_index.py — Mapeo estable entre clip_NNN (archivo físico en clips/) y su
entrada de origen en contenido_chunks/<chunk>.json.

Factorizado de revisar_clips.py (líneas 82-97), pero pensado para resolverse
por request en vez de una sola vez al arrancar un loop batch. Eso introduce un
problema que revisar_clips.py no tenía: si numerás por "publicar == true" y
después una descarte-por-API apaga ese flag, la próxima reconstrucción del
índice correría los números de los clips siguientes del mismo chunk, que ya
tienen archivo físico con el número viejo.

Por eso acá el descarte vía API no solo pone publicar=false: además marca
`revision_descartado: true` en la entrada, y build_clip_index() cuenta un
ítem si tiene publicar=true **o** ese marcador — así una entrada nunca pierde
su posición en la numeración una vez que llegó a tener un archivo cortado,
aunque se descarte después.

Desde 2026-09-30 el pipeline guarda el nombre del clip en la entrada ("clip_id", ej.
clip_c002_01) y se usa directo; la numeración contada queda solo para sesiones viejas
(ver core/clip_ids.py).
"""

import json
from pathlib import Path

from app.paths import PROJECT_ROOT  # noqa: F401 — parchea sys.path antes de importar core/
from core.clip_ids import asignar_clip_ids


def _chunk_files(session_dir: Path) -> list[Path]:
    contenido_chunks_dir = session_dir / "contenido_chunks"
    if not contenido_chunks_dir.exists():
        return []
    return sorted(contenido_chunks_dir.glob("*.json"))


def _load_contenido(chunk_file: Path) -> list[dict]:
    return json.loads(chunk_file.read_text(encoding="utf-8")).get("contenido", [])


def build_clip_index(session_dir: Path) -> list[dict]:
    """Lista ordenada de {clip_id, chunk_file, pos} — mismo orden que usó Agente 4."""
    chunks = [(cf, _load_contenido(cf)) for cf in _chunk_files(session_dir)]
    return [
        {"clip_id": clip_id, "chunk_file": cf, "pos": pos}
        for cf, pos, clip_id in asignar_clip_ids(
            chunks, lambda item: item.get("publicar") or item.get("revision_descartado")
        )
    ]


def find_clip_entry(session_dir: Path, clip_id: str) -> dict | None:
    for entrada in build_clip_index(session_dir):
        if entrada["clip_id"] == clip_id:
            return entrada
    return None


def load_clip_view(session_dir: Path, entrada: dict) -> dict:
    """Combina el JSON editorial (contenido_chunks) con el técnico (clips/clip_NNN.json)."""
    contenido = _load_contenido(entrada["chunk_file"])
    item      = contenido[entrada["pos"]]

    clip_json_path = session_dir / "clips" / f"{entrada['clip_id']}.json"
    clip_mp4_path  = session_dir / "clips" / f"{entrada['clip_id']}.mp4"
    tecnico = {}
    if clip_json_path.exists():
        tecnico = json.loads(clip_json_path.read_text(encoding="utf-8"))

    return {
        "clip_id":             entrada["clip_id"],
        "score":               item.get("score", 0),
        "texto_linea1":        item.get("texto_linea1", ""),
        "texto_linea2":        item.get("texto_linea2", ""),
        "hashtags":            item.get("hashtags", []),
        "publicacion":         item.get("publicacion", {}),
        "rango_original":      item.get("rango_original", {}),
        "juez":                item.get("juez"),  # por qué lo eligió el juez (None antes del juez)
        "fuente":              item.get("fuente"),  # CLIP-27: medios de terceros (None en streams)
        "descartado":          bool(item.get("revision_descartado", False)),
        "tiene_video":         clip_mp4_path.exists(),
        "listo_para_publicar": tecnico.get("listo_para_publicar", False),
        "publicado":           item.get("publicado", {}),   # CLIP-33: {plataforma: {url, video_id}}
        "control_calidad":     tecnico.get("control_calidad") or [],   # CLIP-51/52: avisos técnicos del clip
    }


def list_clips(session_dir: Path) -> list[dict]:
    return [load_clip_view(session_dir, e) for e in build_clip_index(session_dir)]


def regenerate_contenido_final(session_dir: Path) -> None:
    """Igual que el final de revisar_clips.py: merge de todos los contenido_chunks/*.json."""
    todo = []
    for cf in _chunk_files(session_dir):
        todo.extend(_load_contenido(cf))
    todo.sort(key=lambda c: c.get("score", 0), reverse=True)
    (session_dir / "contenido_final.json").write_text(
        json.dumps({"contenido": todo}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
