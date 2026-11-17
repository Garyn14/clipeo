"""
clip_ids.py — Nombre del archivo de clip (clips/<clip_id>.mp4) de cada entrada de contenido.

Dos esquemas conviven:
  - Actual: el pipeline corta cada chunk con prefijo propio (clip_c002_01, clip_c002_02...) y
    guarda ese nombre en la entrada como "clip_id". Reintentar el corte de un chunk solo
    toca sus propios archivos — no corre la numeración de los chunks siguientes.
  - Legacy (sesiones previas a 2026-09-30): numeración global clip_001, clip_002... en el orden
    de contenido_chunks/*.json. Se reconstruye contando, como siempre.

Uso interno:
    from core.clip_ids import prefijo_chunk, asignar_clip_ids
"""

from typing import Callable, Iterable


def prefijo_chunk(chunk_id: str) -> str:
    """chunk_002 → clip_c002 (los clips quedan como clip_c002_01, clip_c002_02...)."""
    return f"clip_c{chunk_id.rsplit('_', 1)[-1]}"


def asignar_clip_ids(
    chunks: Iterable[tuple[object, list[dict]]],
    incluir: Callable[[dict], bool],
) -> list[tuple[object, int, str]]:
    """
    chunks  — [(clave_chunk, contenido)] en orden de chunk.
    incluir — qué entradas tienen (o tuvieron) clip cortado.
    Devuelve [(clave_chunk, pos, clip_id)] en orden.
    """
    resultado = []
    indice_legacy = 1
    for clave, contenido in chunks:
        for pos, item in enumerate(contenido):
            if not incluir(item):
                continue
            clip_id = item.get("clip_id")
            if not clip_id:
                clip_id = f"clip_{indice_legacy:03d}"
                indice_legacy += 1
            resultado.append((clave, pos, clip_id))
    return resultado
