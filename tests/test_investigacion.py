"""test_investigacion.py — Índice outlier y selección de la muestra (investigacion/)."""

from investigacion.comun import calcular_outliers
from investigacion.muestrear import elegir


def _v(cuenta, vistas, edad=10, tipo="clipper", universo="fritz", id_=None):
    return {"id": id_ or f"{cuenta}-{vistas}-{edad}", "cuenta": cuenta, "vistas": vistas,
            "edad_dias": edad, "tipo_cuenta": tipo, "universo": universo}


def test_outlier_relativo_a_la_mediana_de_su_cuenta():
    filas = [_v("a", 100), _v("a", 200), _v("a", 300), _v("b", 10_000), _v("b", 30_000)]
    por_id = {f["id"]: f for f in calcular_outliers(filas)}
    assert por_id["a-300-10"]["outlier"] == 1.5         # mediana de "a" = 200
    assert por_id["b-30000-10"]["outlier"] == 1.5       # mediana de "b" = 20.000


def test_excluye_privados_y_recientes():
    filas = [_v("a", 0), _v("a", 0), _v("a", 100), _v("a", 300), _v("a", 999_999, edad=1)]
    maduros = calcular_outliers(filas)
    assert sorted(f["vistas"] for f in maduros) == [100, 300]
    # los privados (0 vistas) no bajan la mediana: (100+300)/2 = 200
    assert {f["vistas"]: f["outlier"] for f in maduros} == {100: 0.5, 300: 1.5}


def test_no_modifica_las_filas_originales():
    filas = [_v("a", 100), _v("a", 300)]
    calcular_outliers(filas)
    assert "outlier" not in filas[0]


def test_elegir_top_y_fondo_por_universo_y_exitos_propios():
    filas = [_v("c", v, universo="yolu") for v in (10, 20, 30, 40, 1000)]
    filas += [_v("p", v, tipo="propia", universo="mixto") for v in (5, 500, 50)]
    muestra = elegir(calcular_outliers(filas), top=1, fondo=1, propia=2)
    grupos = [(f["grupo"], f["vistas"]) for f in muestra]
    assert ("top", 1000) in grupos and ("fondo", 10) in grupos
    assert [v for g, v in grupos if g == "propia_top"] == [500, 50]
