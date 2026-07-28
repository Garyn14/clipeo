"""
test_video_transcriber.py — Tests unitarios para _transcribe_via_colab()
(core/video_transcriber.py).

Todas las llamadas HTTP están mockeadas con requests_mock — nunca se golpea
una URL real.
"""

import pytest
import requests

from transcripcion.video_transcriber import _transcribe_via_colab

TRANSCRIBE_URL = "https://fake-colab.trycloudflare.com/transcribe"


def status_url(job_id: str) -> str:
    return f"https://fake-colab.trycloudflare.com/status/{job_id}"


@pytest.fixture(autouse=True)
def colab_env(monkeypatch):
    monkeypatch.setenv("COLAB_TRANSCRIBE_URL", TRANSCRIBE_URL)
    monkeypatch.delenv("COLAB_AUTH_TOKEN", raising=False)


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
