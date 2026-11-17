"""CLIP-33 — el operador pega el link del video publicado en la revisión: queda en el clip y en publicados.jsonl."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import review_actions  # noqa: E402


@pytest.mark.parametrize("url, esperado", [
    ("https://www.tiktok.com/@nandoclips93/video/7695416739412184340?lang=es", ("tiktok", "7695416739412184340")),
    ("https://youtube.com/shorts/AbC123xyz_-", ("youtube", "AbC123xyz_-")),
    ("https://www.youtube.com/watch?v=eudv9pU4Vvo", ("youtube", "eudv9pU4Vvo")),
])
def test_video_de_link(url, esperado):
    assert review_actions.video_de_link(url) == esperado


def test_link_no_reconocido():
    with pytest.raises(review_actions.LinkInvalidoError):
        review_actions.video_de_link("https://vm.tiktok.com/ZMabc/")   # link corto: no trae el id


def test_registrar_link_guarda_en_clip_y_en_publicados(tmp_path, monkeypatch):
    sesion = tmp_path / "20261009_100000"
    (sesion / "contenido_chunks").mkdir(parents=True)
    (sesion / "pipeline_estado.json").write_text('{"config": "nicho_test"}', encoding="utf-8")
    (sesion / "contenido_chunks" / "chunk_001.json").write_text(json.dumps(
        {"contenido": [{"clip_id": "clip_c001_01", "publicar": True, "texto_linea1": "a"}]}), encoding="utf-8")
    monkeypatch.setattr(review_actions, "STREAM_DATA", tmp_path)
    registros = []
    monkeypatch.setattr(review_actions, "registrar_publicado", lambda nicho, r: registros.append((nicho, r)))

    vista = review_actions.registrar_link_publicado(
        "20261009_100000", "clip_c001_01", " https://www.tiktok.com/@cuenta/video/123456 ")

    assert vista["publicado"]["tiktok"] == {"url": "https://www.tiktok.com/@cuenta/video/123456", "video_id": "123456"}
    assert registros[0][0] == "nicho_test" and registros[0][1]["video_id"] == "123456"
