"""
test_video_capture.py â€” Tests de captura/video_capture.py: parseo del progreso de yt-dlp,
mensaje de error (la lÃ­nea ERROR primero) y el orden de la descarga (metadata primero, para
fallar rÃ¡pido con URLs malas).

Sin red ni yt-dlp/ffmpeg reales: subprocess.Popen y subprocess.run se reemplazan.
"""

import json
import subprocess
from contextlib import contextmanager

import pytest

import captura.video_capture as vc
from captura.video_capture import DescargaError, _parse_progreso


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  _parse_progreso
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def test_parse_progreso_con_total_real():
    p = _parse_progreso("[PROG] 524288000|1048576000|NA|8388608|62|NA|NA")
    assert p == {"bytes": 524288000, "total": 1048576000, "velocidad": 8388608, "eta_s": 62, "pct": 50.0}


def test_parse_progreso_hls_usa_fragmentos():
    # Salida real de yt-dlp con HLS: al empezar, el estimado es igual a lo descargado
    p = _parse_progreso("[PROG] 1024|NA|1024|4954.8|NA|0|3")
    assert p["pct"] == 0.0
    assert p["total"] is None  # el estimado todavÃ­a no significa nada
    p = _parse_progreso("[PROG] 500|NA|1500.0|NA|NA|30|120")
    assert p["pct"] == 25.0
    assert p["total"] == 1500.0


def test_parse_progreso_usa_estimado_sin_total_ni_fragmentos():
    p = _parse_progreso("[PROG] 100|NA|400|NA|NA|NA|NA")
    assert p["total"] == 400
    assert p["pct"] == 25.0
    assert p["velocidad"] is None and p["eta_s"] is None


def test_parse_progreso_sin_datos_de_total():
    assert _parse_progreso("[PROG] 100|NA|NA|50|NA|NA|NA")["pct"] is None


@pytest.mark.parametrize("linea", ["[download] Destination: x.mp4", "[PROG] roto", "[PROG] 1|2|3|4|5", ""])
def test_parse_progreso_linea_ajena(linea):
    assert _parse_progreso(linea) is None


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  _run: mensaje de error
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _PopenFalso:
    def __init__(self, salida: list[str], codigo: int):
        self.stdout = iter(l + "\n" for l in salida)
        self.returncode = codigo

    def wait(self):
        return self.returncode


def test_run_error_empieza_por_la_linea_error(monkeypatch):
    salida = [
        "[youtube] abc: Downloading webpage",
        "WARNING: [youtube] No supported JavaScript runtime could be found",
        "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    ]
    monkeypatch.setattr(vc.subprocess, "Popen", lambda *a, **k: _PopenFalso(salida, 1))

    with pytest.raises(DescargaError) as exc:
        vc._run(["yt-dlp", "x"], label="VIDEO")

    assert str(exc.value).splitlines()[0] == (
        "[VIDEO] ERROR: unable to download video data: HTTP Error 403: Forbidden"
    )
    assert exc.value.reintentable is True


@pytest.mark.parametrize("error", [
    "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
    "ERROR: [youtube] xxxxxxxxxx0: This video is unavailable",  # salida real de yt-dlp 2026.08
])
def test_run_video_no_disponible_no_es_reintentable(monkeypatch, error):
    salida = [error]
    monkeypatch.setattr(vc.subprocess, "Popen", lambda *a, **k: _PopenFalso(salida, 1))

    with pytest.raises(DescargaError) as exc:
        vc._run(["yt-dlp", "x"], label="VIDEO")
    assert exc.value.reintentable is False


def test_run_on_linea_consume_lineas_de_progreso(monkeypatch, capsys):
    salida = ["[PROG] 1|2|NA|NA|NA|NA|NA", "[download] 100%"]
    monkeypatch.setattr(vc.subprocess, "Popen", lambda *a, **k: _PopenFalso(salida, 0))
    vistas = []

    r = vc._run(["yt-dlp"], label="VIDEO", on_linea=lambda l: vistas.append(l) or l.startswith("[PROG]"))

    assert vistas == salida
    assert "[PROG]" not in capsys.readouterr().out
    assert r.stdout == "[download] 100%"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  download_video: orden y fallo rÃ¡pido
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class _SubpasosEspia:
    def __init__(self):
        self.eventos: list[tuple] = []

    @contextmanager
    def paso(self, sid):
        self.eventos.append(("inicio", sid))
        try:
            yield
        except BaseException:
            self.eventos.append(("error", sid))
            raise
        self.eventos.append(("ok", sid))

    def detalle(self, sid, texto):
        pass

    def progreso(self, sid, **campos):
        self.eventos.append(("progreso", sid, campos.get("pct")))


META = {"title": "Zapatillas top", "uploader": "Canal X", "duration": 120, "thumbnail": "https://i/t.jpg"}


def _fake_run_meta(stdout="", stderr="", codigo=0):
    def run(cmd, **kwargs):
        if "--dump-json" in cmd:
            return subprocess.CompletedProcess(cmd, codigo, stdout, stderr)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, 0, "120.5\n", "")
        raise AssertionError(f"subprocess.run inesperado: {cmd}")
    return run


def test_download_video_orden_y_metadata(monkeypatch, tmp_path):
    llamadas = []

    def fake_run(cmd, label, on_linea=None):
        llamadas.append(label)
        if label == "VIDEO":
            for l in ["[info] abc: Downloading 1 format(s): 270+234",
                      "[download] Destination: a.f270.mp4", "[PROG] 50|100|NA|10|5|NA|NA"]:
                on_linea(l)
            (tmp_path / "stream_completo.mp4").write_bytes(b"v" * 10)
        if label == "AUDIO":
            on_linea("out_time_us=60000000")
            (tmp_path / "audio" / "audio_completo.mp3").write_bytes(b"a")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(vc, "_run", fake_run)
    monkeypatch.setattr(vc.subprocess, "run", _fake_run_meta(stdout=json.dumps(META)))
    sub, videos = _SubpasosEspia(), []

    info = vc.download_video("https://y/abc", tmp_path, subpasos=sub, on_metadata=videos.append)

    assert llamadas == ["VIDEO", "AUDIO"]
    assert [e[1] for e in sub.eventos if e[0] == "inicio"] == ["metadata", "video", "audio", "duracion"]
    assert all(e[0] != "error" for e in sub.eventos)
    assert ("progreso", "video", 50.0) in sub.eventos
    assert ("progreso", "audio", 50.0) in sub.eventos  # 60 s de 120 s
    assert videos == [{"titulo": "Zapatillas top", "canal": "Canal X", "duracion_s": 120,
                       "miniatura": "https://i/t.jpg"}]
    assert info["titulo"] == "Zapatillas top"
    assert info["duracion_segundos"] == 120.5
    assert json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))["title"] == "Zapatillas top"


def test_download_video_privado_falla_sin_descargar(monkeypatch, tmp_path):
    monkeypatch.setattr(vc, "_run", lambda *a, **k: pytest.fail("no deberÃ­a intentar descargar"))
    monkeypatch.setattr(vc.subprocess, "run", _fake_run_meta(
        stderr="ERROR: [youtube] abc: Private video. Sign in if you've been granted access", codigo=1,
    ))
    sub = _SubpasosEspia()

    with pytest.raises(DescargaError) as exc:
        vc.download_video("https://y/abc", tmp_path, subpasos=sub)

    assert exc.value.reintentable is False
    assert str(exc.value).startswith("[METADATA] ERROR: [youtube] abc: Private video")
    assert sub.eventos == [("inicio", "metadata"), ("error", "metadata")]


def test_download_video_sin_subpasos_funciona(monkeypatch, tmp_path):
    def fake_run(cmd, label, on_linea=None):
        if label == "VIDEO":
            (tmp_path / "stream_completo.mp4").write_bytes(b"v")
        else:
            (tmp_path / "audio" / "audio_completo.mp3").write_bytes(b"a")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(vc, "_run", fake_run)
    monkeypatch.setattr(vc.subprocess, "run", _fake_run_meta(stdout=json.dumps(META)))

    assert vc.download_video("https://y/abc", tmp_path)["titulo"] == "Zapatillas top"
