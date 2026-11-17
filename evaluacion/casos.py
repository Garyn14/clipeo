"""
casos.py — Formato del conjunto de evaluación (evaluacion/casos/<nicho>.yaml).

Cada caso es autocontenido (no depende de stream_data/): trae el fragmento de transcripción,
el rango del candidato y lo esperado.

    - id: zp-corr-001
      nicho: zapatillas_peru
      origen: correccion            # correccion | muestra | sintetico
      fuente: "correcciones.jsonl · 20261003_232147 · clip_c001_01"
      clave_correccion: "20261003_232147/clip_c001_01"   # solo origen=correccion
      video: {titulo: "...", canal: "..."}
      candidato: {inicio: "12:04", fin: "12:50"}
      transcripcion: |
        [12:01] ...
      esperado: {publicar: true, tipo: jefe_y_trabajadores}   # tipo opcional
      evidencia: "aprobado por el editor"
"""

from __future__ import annotations

from pathlib import Path

import yaml

ORIGENES = {"correccion", "muestra", "sintetico"}
DIR_CASOS = Path(__file__).resolve().parent / "casos"


class CasoInvalido(ValueError):
    pass


def validar(caso: dict) -> dict:
    """Devuelve el caso si es válido; lanza CasoInvalido con el motivo si no."""
    ident = caso.get("id") or "(sin id)"
    for campo in ("id", "nicho", "origen", "candidato", "transcripcion", "esperado"):
        if not caso.get(campo) and caso.get(campo) is not False:
            raise CasoInvalido(f"{ident}: falta '{campo}'")
    if caso["origen"] not in ORIGENES:
        raise CasoInvalido(f"{ident}: origen '{caso['origen']}' no es uno de {sorted(ORIGENES)}")
    cand = caso["candidato"]
    if not (isinstance(cand, dict) and cand.get("inicio") and cand.get("fin")):
        raise CasoInvalido(f"{ident}: candidato necesita inicio y fin")
    if not isinstance(caso["esperado"].get("publicar"), bool):
        raise CasoInvalido(f"{ident}: esperado.publicar debe ser true o false")
    if caso["origen"] == "correccion" and not caso.get("clave_correccion"):
        raise CasoInvalido(f"{ident}: un caso de corrección necesita 'clave_correccion'")
    return caso


def cargar(ruta: Path) -> list[dict]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or []
    if not isinstance(datos, list):
        raise CasoInvalido(f"{ruta}: se esperaba una lista de casos")
    casos = [validar(c) for c in datos]
    ids = [c["id"] for c in casos]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if repetidos:
        raise CasoInvalido(f"{ruta}: ids repetidos {sorted(repetidos)}")
    return casos


UMBRAL_AUDIENCIA = 1.0   # outlier >= 1: rindió sobre lo normal de la cuenta → "debía publicarse"


def aplicar_audiencia(casos: list[dict], ruta: Path) -> list[dict]:
    """
    Etiqueta por audiencia (CLIP-30): en los casos de corrección cuyo clip ya se publicó, lo esperado pasa a ser
    lo que hizo la audiencia y no la decisión del editor. `<nicho>.audiencia.yaml` es una lista de
    {clave_correccion, video_id, outlier, titulo}; vive aparte para que un re-export no la pise.
    """
    if not ruta.exists():
        return casos
    por_clave = {e["clave_correccion"]: e for e in yaml.safe_load(ruta.read_text(encoding="utf-8")) or []}
    for caso in casos:
        e = por_clave.get(caso.get("clave_correccion"))
        if not e:
            continue
        publicar = float(e["outlier"]) >= UMBRAL_AUDIENCIA
        caso["esperado_editor"] = dict(caso["esperado"])
        caso["esperado"] = {"publicar": publicar, **({"tipo": caso["esperado"]["tipo"]}
                                                     if publicar and caso["esperado"].get("tipo") else {})}
        caso["evidencia"] = f"audiencia: {e['outlier']}x en @nandoclips93 (video {e['video_id']})"
    return casos


def cargar_nicho(nicho: str, incluir_sinteticos: bool = False) -> list[dict]:
    """Casos reales del nicho (<nicho>.yaml, con las etiquetas de <nicho>.audiencia.yaml) y, si se pide, los
    sintéticos (<nicho>.sinteticos.yaml)."""
    casos: list[dict] = []
    reales = DIR_CASOS / f"{nicho}.yaml"
    if reales.exists():
        casos += aplicar_audiencia(cargar(reales), DIR_CASOS / f"{nicho}.audiencia.yaml")
    sinteticos = DIR_CASOS / f"{nicho}.sinteticos.yaml"
    if incluir_sinteticos and sinteticos.exists():
        casos += cargar(sinteticos)
    return casos


def guardar(casos: list[dict], ruta: Path) -> None:
    for c in casos:
        validar(c)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        yaml.safe_dump(casos, allow_unicode=True, sort_keys=False, width=110),
        encoding="utf-8",
    )
