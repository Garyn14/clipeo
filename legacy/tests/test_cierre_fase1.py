"""test_cierre_fase1.py — CLIP-59: criterios de cierre de la Fase 1."""

from datetime import datetime

from investigacion import cierre_fase1 as c


def r(fecha, accion, titulo, sesion="s"):
    return {"fecha": fecha, "accion": accion, "session_id": sesion, "juez": {"linea1": titulo, "linea2": ""}}


def test_tasa_cuenta_cada_momento_una_vez_y_respeta_el_periodo():
    regs = [r("2026-11-01T10:00:00", "descartado", "viejo"),                 # fuera del período
            r("2026-11-18T10:00:00", "descartado", "casero"),
            r("2026-11-18T12:00:00", "aprobado", "casero"),                   # re-aprobado: vale la última
            r("2026-11-18T12:01:00", "aprobado", "zeein"),
            r("2026-11-18T12:02:00", "editado", "guardia")]
    t = c.tasa_aprobacion(regs, datetime(2026, 11, 10))
    assert (t["aprobado"], t["editado"], t["descartado"], t["total"], t["tasa"]) == (2, 1, 0, 3, 0.67)
    assert c.tasa_aprobacion([], datetime(2026, 11, 10))["tasa"] is None


def test_clips_medidos_solo_maduros_y_distintos():
    filas = [{"plataforma": "youtube", "clave": "a", "edad_dias": 5}, {"plataforma": "youtube", "clave": "a", "edad_dias": 9},
             {"plataforma": "tiktok", "clave": "a", "edad_dias": 4}, {"plataforma": "youtube", "clave": "b", "edad_dias": 1}]
    assert c.clips_medidos(filas) == 2
