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


def test_dependencias_al_dia_compara_lo_instalado_con_el_lock(tmp_path):
    """CLIP-84: si package-lock.json es más nuevo que lo instalado, levantar corre npm install."""
    import os
    from herramientas.levantar import dependencias_al_dia

    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    assert not dependencias_al_dia(tmp_path)               # sin node_modules
    (tmp_path / "node_modules").mkdir()
    instalado = tmp_path / "node_modules" / ".package-lock.json"
    instalado.write_text("{}", encoding="utf-8")
    os.utime(instalado, (2_000_000_000, 2_000_000_000))
    assert dependencias_al_dia(tmp_path)
    os.utime(tmp_path / "package-lock.json", (2_100_000_000, 2_100_000_000))
    assert not dependencias_al_dia(tmp_path)
