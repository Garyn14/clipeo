"""
test_context_loader.py — Tests unitarios para ContextLoader._assemble()
(core/context_loader.py).
"""

from contexto.context_loader import ContextLoader


def test_assemble_construye_personajes_desde_entidades():
    ctx = ContextLoader()

    nicho_data = {
        "nicho": {
            "id": "test_nicho",
            "descripcion": "nicho de prueba",
            "entidades": ["test"],
            "identificacion": {"umbral_alto": 0.8, "umbral_bajo": 0.4},
        },
        "deteccion_base": {"confianza_minima": 0.75, "prompt": "prompt base"},
        "contenido_base": {"score_minimo_publicar": 7, "hashtags_base": [], "prompt": "prompt contenido"},
        "refinamiento_base": {
            "contexto_antes_segundos": 45,
            "contexto_despues_segundos": 45,
            "duracion_minima_segundos": 20,
            "duracion_maxima_segundos": 90,
            "prompt": "prompt refinamiento",
        },
    }

    entidad_test = {
        "entidad": {
            "id": "test",
            "nombre": "Test Uno",
            "apodos": ["Apodo A", "Apodo B"],
        }
    }

    assembled = ctx._assemble(nicho_data, [entidad_test], [])

    assert assembled["personajes"] == [
        {"id": "test", "nombres": ["Test Uno", "Apodo A", "Apodo B"]}
    ]


def test_assemble_personaje_sin_apodos():
    ctx = ContextLoader()

    nicho_data = {"nicho": {"id": "test_nicho", "entidades": ["test"]}}
    entidad_test = {"entidad": {"id": "test", "nombre": "Test Uno"}}

    assembled = ctx._assemble(nicho_data, [entidad_test], [])

    assert assembled["personajes"] == [{"id": "test", "nombres": ["Test Uno"]}]


def test_umbral_del_juez_del_nicho_real_llega_a_la_config():
    """S5: `juez:` está en el primer nivel del YAML; antes el loader lo buscaba en `nicho:` y llegaba {}."""
    from pathlib import Path
    contexto = Path(__file__).resolve().parents[1] / "contexto"
    config = ContextLoader(contexto_dir=str(contexto)).load_nicho("zapatillas_peru")
    assert config["juez"].get("umbral_fuerza") == 3
