"""test_colab_arrancar.py — CLIP-65: partes puras del arranque de Colab (sin Colab ni red)."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("arrancar", Path(__file__).resolve().parents[1] / "colab" / "arrancar.py")
arrancar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arrancar)


def test_buscar_url():
    linea = "2026-11-19T05:17:02Z INF |  https://stockholm-receipt-electro-slight.trycloudflare.com    |"
    assert arrancar.buscar_url(linea) == "https://stockholm-receipt-electro-slight.trycloudflare.com"
    assert arrancar.buscar_url("Requesting new quick Tunnel on trycloudflare.com...") is None


def test_progreso_avanza_y_no_se_adelanta():
    pct0, resto0 = arrancar.progreso(0, 0)
    assert pct0 == 0 and resto0 == sum(e[2] for e in arrancar.ETAPAS)
    pct_largo, _ = arrancar.progreso(1, 10_000)          # una etapa que se demora no llega al 100%
    pct_sig, _ = arrancar.progreso(2, 0)
    assert pct_largo < pct_sig
    assert arrancar.progreso(4, 0)[0] < 100


def test_texto_barra():
    t = arrancar.texto_barra(1, 30, 95)
    assert "Paso 2 de 5" in t and "Instalando" in t and "1:35 transcurridos" in t and "faltan ~" in t
