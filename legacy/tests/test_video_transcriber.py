"""
test_video_transcriber.py — Tests unitarios para _transcribe_via_colab()
(core/video_transcriber.py).

Todas las llamadas HTTP están mockeadas con requests_mock — nunca se golpea
una URL real.
"""

import json

import pytest
import requests

from transcripcion import video_transcriber
from transcripcion.video_transcriber import (
    _normalizar_url_colab,
    _transcribe_via_colab,
    _write_word_timings,
)

TRANSCRIBE_URL = "https://fake-colab.trycloudflare.com/transcribe"


def status_url(job_id: str) -> str:
    return f"https://fake-colab.trycloudflare.com/status/{job_id}"


@pytest.fixture(autouse=True)
def colab_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COLAB_TRANSCRIBE_URL", TRANSCRIBE_URL)
    monkeypatch.delenv("COLAB_AUTH_TOKEN", raising=False)
    # Sin esto, el .env real del proyecto pisaría la URL falsa (se relee en cada llamada).
    monkeypatch.setattr(video_transcriber, "_ENV_PATH", tmp_path / "no_existe.env")
    monkeypatch.setattr(video_transcriber, "_ENV_PATH_RAIZ", tmp_path / "no_existe_raiz.env")


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    path = tmp_path / ".env"
    monkeypatch.setattr(video_transcriber, "_ENV_PATH", path)
    return path


def test_lee_la_url_del_env_de_la_raiz(monkeypatch, tmp_path):
    """CLIP-39: en la laptop del operador el .env vive en la raíz del repo, no en legacy/."""
    raiz = tmp_path / "raiz.env"
    raiz.write_text("COLAB_TRANSCRIBE_URL=https://raiz.trycloudflare.com\nCOLAB_AUTH_TOKEN=abc\n", encoding="utf-8")
    monkeypatch.setattr(video_transcriber, "_ENV_PATH_RAIZ", raiz)
    assert video_transcriber._colab_config() == ("https://raiz.trycloudflare.com/transcribe", "abc")

    legacy = tmp_path / "legacy.env"
    legacy.write_text("COLAB_TRANSCRIBE_URL=https://legacy.trycloudflare.com\n", encoding="utf-8")
    monkeypatch.setattr(video_transcriber, "_ENV_PATH", legacy)
    url, token = video_transcriber._colab_config()
    assert url == "https://legacy.trycloudflare.com/transcribe" and token == "abc"   # legacy gana, token de la raíz


def _mock_job_ok(requests_mock, base: str, job_id: str):
    requests_mock.post(f"{base}/transcribe", status_code=202, json={"job_id": job_id})
    requests_mock.get(
        f"{base}/status/{job_id}",
        status_code=200,
        json={"status": "done", "segments": [], "language": "es", "processing_seconds": 1.0},
    )


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "chunk_001.mp3"
    p.write_bytes(b"fake mp3 bytes")
    return p


def test_post_exitoso_y_done_en_primer_poll(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "abc123"})
    requests_mock.get(
        status_url("abc123"),
        status_code=200,
        json={
            "status": "done",
            "segments": [{"start": 0.0, "text": "hola"}],
            "language": "es",
            "processing_seconds": 1.5,
        },
    )

    result = _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    assert result == {
        "status": "done",
        "segments": [{"start": 0.0, "text": "hola"}],
        "language": "es",
        "processing_seconds": 1.5,
    }


def test_post_status_code_no_202(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=500, text="server error interno")

    with pytest.raises(RuntimeError):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_post_202_sin_job_id(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"otra_clave": "sin_job_id"})

    with pytest.raises(RuntimeError, match="job_id"):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_polling_processing_luego_done(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "job2"})
    requests_mock.get(
        status_url("job2"),
        [
            {"status_code": 200, "json": {"status": "processing"}},
            {
                "status_code": 200,
                "json": {
                    "status": "done",
                    "segments": [{"start": 3.2, "text": "listo"}],
                    "language": "es",
                    "processing_seconds": 4.0,
                },
            },
        ],
    )

    result = _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    assert result["status"] == "done"
    assert result["segments"] == [{"start": 3.2, "text": "listo"}]
    assert requests_mock.call_count == 3  # 1 POST + 2 GET


def test_polling_status_code_no_200(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "job3"})
    requests_mock.get(status_url("job3"), status_code=503, text="temporal")

    with pytest.raises(RuntimeError):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_polling_status_error(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "job4"})
    requests_mock.get(
        status_url("job4"),
        status_code=200,
        json={"status": "error", "error": "el modelo se quedo sin memoria"},
    )

    with pytest.raises(RuntimeError, match="el modelo se quedo sin memoria"):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_polling_status_desconocido(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "job5"})
    requests_mock.get(
        status_url("job5"),
        status_code=200,
        json={"status": "weird_status"},
    )

    with pytest.raises(RuntimeError, match="weird_status"):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_timeout_global_de_polling(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "job6"})
    requests_mock.get(
        status_url("job6"),
        status_code=200,
        json={"status": "processing"},
    )

    with pytest.raises(RuntimeError, match="timeout"):
        _transcribe_via_colab(audio_file, timeout=0.05, poll_interval=0.02)


def test_connection_error_en_post(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, exc=requests.exceptions.ConnectionError)

    with pytest.raises(RuntimeError):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_connection_error_en_polling(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "job7"})
    requests_mock.get(status_url("job7"), exc=requests.exceptions.ConnectionError)

    with pytest.raises(RuntimeError):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)


def test_envia_el_idioma_a_colab(requests_mock, audio_file):
    _mock_job_ok(requests_mock, "https://fake-colab.trycloudflare.com", "jl")

    _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    assert b'name="language"' in requests_mock.request_history[0].body
    assert b"\r\n\r\nes\r\n" in requests_mock.request_history[0].body


def test_idioma_distinto_falla_sin_reintentar(requests_mock, audio_file):
    requests_mock.post(TRANSCRIBE_URL, status_code=202, json={"job_id": "jit"})
    requests_mock.get(status_url("jit"), status_code=200, json={
        "status": "done", "segments": [{"start": 0, "text": "Non c'è l'elettronica?"}], "language": "it",
    })

    with pytest.raises(video_transcriber.ColabError, match="'it' en vez de 'es'") as exc:
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)
    assert exc.value.reintentable is False


@pytest.mark.parametrize("entrada, esperado", [
    ("https://x.trycloudflare.com", "https://x.trycloudflare.com/transcribe"),
    ("https://x.trycloudflare.com/", "https://x.trycloudflare.com/transcribe"),
    ("https://x.trycloudflare.com/transcribe", "https://x.trycloudflare.com/transcribe"),
    ("  https://x.trycloudflare.com/transcribe/ ", "https://x.trycloudflare.com/transcribe"),
    ("", ""),
])
def test_normalizar_url_colab(entrada, esperado):
    assert _normalizar_url_colab(entrada) == esperado


def test_url_sin_sufijo_en_env_file(requests_mock, audio_file, env_file):
    env_file.write_text("COLAB_TRANSCRIBE_URL=https://nuevo.trycloudflare.com\n", encoding="utf-8")
    _mock_job_ok(requests_mock, "https://nuevo.trycloudflare.com", "j1")

    result = _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    assert result["status"] == "done"
    assert requests_mock.request_history[0].url == "https://nuevo.trycloudflare.com/transcribe"


def test_env_file_gana_sobre_os_environ(requests_mock, audio_file, env_file):
    # os.environ conserva la URL del arranque (TRANSCRIBE_URL); el archivo tiene la nueva.
    env_file.write_text(
        "COLAB_TRANSCRIBE_URL=https://nuevo.trycloudflare.com/transcribe\n"
        "COLAB_AUTH_TOKEN=tok-nuevo\n",
        encoding="utf-8",
    )
    _mock_job_ok(requests_mock, "https://nuevo.trycloudflare.com", "j2")

    _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    post = requests_mock.request_history[0]
    assert post.url == "https://nuevo.trycloudflare.com/transcribe"
    assert post.headers["Authorization"] == "Bearer tok-nuevo"


def test_cambio_de_env_entre_intentos(requests_mock, audio_file, env_file):
    env_file.write_text("COLAB_TRANSCRIBE_URL=https://viejo.trycloudflare.com\n", encoding="utf-8")
    requests_mock.post("https://viejo.trycloudflare.com/transcribe", exc=requests.exceptions.ConnectionError)

    with pytest.raises(video_transcriber.ColabError, match="viejo.trycloudflare.com"):
        _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    # El usuario corrige .env mientras el paso espera el reintento.
    env_file.write_text("COLAB_TRANSCRIBE_URL=https://nuevo.trycloudflare.com\n", encoding="utf-8")
    _mock_job_ok(requests_mock, "https://nuevo.trycloudflare.com", "j3")

    result = _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    assert result["status"] == "done"


def test_env_file_sin_la_clave_cae_a_os_environ(requests_mock, audio_file, env_file):
    env_file.write_text("HF_TOKEN=x\n", encoding="utf-8")
    _mock_job_ok(requests_mock, "https://fake-colab.trycloudflare.com", "j4")

    _transcribe_via_colab(audio_file, timeout=5, poll_interval=0.01)

    assert requests_mock.request_history[0].url == TRANSCRIBE_URL


def test_write_word_timings_extrae_palabras_con_offset(tmp_path):
    segments = [
        {"words": [
            {"word": "Hola",  "start": 1.0, "end": 1.3},
            {"word": "mundo", "start": 1.4, "end": 1.8},
        ]},
    ]
    dest = tmp_path / "palabras.json"
    n = _write_word_timings(segments, dest, offset_segundos=10)

    assert n == 2
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data == [
        {"word": "Hola",  "start": 11.0, "end": 11.3},
        {"word": "mundo", "start": 11.4, "end": 11.8},
    ]


def test_write_word_timings_omite_palabras_sin_alinear(tmp_path):
    segments = [
        {"words": [
            {"word": "Hola"},                            # sin start/end
            {"word": "mundo", "start": 1.4, "end": 1.8},
        ]},
    ]
    dest = tmp_path / "palabras.json"
    n = _write_word_timings(segments, dest)

    assert n == 1
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data == [{"word": "mundo", "start": 1.4, "end": 1.8}]


def test_write_word_timings_sin_segmentos_escribe_lista_vacia(tmp_path):
    dest = tmp_path / "palabras.json"
    n = _write_word_timings([], dest)

    assert n == 0
    assert json.loads(dest.read_text(encoding="utf-8")) == []


def test_colab_vivo(requests_mock, monkeypatch, tmp_path):
    """CLIP-56: 401/404 = el túnel responde; sin respuesta o 530 = caído; sin URL = no configurado."""
    base = "https://fake-colab.trycloudflare.com"
    requests_mock.get(f"{base}/status/_comprobar", status_code=404)
    assert video_transcriber.colab_vivo() == (True, "")
    requests_mock.get(f"{base}/status/_comprobar", status_code=530)
    ok, motivo = video_transcriber.colab_vivo()
    assert not ok and "530" in motivo
    monkeypatch.setenv("COLAB_TRANSCRIBE_URL", "")
    assert video_transcriber.colab_vivo() == (False, "sin COLAB_TRANSCRIBE_URL en .env")
