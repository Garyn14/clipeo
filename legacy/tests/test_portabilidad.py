"""CLIP-19 — portabilidad: FFmpeg sin rutas personales y fuentes incluidas en el repo."""

import os
from pathlib import Path

from core import utils
from edicion_video import agent4_video_cutter as a4


def test_ffmpeg_usa_variable_si_esta_definida(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN_DIR", "/opt/ffmpeg/bin")
    assert utils._ffmpeg_bin_dir() == "/opt/ffmpeg/bin"


def test_ffmpeg_del_sistema_no_toca_el_path(monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN_DIR", raising=False)
    monkeypatch.setattr(utils.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    assert utils._ffmpeg_bin_dir() is None


def test_ffmpeg_sin_nada_en_linux_devuelve_none(monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN_DIR", raising=False)
    monkeypatch.setattr(utils.shutil, "which", lambda _: None)
    monkeypatch.setattr(utils.sys, "platform", "linux")
    assert utils._ffmpeg_bin_dir() is None


def test_ffmpeg_busca_winget_en_windows(monkeypatch, tmp_path):
    bin_dir = tmp_path / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_x" / "ffmpeg-8.1-full_build" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "ffmpeg.exe").write_bytes(b"")
    monkeypatch.delenv("FFMPEG_BIN_DIR", raising=False)
    monkeypatch.setattr(utils.shutil, "which", lambda _: None)
    monkeypatch.setattr(utils.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert utils._ffmpeg_bin_dir() == str(bin_dir)


def test_setup_ffmpeg_path_agrega_el_directorio(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN_DIR", "/opt/ffmpeg/bin")
    monkeypatch.setenv("PATH", "/usr/bin")
    utils.setup_ffmpeg_path()
    assert os.environ["PATH"].split(os.pathsep)[0] == "/opt/ffmpeg/bin"


def test_fuentes_incluidas_existen():
    assert (a4._FONTS_DIR / "Anton-Regular.ttf").is_file()
    assert (a4._FONTS_DIR / "ArchivoBlack-Regular.ttf").is_file()


def test_prepare_font_usa_la_fuente_incluida(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    rel, nombre = a4._prepare_font()
    assert nombre == "Anton"
    assert rel == "stream_data/anton.ttf"
    assert (tmp_path / rel).is_file()


def test_sin_rutas_personales_en_codigo():
    raiz = Path(__file__).resolve().parents[1]
    for py in raiz.rglob("*.py"):
        if "tests" in py.parts or "node_modules" in py.parts:
            continue
        texto = py.read_text(encoding="utf-8", errors="ignore")
        assert "C:\\Users\\" not in texto, py
