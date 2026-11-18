"""test_levantar.py — CLIP-55: utilidades del comando que levanta Clipeo (sin arrancar servidores)."""

from herramientas import levantar


def test_get_sin_servidor_devuelve_cero():
    assert levantar._get("http://127.0.0.1:9", timeout=0.5)[0] == 0


def test_resumen_publicacion_sin_api(monkeypatch):
    monkeypatch.setattr(levantar, "_get", lambda url, **k: (0, ""))
    assert levantar.resumen_publicacion() == ["  publicación: no responde"]


def test_resumen_publicacion_con_cuentas(monkeypatch):
    cuerpo = '{"nichos": [{"plataforma": "tiktok", "nicho": "n", "cuenta": {"estado": "conectada"}, "proximo_horario": "16:00"}]}'
    monkeypatch.setattr(levantar, "_get", lambda url, **k: (200, cuerpo))
    assert levantar.resumen_publicacion() == ["  tiktok   n: cuenta conectada · próximo horario 16:00"]
