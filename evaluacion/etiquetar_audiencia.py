"""
etiquetar_audiencia.py — CLIP-33: los clips publicados alimentan la evaluación.

Cruza los clips aprobados en la revisión (casos de corrección) con los videos publicados de la cuenta propia y
etiqueta cada caso con su resultado real (outlier) en `evaluacion/casos/<nicho>.audiencia.yaml`.

La metadata de TikTok no trae el texto del video, así que el cruce es por **duración + fecha**:
  - duración del clip (rango del candidato) = duración del video, con tolerancia de 1 s;
  - el video se publicó entre 2 días antes y 10 días después de la revisión (`correcciones.jsonl`);
  - el video tiene al menos --dias-min días al medirlo (vistas maduras). El outlier se recalcula contra la mediana
    de la última medición de la cuenta (`investigacion/comun.calcular_outliers`).
**Primero, el link:** si el operador pegó el link del video al publicar (revisión web → `publicados.jsonl`), el
cruce es exacto. Para el resto:

Desempate por **título**: si se conoce el texto de la portada del video (`cuenta_propia.jsonl`, campo
`titulo_pantalla`), se compara con el título del clip (el del juez o el final del editor, que es el que se quema en
el video). Título casi idéntico (≥ 0,85) → automático aunque haya otros candidatos por duración; ninguno parecido
(< 0,5) → no se publicó. Sin títulos: un único candidato por duración → automático; si no → dudoso (se lista).

    python -m evaluacion.etiquetar_audiencia zapatillas_peru              # solo reporte
    python -m evaluacion.etiquetar_audiencia zapatillas_peru --escribir   # actualiza <nicho>.audiencia.yaml

Antes, medir la cuenta: `cd legacy && python investigacion/recolectar.py zapatillas_peru --cuenta <cuenta>`.
Las entradas manuales del archivo se conservan; si el cruce las contradice, se avisa (no se borran solas).
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from evaluacion import _legacy, casos as casos_mod

import difflib

TITULO_SI, TITULO_NO = 0.85, 0.5
TOLERANCIA_S = 1
CASI_S = 3
ANTES_DIAS, DESPUES_DIAS = 2, 10


def _fecha(valor) -> date | None:
    s = str(valor or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s[:10] if "-" in s else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def _segundos(ts: str) -> int:
    partes = [int(p) for p in str(ts).split(":")]
    total = 0
    for p in partes:
        total = total * 60 + p
    return total


def videos_propios(ruta_videos: Path, dias_min: int) -> list[dict]:
    """Última medición de cada video de la cuenta propia, maduro (>= dias_min días), con su outlier recalculado."""
    from investigacion.comun import calcular_outliers

    ultimos: dict[str, dict] = {}
    for linea in ruta_videos.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        v = json.loads(linea)
        if v.get("tipo_cuenta") != "propia":
            continue
        if v["id"] not in ultimos or str(v.get("medido")) > str(ultimos[v["id"]].get("medido")):
            ultimos[v["id"]] = v
    filas = []
    for v in ultimos.values():
        try:   # las mediciones antiguas guardaban números como texto
            v = {**v, "vistas": int(float(v.get("vistas") or 0)), "edad_dias": float(v.get("edad_dias") or 0)}
        except ValueError:
            continue
        if v["edad_dias"] >= dias_min and v.get("duracion_s") not in (None, "") and _fecha(v.get("publicado")):
            filas.append(v)
    return [{**v, "_pub": _fecha(v["publicado"]), "_dur": int(float(v["duracion_s"]))}
            for v in calcular_outliers(filas)]


def leer_correcciones(ruta_correcciones: Path) -> tuple[dict[str, date], dict[str, str]]:
    """Fecha de la última revisión y título quemado (final del editor o el del juez) de cada clip (sesion/clip)."""
    fechas: dict[str, date] = {}
    titulos: dict[str, str] = {}
    if ruta_correcciones.exists():
        for linea in ruta_correcciones.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                r = json.loads(linea)
                clave = f"{r['session_id']}/{r['clip_id']}"
                fechas[clave] = _fecha(r.get("fecha"))
                j = r.get("juez") or {}
                titulos[clave] = r.get("titulo_final") or f"{j.get('linea1', '')} {j.get('linea2', '')}".strip()
    return fechas, titulos


def titulos_de_portada(ruta: Path) -> dict[str, str]:
    """Texto de portada de cada video propio (cuenta_propia.jsonl, leído de la portada), si existe."""
    if not ruta.exists():
        return {}
    filas = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {str(f["id"]): f.get("titulo_pantalla", "") for f in filas}


def clips_aprobados(casos: list[dict], revision: dict[str, date] | None = None,
                    titulos: dict[str, str] | None = None) -> list[dict]:
    """Casos de corrección que el editor aprobó, con su duración, fecha de revisión (o de la sesión) y título."""
    revision, titulos = revision or {}, titulos or {}
    salida = []
    for c in casos:
        if c.get("origen") != "correccion" or not c["esperado"].get("publicar"):
            continue
        clave = c["clave_correccion"]
        salida.append({
            "id": c["id"], "clave": clave,
            "dur": _segundos(c["candidato"]["fin"]) - _segundos(c["candidato"]["inicio"]),
            "revision": revision.get(clave) or _fecha(clave.split("/")[0]),
            "titulo": titulos.get(clave, ""),
        })
    return salida


def _norm(texto: str) -> str:
    return " ".join(w for w in (texto or "").lower().replace("tío", "tio").split() if len(w) > 3)


def parecido(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() if a and b else 0.0


def leer_publicados(ruta: Path) -> dict[str, str]:
    """Clave sesion/clip → video_id de TikTok, desde los links pegados en la revisión (el último gana)."""
    enlaces: dict[str, str] = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                r = json.loads(linea)
                if r.get("plataforma", "tiktok") == "tiktok":
                    enlaces[f"{r['session_id']}/{r['clip_id']}"] = str(r["video_id"])
    return enlaces


def cruzar(clips: list[dict], videos: list[dict], enlaces: dict[str, str] | None = None) -> dict[str, list]:
    """{'automaticos': [(clip, video)], 'dudosos': [(clip, [videos])], 'sin_publicar': [clip]}."""
    res = {"automaticos": [], "dudosos": [], "sin_publicar": [], "por_link": [], "link_sin_medir": []}
    confirmados_por_titulo = set()
    enlaces = enlaces or {}
    por_id = {str(v["id"]): v for v in videos}
    usados = set()
    for c in clips:
        vid = enlaces.get(c["clave"])
        if vid:
            if vid in por_id:
                res["por_link"].append((c, por_id[vid]))
                usados.add(vid)
            else:
                res["link_sin_medir"].append(c)   # video aún sin medir o sin vistas maduras
    clips = [c for c in clips if c["clave"] not in enlaces]
    videos = [v for v in videos if str(v["id"]) not in usados]
    for c in clips:
        r = c["revision"]
        en_fecha = [v for v in videos
                    if r is None or r - timedelta(days=ANTES_DIAS) <= v["_pub"] <= r + timedelta(days=DESPUES_DIAS)]
        exactos = [v for v in en_fecha if abs(v["_dur"] - c["dur"]) <= TOLERANCIA_S]
        casi = [v for v in en_fecha if TOLERANCIA_S < abs(v["_dur"] - c["dur"]) <= CASI_S]
        candidatos = exactos + casi
        con_titulo = [(parecido(c.get("titulo", ""), v.get("titulo_pantalla", "")), v)
                      for v in candidatos if c.get("titulo") and v.get("titulo_pantalla")]
        if con_titulo and len(con_titulo) == len(candidatos):
            mejores = [v for p, v in con_titulo if p >= TITULO_SI]
            if len(mejores) == 1:
                res["automaticos"].append((c, mejores[0]))
                confirmados_por_titulo.add(c["clave"])
            elif all(p < TITULO_NO for p, _ in con_titulo):
                res["sin_publicar"].append(c)
            else:
                res["dudosos"].append((c, candidatos))
        elif len(exactos) == 1 and not casi:
            res["automaticos"].append((c, exactos[0]))
        elif exactos or casi:
            res["dudosos"].append((c, exactos + casi))
        else:
            res["sin_publicar"].append(c)
    # un video que es candidato de más de un clip (automático o dudoso) nunca se asigna solo
    por_video: dict[str, int] = {}
    for c, v in res["automaticos"]:
        if c["clave"] not in confirmados_por_titulo:
            por_video[v["id"]] = por_video.get(v["id"], 0) + 1
    for c, vs in res["dudosos"]:
        for v in vs:
            por_video[v["id"]] = por_video.get(v["id"], 0) + 1
    repetidos = {vid for vid, n in por_video.items() if n > 1}
    ambiguos = [(c, v) for c, v in res["automaticos"] if v["id"] in repetidos and c["clave"] not in confirmados_por_titulo]
    res["dudosos"] += [(c, [v]) for c, v in ambiguos]
    res["automaticos"] = [(c, v) for c, v in res["automaticos"] if (c, v) not in ambiguos]
    return res


def entrada(c: dict, v: dict, fuente: str = "automatica") -> dict:
    return {"clave_correccion": c["clave"], "video_id": str(v["id"]), "outlier": round(float(v["outlier"]), 2),
            "titulo": v.get("titulo_pantalla") or "", "fuente": fuente,
            "duracion_s": v["_dur"], "publicado": v["_pub"].isoformat()}


def actualizar(existentes: list[dict], res: dict) -> tuple[list[dict], list[str]]:
    """Fusiona: manuales se conservan; automáticas se reemplazan; avisa cuando el cruce contradice una manual."""
    auto = {c["clave"]: (c, v) for c, v in res["automaticos"]}
    links = {c["clave"]: (c, v) for c, v in res.get("por_link", [])}
    auto.update(links)
    sin_pub = {c["clave"] for c in res["sin_publicar"]}
    avisos, salida = [], []
    for e in existentes:
        clave = e["clave_correccion"]
        if e.get("fuente", "manual") != "manual":
            continue  # las automáticas y por link se recalculan
        if clave in auto and str(auto[clave][1]["id"]) != str(e["video_id"]):
            avisos.append(f"{clave}: etiqueta manual → video {e['video_id']}, el cruce dice {auto[clave][1]['id']}")
        elif clave in sin_pub:
            avisos.append(f"{clave}: etiqueta manual → video {e['video_id']}, pero el cruce no encuentra un video con "
                          "su duración en esas fechas (revisar)")
        salida.append(e)
        auto.pop(clave, None)
    salida += [entrada(c, v, "link" if c["clave"] in links else "automatica") for c, v in auto.values()]
    return salida, avisos


def main() -> None:
    ap = argparse.ArgumentParser(description="Etiqueta por audiencia: cruza clips aprobados con videos publicados")
    ap.add_argument("nicho")
    ap.add_argument("--videos", type=Path, default=None, help="videos.jsonl (default: el del nicho en legacy/)")
    ap.add_argument("--dias-min", type=int, default=7, help="días mínimos publicado para tomar las vistas (7)")
    ap.add_argument("--escribir", action="store_true", help="actualizar <nicho>.audiencia.yaml")
    args = ap.parse_args()

    ruta_videos = args.videos or _legacy.LEGACY / "investigacion" / args.nicho / "videos.jsonl"
    casos = casos_mod.cargar(casos_mod.DIR_CASOS / f"{args.nicho}.yaml")   # etiquetas del editor, sin audiencia
    carpeta = _legacy.LEGACY / "investigacion" / args.nicho
    revision, titulos = leer_correcciones(carpeta / "correcciones.jsonl")
    portadas = titulos_de_portada(carpeta / "cuenta_propia.jsonl")
    videos = [{**v, "titulo_pantalla": portadas.get(str(v["id"]), "")}
              for v in videos_propios(ruta_videos, args.dias_min)]
    res = cruzar(clips_aprobados(casos, revision, titulos), videos, leer_publicados(carpeta / "publicados.jsonl"))

    for c, v in res["por_link"]:
        print(f"  🔗 {c['id']} {c['clave']} → video {v['id']} (link pegado) outlier {float(v['outlier']):.2f}")
    for c in res["link_sin_medir"]:
        print(f"  … {c['id']} {c['clave']}: tiene link pero el video aún no está medido o no tiene vistas maduras")
    print(f"[AUDIENCIA] {len(res['por_link'])} por link · {len(res['automaticos'])} automático(s) · {len(res['dudosos'])} dudoso(s) · "
          f"{len(res['sin_publicar'])} sin publicar (o sin vistas maduras)")
    for c, v in res["automaticos"]:
        print(f"  ✓ {c['id']} {c['clave']} ({c['dur']}s) → video {v['id']} ({v['_dur']}s, {v['_pub']}) "
              f"outlier {float(v['outlier']):.2f}")
    for c, vs in res["dudosos"]:
        opciones = ", ".join(f"{v['id']} ({v['_dur']}s, {v['_pub']})" for v in vs)
        print(f"  ? {c['id']} {c['clave']} ({c['dur']}s) → confirmar a mano entre: {opciones}")
    for c in res["sin_publicar"]:
        print(f"  · {c['id']} {c['clave']} ({c['dur']}s) sin video publicado que coincida (duración, fecha y título)")

    ruta = casos_mod.DIR_CASOS / f"{args.nicho}.audiencia.yaml"
    existentes = yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else []
    nuevas, avisos = actualizar(existentes or [], res)
    for a in avisos:
        print(f"  ⚠ {a}")
    if args.escribir:
        cabecera = ("# Etiquetas por audiencia: resultado real (outlier) de los clips aprobados que se publicaron.\n"
                    "# fuente: manual (confirmada por una persona) | automatica (evaluacion.etiquetar_audiencia).\n")
        ruta.write_text(cabecera + yaml.safe_dump(nuevas, allow_unicode=True, sort_keys=False, width=200),
                        encoding="utf-8")
        print(f"[AUDIENCIA] {len(nuevas)} etiqueta(s) → {ruta}")


if __name__ == "__main__":
    main()
