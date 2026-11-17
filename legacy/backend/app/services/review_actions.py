"""
review_actions.py — Aprobar / editar / descartar un clip ya cortado, vía API,
en vez del loop de terminal de revisar_clips.py / pipeline.py --revisar.

Reutiliza directo (no reimplementa) las mismas funciones que ya usa
revisar_clips.py: _guardar_evento_correccion, _guardar_evento_descarte
(pipeline.py) y _find_video, _detect_video_info, _prepare_font, _cut_clip
(edicion_video/agent4_video_cutter.py). pipeline.py y agent4_video_cutter.py
no se modifican.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from app.paths import PROJECT_ROOT, STREAM_DATA  # noqa: F401 — parcha sys.path antes de los imports de abajo
from pipeline import _load_config, _guardar_evento_correccion, _guardar_evento_descarte
from edicion_video.agent4_video_cutter import (
    _find_video, _detect_video_info, _prepare_font, _cut_clip,
)
from core.utils import _timestamp_to_seconds
from investigacion.comun import registrar_correccion, registrar_publicado

from app.services.clip_index import find_clip_entry, list_clips, load_clip_view, regenerate_contenido_final


class ClipNotFoundError(Exception):
    pass


def _load_contenido(chunk_file: Path) -> list[dict]:
    return json.loads(chunk_file.read_text(encoding="utf-8")).get("contenido", [])


def _save_contenido(chunk_file: Path, contenido: list[dict]) -> None:
    chunk_file.write_text(
        json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _registrar_correccion(session_dir: Path, clip_id: str, clip: dict, accion: str,
                          titulo_final: str | None = None, razon: str | None = None) -> None:
    """
    Tu decisión en la revisión vuelve al juez (investigacion/<nicho>/correcciones.jsonl):
    junto a la memoria del nicho, es su criterio. Nunca rompe la acción de revisión.
    """
    try:
        estado = json.loads((session_dir / "pipeline_estado.json").read_text(encoding="utf-8"))
        nicho = estado.get("config")
        if not nicho:
            return
        juez = clip.get("juez") or {}
        registrar_correccion(nicho, {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "session_id": session_dir.name,
            "clip_id": clip_id,
            "accion": accion,
            # el título propuesto es el que estaba al momento de decidir (antes de editarlo)
            "juez": {"tipo": juez.get("tipo"), "fuerza": juez.get("fuerza", clip.get("score")),
                     "linea1": clip.get("texto_linea1"), "linea2": clip.get("texto_linea2")},
            "titulo_final": titulo_final,
            "razon": razon,
        })
    except (OSError, json.JSONDecodeError) as e:
        print(f"[REVISION] ⚠ no se pudo registrar la corrección de {clip_id}: {e}")


def _nicho(session_dir: Path) -> str | None:
    estado = json.loads((session_dir / "pipeline_estado.json").read_text(encoding="utf-8"))
    return estado.get("config")


def _encolar_en(plataforma: str, session_dir: Path, clip_id: str, clip: dict, nicho: str) -> None:
    from app.publicacion import cola, db
    from app.publicacion.texto import metadatos_youtube, texto_tiktok, texto_youtube
    titulo = " / ".join(x for x in (clip.get("texto_linea1"), clip.get("texto_linea2")) if x) or None
    if plataforma == "youtube":
        metadatos = metadatos_youtube(clip)
        texto = texto_youtube(metadatos)
    else:
        metadatos, texto = None, texto_tiktok(clip)
    conn = db.conectar()
    try:
        cola.encolar(conn, session_dir.name, clip_id, nicho, str(session_dir / "clips" / f"{clip_id}.mp4"),
                     titulo, texto, plataforma=plataforma, metadatos=metadatos)
    finally:
        conn.close()


def _encolar_publicacion(session_dir: Path, clip_id: str, clip: dict) -> None:
    """Todo clip aprobado entra a la cola de su nicho en cada plataforma (TikTok, YouTube).
    Cada cola por separado: si una falla, la otra entra igual. Nunca rompe la aprobación."""
    try:
        nicho = _nicho(session_dir)
    except Exception as e:
        print(f"[REVISION] ⚠ no se pudo encolar {clip_id} para publicar: {type(e).__name__}: {e}")
        return
    if not nicho:
        return
    from app.publicacion.db import PLATAFORMAS
    for plataforma in PLATAFORMAS:
        try:
            _encolar_en(plataforma, session_dir, clip_id, clip, nicho)
        except Exception as e:
            print(f"[REVISION] ⚠ no se pudo encolar {clip_id} en {plataforma}: {type(e).__name__}: {e}")


def copiar_cola_a_youtube(nicho: str) -> int:
    """Acción única de prueba: copia a la cola de YouTube, en el mismo orden, lo que hoy está
    en cola en TikTok para ese nicho (TikTok no cambia). Idempotente. Devuelve cuántos copió."""
    from app.publicacion import cola, db
    conn = db.conectar()
    try:
        en_tiktok = cola.listar(conn, nicho, "en_cola", plataforma="tiktok")
        ya = {(p["session_id"], p["clip_id"]) for p in cola.listar(conn, nicho, plataforma="youtube")}
    finally:
        conn.close()
    copiadas = 0
    for pub in en_tiktok:
        if (pub["session_id"], pub["clip_id"]) in ya:
            continue
        session_dir = STREAM_DATA / pub["session_id"]
        entrada = find_clip_entry(session_dir, pub["clip_id"])
        if not entrada:
            print(f"[PUBLICACION] ⚠ {pub['session_id']}/{pub['clip_id']} ya no está en su sesión — no se copia")
            continue
        _encolar_en("youtube", session_dir, pub["clip_id"], _load_contenido(entrada["chunk_file"])[entrada["pos"]], nicho)
        copiadas += 1
    return copiadas


def completar_textos_publicacion() -> int:
    """Publicaciones encoladas antes de que existiera `texto`: lo arma desde su sesión.
    Corre al arrancar el backend; las que no tienen copy quedan en NULL. Nunca rompe el arranque."""
    try:
        from app.publicacion import db
        from app.publicacion.texto import texto_tiktok
        conn = db.conectar()
        try:
            completadas = 0
            for fila in conn.execute(
                "SELECT id, session_id, clip_id FROM publicaciones WHERE texto IS NULL AND plataforma = 'tiktok'"
            ).fetchall():
                entrada = find_clip_entry(STREAM_DATA / fila["session_id"], fila["clip_id"])
                if not entrada:
                    continue
                texto = texto_tiktok(_load_contenido(entrada["chunk_file"])[entrada["pos"]])
                if texto:
                    conn.execute("UPDATE publicaciones SET texto = ? WHERE id = ? AND texto IS NULL",
                                 (texto, fila["id"]))
                    completadas += 1
            return completadas
        finally:
            conn.close()
    except Exception as e:
        print(f"[PUBLICACION] ⚠ no se pudieron completar los textos de TikTok: {type(e).__name__}: {e}")
        return 0


def _sacar_de_cola(session_dir: Path, clip_id: str, motivo: str) -> None:
    try:
        from app.publicacion import cola, db
        conn = db.conectar()
        try:
            cola.cancelar_por_clip(conn, session_dir.name, clip_id, motivo)
        finally:
            conn.close()
    except Exception as e:
        print(f"[REVISION] ⚠ no se pudo sacar {clip_id} de la cola de publicación: {type(e).__name__}: {e}")


def _resolve(session_id: str, clip_id: str) -> tuple[Path, dict]:
    session_dir = STREAM_DATA / session_id
    entrada = find_clip_entry(session_dir, clip_id)
    if not entrada:
        raise ClipNotFoundError(clip_id)
    return session_dir, entrada


def approve_clip(session_id: str, clip_id: str) -> dict:
    session_dir, entrada = _resolve(session_id, clip_id)

    clip_json_path = session_dir / "clips" / f"{clip_id}.json"
    if not clip_json_path.exists():
        raise ClipNotFoundError(clip_id)  # descartado o nunca cortado

    meta = json.loads(clip_json_path.read_text(encoding="utf-8"))
    meta["listo_para_publicar"] = True
    clip_json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    clip = _load_contenido(entrada["chunk_file"])[entrada["pos"]]
    _registrar_correccion(session_dir, clip_id, clip, "aprobado")
    _encolar_publicacion(session_dir, clip_id, clip)
    return load_clip_view(session_dir, entrada)


def edit_clip(
    session_id: str, clip_id: str, canal_id: str | None,
    texto_linea1: str | None, texto_linea2: str | None,
    inicio: str | None, fin: str | None,
) -> dict:
    session_dir, entrada = _resolve(session_id, clip_id)
    # el archivo se re-corta y queda sin aprobar: sale de la cola hasta que se apruebe de nuevo
    _sacar_de_cola(session_dir, clip_id, "clip editado en la revisión (hay que volver a aprobarlo)")

    contenido = _load_contenido(entrada["chunk_file"])
    clip      = contenido[entrada["pos"]]
    rango     = clip.setdefault("rango_original", {})

    l1 = texto_linea1 if texto_linea1 is not None else clip.get("texto_linea1", "")
    l2 = texto_linea2 if texto_linea2 is not None else clip.get("texto_linea2", "")
    nuevo_inicio = inicio if inicio is not None else rango.get("inicio", "")
    nuevo_fin    = fin    if fin    is not None else rango.get("fin", "")

    config, _ = _load_config(canal_id)
    _guardar_evento_correccion(clip, l1, l2, nuevo_inicio, nuevo_fin, session_dir, config)

    video_path = _find_video(session_dir)
    if not video_path:
        raise FileNotFoundError(f"No se encontró el video original en {session_dir}")
    font_rel, _ = _prepare_font()
    vid_info = _detect_video_info(video_path)

    clip_path = session_dir / "clips" / f"{clip_id}.mp4"
    meta_path = session_dir / "clips" / f"{clip_id}.json"

    ok = _cut_clip(
        video_path, nuevo_inicio, nuevo_fin, l1, l2,
        clip_path, font_rel, vid_info["has_letterbox"], vid_info["bar_height"],
    )
    if not ok:
        raise RuntimeError("El re-corte con FFmpeg falló — revisar el clip manualmente")

    nueva_dur = _timestamp_to_seconds(nuevo_fin) - _timestamp_to_seconds(nuevo_inicio)
    if (l1, l2) != (clip.get("texto_linea1", ""), clip.get("texto_linea2", "")):
        _registrar_correccion(session_dir, clip_id, dict(clip), "editado",
                              titulo_final=" / ".join(x for x in (l1, l2) if x))
    clip["texto_linea1"] = l1
    clip["texto_linea2"] = l2
    rango["inicio"] = nuevo_inicio
    rango["fin"] = nuevo_fin
    rango["duracion_segundos"] = nueva_dur
    clip["publicar"] = True
    clip.pop("revision_descartado", None)  # un edit "resucita" un clip previamente descartado

    contenido[entrada["pos"]] = clip
    _save_contenido(entrada["chunk_file"], contenido)

    meta_path.write_text(
        json.dumps({
            "clip": clip_path.name,
            "texto_linea1": l1,
            "texto_linea2": l2,
            "hashtags": clip.get("hashtags", []),
            "score": clip.get("score", 0),
            "duracion_segundos": nueva_dur,
            "listo_para_publicar": False,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    regenerate_contenido_final(session_dir)
    return load_clip_view(session_dir, entrada)


def discard_clip(session_id: str, clip_id: str, canal_id: str | None, razon: str | None) -> None:
    session_dir, entrada = _resolve(session_id, clip_id)

    contenido = _load_contenido(entrada["chunk_file"])
    clip      = contenido[entrada["pos"]]

    if razon:
        config, _ = _load_config(canal_id)
        _guardar_evento_descarte(clip, razon, session_dir, config)

    _registrar_correccion(session_dir, clip_id, dict(clip), "descartado", razon=razon)
    _sacar_de_cola(session_dir, clip_id, "clip descartado en la revisión")
    clip["publicar"] = False
    clip["revision_descartado"] = True  # conserva el lugar en la numeración (ver clip_index.py)
    contenido[entrada["pos"]] = clip
    _save_contenido(entrada["chunk_file"], contenido)

    (session_dir / "clips" / f"{clip_id}.mp4").unlink(missing_ok=True)
    (session_dir / "clips" / f"{clip_id}.json").unlink(missing_ok=True)

    regenerate_contenido_final(session_dir)


class RevisionIncompletaError(Exception):
    def __init__(self, pendientes: list[str]):
        super().__init__(f"{len(pendientes)} clip(s) sin decidir: {', '.join(pendientes)}")
        self.pendientes = pendientes


class RevisionNoDisponibleError(Exception):
    pass


def finalizar_revision(session_id: str) -> None:
    """
    Cierra el círculo "Revisión" → "Fin": exige que cada clip esté aprobado
    (listo_para_publicar) o descartado. Escribe pipeline_estado.json vía ChunkManager
    (mismo formato y escritura atómica que el pipeline).
    """
    from core.chunk_manager import ChunkManager
    from app.services import pipeline_runner

    session_dir = STREAM_DATA / session_id
    if pipeline_runner.run_activa(session_id):
        raise RevisionNoDisponibleError("La sesión tiene una corrida en curso")

    mgr = ChunkManager(session_dir)
    if not mgr.cargar_estado():
        raise RevisionNoDisponibleError("Sesión sin pipeline_estado.json")
    chunks = mgr._estado.get("chunks", {})
    if not chunks or any(c.get("estado") != "completado" for c in chunks.values()):
        raise RevisionNoDisponibleError("Hay chunks sin terminar — termina o reintenta esos pasos primero")

    pendientes = [
        c["clip_id"] for c in list_clips(session_dir)
        if not c["descartado"] and not c["listo_para_publicar"]
    ]
    if pendientes:
        raise RevisionIncompletaError(pendientes)

    ahora = datetime.now().isoformat(timespec="seconds")
    mgr.actualizar_paso(None, "revision", estado="ok", fin=ahora, nota="revisado en la web")
    mgr.actualizar_paso(None, "fin", estado="ok", fin=ahora)


# ── CLIP-33: link del video publicado ────────────────────────────────────────────────────────────
_PATRONES_LINK = [
    ("tiktok", re.compile(r"tiktok\.com/@[^/]+/video/(\d+)")),
    ("youtube", re.compile(r"youtube\.com/shorts/([\w-]{6,})")),
    ("youtube", re.compile(r"youtu\.be/([\w-]{6,})")),
    ("youtube", re.compile(r"youtube\.com/watch\?(?:.*&)?v=([\w-]{6,})")),
]


class LinkInvalidoError(ValueError):
    pass


def video_de_link(url: str) -> tuple[str, str]:
    """(plataforma, video_id) de un link de TikTok o YouTube; LinkInvalidoError si no se reconoce."""
    for plataforma, patron in _PATRONES_LINK:
        m = patron.search(url or "")
        if m:
            return plataforma, m.group(1)
    raise LinkInvalidoError("Pega el link completo del video (TikTok: …/@cuenta/video/123…; YouTube: …/shorts/…)")


def registrar_link_publicado(session_id: str, clip_id: str, url: str) -> dict:
    """Guarda en el clip el link del video publicado y lo registra para la evaluación (etiqueta por audiencia)."""
    session_dir, entrada = _resolve(session_id, clip_id)
    plataforma, video_id = video_de_link(url.strip())
    contenido = _load_contenido(entrada["chunk_file"])
    contenido[entrada["pos"]].setdefault("publicado", {})[plataforma] = {"url": url.strip(), "video_id": video_id}
    _save_contenido(entrada["chunk_file"], contenido)
    nicho = _nicho(session_dir)
    if nicho:
        registrar_publicado(nicho, {"fecha": datetime.now().isoformat(timespec="seconds"),
                                    "session_id": session_dir.name, "clip_id": clip_id,
                                    "plataforma": plataforma, "video_id": video_id, "url": url.strip()})
    return load_clip_view(session_dir, entrada)
