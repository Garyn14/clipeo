"""test_juez_objetivo.py — CLIP-68: objetivo del cliente y nota comercial del juez (sin IA)."""

from agentes import juez
from investigacion import comun


def test_decidir_viral_o_comercial():
    cfg = {"umbral_fuerza": 5, "umbral_comercial": 6}
    assert juez.decidir(3, 7, False, cfg) == (True, False)       # precio claro: entra por venta
    assert juez.decidir(3, 9, False, cfg) == (True, True)        # comercial alto: prioridad
    assert juez.decidir(7, 2, True, cfg) == (True, True)         # viral alto: como antes
    assert juez.decidir(3, 4, False, cfg) == (False, False)      # ni lo uno ni lo otro
    assert juez.decidir(4, None, True, {}) == (True, False)      # sin umbral ni objetivo: decide el juez (como hoy)
    assert juez.decidir(4, None, False, {}) == (False, False)


def test_prompt_con_y_sin_objetivo(monkeypatch):
    monkeypatch.setattr(comun, "cargar_memoria", lambda c: "MEMORIA")
    monkeypatch.setattr(comun, "cargar_correcciones", lambda c: "")
    sin = juez.system_prompt("n")
    con = juez.system_prompt("n", {"viralidad": True, "venta": "vende zapatillas baratas"})
    assert "comercial" not in sin.split("MEMORIA")[1].split("Responde SOLO")[0].lower() or "OBJETIVO DEL CLIENTE" not in sin
    assert "OBJETIVO DEL CLIENTE" in con and "vende zapatillas baratas" in con and con.startswith(sin)


def test_bloque_y_nota_clip():
    d = {"tipo": "ninguno", "fuerza": 3, "comercial": 7, "por_que": "x", "linea1": "a", "linea2": "b"}
    assert juez.bloque_juez(d)["comercial"] == 7
    assert juez.nota_clip(d) == 7 and juez.nota_clip({"fuerza": 5}) == 5


def test_context_loader_pasa_el_objetivo():
    from pathlib import Path
    from contexto.context_loader import ContextLoader
    cfg = ContextLoader(str(Path(__file__).resolve().parents[1] / "contexto")).load_nicho("zapatillas_peru")
    assert cfg["objetivo"]["viralidad"] is True and "Fritz Sport" in cfg["objetivo"]["venta"]
    assert cfg["juez"]["umbral_comercial"] == 6
