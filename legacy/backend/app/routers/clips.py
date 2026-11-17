from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.paths import STREAM_DATA
from app.services import clip_index, review_actions

router = APIRouter(prefix="/sessions/{session_id}/clips", tags=["clips"])


class EditBody(BaseModel):
    canal_id: str | None = None
    texto_linea1: str | None = None
    texto_linea2: str | None = None
    inicio: str | None = None
    fin: str | None = None


class PublicadoBody(BaseModel):
    url: str


class DiscardBody(BaseModel):
    canal_id: str | None = None
    razon: str | None = None


@router.get("")
def get_clips(session_id: str):
    session_dir = STREAM_DATA / session_id
    if not session_dir.exists():
        raise HTTPException(404, "Sesión no encontrada")
    return clip_index.list_clips(session_dir)


@router.get("/{clip_id}/video")
def get_clip_video(session_id: str, clip_id: str):
    video_path = STREAM_DATA / session_id / "clips" / f"{clip_id}.mp4"
    if not video_path.exists():
        raise HTTPException(404, "Clip no encontrado")
    return FileResponse(video_path, media_type="video/mp4")


@router.post("/{clip_id}/approve")
def approve(session_id: str, clip_id: str):
    try:
        return review_actions.approve_clip(session_id, clip_id)
    except review_actions.ClipNotFoundError:
        raise HTTPException(404, "Clip no encontrado")


@router.post("/{clip_id}/edit")
def edit(session_id: str, clip_id: str, body: EditBody):
    try:
        return review_actions.edit_clip(
            session_id, clip_id, body.canal_id,
            body.texto_linea1, body.texto_linea2, body.inicio, body.fin,
        )
    except review_actions.ClipNotFoundError:
        raise HTTPException(404, "Clip no encontrado")
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))


@router.post("/{clip_id}/discard")
def discard(session_id: str, clip_id: str, body: DiscardBody):
    try:
        review_actions.discard_clip(session_id, clip_id, body.canal_id, body.razon)
    except review_actions.ClipNotFoundError:
        raise HTTPException(404, "Clip no encontrado")
    return {"ok": True}


@router.post("/{clip_id}/publicado")
def publicado(session_id: str, clip_id: str, body: PublicadoBody):
    """CLIP-33: el operador pega el link del video ya publicado (enlaza el clip con su resultado real)."""
    try:
        return review_actions.registrar_link_publicado(session_id, clip_id, body.url)
    except review_actions.ClipNotFoundError:
        raise HTTPException(404, "Clip no encontrado")
    except review_actions.LinkInvalidoError as e:
        raise HTTPException(422, str(e))
