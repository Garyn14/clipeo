"""
fuentes_config.py — CLIP-66/67: editar las fuentes de un cliente (lo que usa el panel).

`fuentes.yaml` sigue siendo la fuente de verdad: se lee y se reescribe conservando el encabezado de comentarios
(los comentarios en línea se pierden al guardar). El historial de un canal quitado se conserva.
"""

from __future__ import annotations

from datetime import datetime, timezone

import yaml

from core import exclusion
from investigacion import comun
from investigacion import fuentes_estaticas as fe
from investigacion import tipos_fuente as tf

ROLES = ("propio", "medios")


def _ruta(nicho: str):
    return comun.carpeta_nicho(nicho) / "fuentes.yaml"


def guardar_config(nicho: str, config: dict) -> None:
    ruta = _ruta(nicho)
    encabezado = ""
    if ruta.exists():
        lineas = ruta.read_text(encoding="utf-8").splitlines(True)
        encabezado = "".join(l for l in lineas[:next((i for i, l in enumerate(lineas) if not l.startswith("#")),
                                                     len(lineas))])
    cuerpo = yaml.safe_dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False)
    ruta.write_text(encabezado + cuerpo, encoding="utf-8")


def _canal(config: dict, url: str) -> dict:
    for c in config.get("canales") or []:
        if c.get("url") == url:
            return c
    raise tf.FuenteError("ese canal no está en las fuentes del cliente")


def _validar_rol(rol: str) -> str:
    if not rol:
        raise tf.FuenteError("elige el rol: Propio (canal del cliente) o TV / prensa (terceros)")
    if rol not in ROLES:
        raise tf.FuenteError(f"rol inválido: {rol} (propio o medios)")
    return rol


def previsualizar(plataforma: str, entrada: str, n: int = 5) -> dict:
    """Resuelve el canal y muestra sus últimos videos, sin guardar nada."""
    tipo = tf.obtener(plataforma)
    if not tipo.implementado or not tipo.automatico:
        raise tf.FuenteError(f"{tipo.nombre}: no se agrega como canal")
    canal = tipo.resolver(entrada)
    videos = sorted(tipo.listar({**canal, "plataforma": tipo.clave}),
                    key=lambda v: v.get("publicado") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:n]
    return {**canal, "plataforma": tipo.clave,
            "videos": [{"id": v["id"], "titulo": v["titulo"], "url": v.get("url"),
                        "publicado": v["publicado"].isoformat() if v.get("publicado") else None} for v in videos]}


def _rol_del_tipo(tipo: tf.TipoFuente, rol: str) -> None:
    if rol not in tipo.roles:
        admitidos = " o ".join("Propio" if r == "propio" else "TV / prensa" for r in tipo.roles)
        raise tf.FuenteError(f"{tipo.nombre} solo admite el rol {admitidos}")


def agregar_canal(nicho: str, plataforma: str, entrada: str, rol: str, nombre: str | None = None) -> dict:
    _validar_rol(rol)
    tipo = tf.obtener(plataforma)
    _rol_del_tipo(tipo, rol)
    if not tipo.implementado or not tipo.automatico:
        raise tf.FuenteError(f"{tipo.nombre}: no se agrega como canal")
    canal = tipo.resolver(entrada)
    config = fe.cargar_config(nicho)
    canales = config.setdefault("canales", [])
    if any(c.get("url") == canal["url"] for c in canales):
        raise tf.FuenteError(f"«{canal['nombre']}» ya está en las fuentes")
    motivo = exclusion.motivo(canal=canal["nombre"])
    if motivo:
        raise tf.FuenteError(motivo)
    nuevo = {"nombre": (nombre or canal["nombre"]).strip(), "plataforma": tipo.clave, "url": canal["url"],
             "rol": rol, "activo": True}
    canales.append(nuevo)
    guardar_config(nicho, config)
    return nuevo


def editar_canal(nicho: str, url: str, activo: bool | None = None, rol: str | None = None,
                 nombre: str | None = None) -> dict:
    config = fe.cargar_config(nicho)
    canal = _canal(config, url)
    if activo is not None:
        canal["activo"] = bool(activo)
    if rol is not None:
        canal["rol"] = _validar_rol(rol)
        _rol_del_tipo(tf.obtener(canal.get("plataforma")), canal["rol"])
    if nombre is not None and nombre.strip():
        canal["nombre"] = nombre.strip()
    guardar_config(nicho, config)
    return canal


def quitar_canal(nicho: str, url: str) -> None:
    config = fe.cargar_config(nicho)
    _canal(config, url)
    config["canales"] = [c for c in config.get("canales") or [] if c.get("url") != url]
    guardar_config(nicho, config)


def guardar_palabras(nicho: str, palabras: list[str]) -> list[str]:
    limpias = []
    for p in palabras:
        p = (p or "").strip()
        if p and p.lower() not in {x.lower() for x in limpias}:
            limpias.append(p)
    config = fe.cargar_config(nicho)
    config["palabras_clave"] = limpias
    guardar_config(nicho, config)
    return limpias


def agregar_links(nicho: str, links: list[str], rol: str, tipo_clave: str = "manual") -> list[dict]:
    """CLIP-67: links sueltos → candidatos del cliente (con el mismo dedup, historial y exclusión)."""
    _validar_rol(rol)
    tipo = tf.obtener(tipo_clave)
    historial = fe.leer_historial(nicho)
    vistos = set(fe.estado_actual(historial)) | fe.ids_ya_procesados(fe._stream_data())
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resultados = []
    for link in [l.strip() for l in links if l and l.strip()]:
        try:
            v = tipo.info_video(link)
        except tf.FuenteError as e:
            resultados.append({"link": link, "ok": False, "motivo": str(e)})
            continue
        if v["id"] in vistos:
            resultados.append({"link": link, "ok": False, "motivo": "ya estaba registrado o procesado"})
            continue
        motivo = exclusion.motivo(canal=v.get("canal"))
        if motivo:
            resultados.append({"link": link, "ok": False, "motivo": motivo})
            continue
        vistos.add(v["id"])
        historial.append({"id": v["id"], "url": v["url"], "titulo": v["titulo"],
                          "canal": v.get("canal") or tipo.nombre, "rol": rol, "fuente": tipo.clave,
                          "publicado": v["publicado"].isoformat() if v.get("publicado") else None,
                          "detectado": ahora, "estado": "nuevo", "motivo": "agregado a mano"})
        resultados.append({"link": link, "ok": True, "id": v["id"], "titulo": v["titulo"]})
    fe._guardar_historial(nicho, historial)
    return resultados


def aportes(nicho: str) -> dict[str, dict]:
    """Por canal: cuántos videos aportó en cada estado (para el panel)."""
    conteo: dict[str, dict] = {}
    for f in fe.estado_actual(fe.leer_historial(nicho)).values():
        c = conteo.setdefault(f.get("canal") or "", {"nuevo": 0, "procesado": 0, "descartado": 0, "error": 0})
        if f.get("estado") in c:
            c[f["estado"]] += 1
    return conteo
