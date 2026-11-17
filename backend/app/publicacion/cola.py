"""
cola.py — La cola de publicación y las transiciones de estado de cada publicación.

Estados:
  en_cola ─▶ enviando ─▶ en_bandeja   (fin: TikTok confirmó el borrador / YouTube procesó el video)
                     ├─▶ en_cola   (error reintentable / cuenta pausada o a reconectar)
                     ├─▶ error     (no reintentable, o se agotaron los reintentos)
                     └─▶ sin_confirmar (no se pudo saber si llegó)
  en_cola ─▶ cancelado  (clip descartado/editado, o quitado a mano)

error y sin_confirmar solo salen por acción manual (reintentar / marcar recibido): un
borrador repetido es peor que uno que falta, así que nunca se reenvía a ciegas.
Cada cambio de estado queda como evento (trazabilidad).
"""

import json
import os
import sqlite3
from datetime import datetime

from app.publicacion import db
from app.publicacion.horarios import ahora, iso

PLATAFORMA = "tiktok"   # default de las funciones (la primera plataforma); el motor pasa la de cada cuenta
MAX_INTENTOS = 3


class TransicionInvalida(Exception):
    pass


class PublicacionNoEncontrada(Exception):
    pass


# ── Eventos ──────────────────────────────────────────────────

def registrar_evento(conn: sqlite3.Connection, publicacion_id: int | None, tipo: str, mensaje: str,
                     detalle: dict | None = None, cuenta_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO eventos (publicacion_id, cuenta_id, ts, tipo, mensaje, detalle) VALUES (?,?,?,?,?,?)",
        (publicacion_id, cuenta_id, iso(ahora()), tipo, mensaje,
         json.dumps(detalle, ensure_ascii=False) if detalle else None),
    )


def eventos(conn: sqlite3.Connection, publicacion_id: int) -> list[dict]:
    filas = conn.execute(
        "SELECT ts, tipo, mensaje, detalle FROM eventos WHERE publicacion_id = ? ORDER BY id",
        (publicacion_id,),
    ).fetchall()
    return [{**dict(f), "detalle": json.loads(f["detalle"]) if f["detalle"] else None} for f in filas]


# ── Lectura ──────────────────────────────────────────────────

def obtener(conn: sqlite3.Connection, pub_id: int) -> dict:
    fila = conn.execute("SELECT * FROM publicaciones WHERE id = ?", (pub_id,)).fetchone()
    if not fila:
        raise PublicacionNoEncontrada(pub_id)
    return dict(fila)


def listar(conn: sqlite3.Connection, nicho: str | None = None, estado: str | None = None,
           plataforma: str = PLATAFORMA) -> list[dict]:
    sql, args = "SELECT * FROM publicaciones WHERE plataforma = ?", [plataforma]
    if nicho:
        sql += " AND nicho = ?"
        args.append(nicho)
    if estado:
        sql += " AND estado = ?"
        args.append(estado)
    sql += " ORDER BY CASE estado WHEN 'en_cola' THEN 0 ELSE 1 END, " \
           "CASE estado WHEN 'en_cola' THEN orden END, COALESCE(enviada_en, actualizada_en) DESC"
    return [dict(f) for f in conn.execute(sql, args).fetchall()]


def primero_en_cola(conn: sqlite3.Connection, nicho: str, plataforma: str = PLATAFORMA) -> dict | None:
    fila = conn.execute(
        "SELECT * FROM publicaciones WHERE plataforma = ? AND nicho = ? AND estado = 'en_cola' "
        "ORDER BY orden LIMIT 1",
        (plataforma, nicho),
    ).fetchone()
    return dict(fila) if fila else None


def slots_ocupados(conn: sqlite3.Connection, nicho: str, plataforma: str = PLATAFORMA) -> set[str]:
    filas = conn.execute(
        f"SELECT slot FROM publicaciones WHERE plataforma = ? AND nicho = ? AND slot IS NOT NULL "
        f"AND estado IN {db.ESTADOS_OCUPAN_SLOT!r}",
        (plataforma, nicho),
    ).fetchall()
    return {f["slot"] for f in filas}


def ultimo_envio(conn: sqlite3.Connection, nicho: str, plataforma: str = PLATAFORMA) -> datetime | None:
    fila = conn.execute(
        f"SELECT MAX(enviada_en) AS t FROM publicaciones WHERE plataforma = ? AND nicho = ? "
        f"AND estado IN {db.ESTADOS_OCUPAN_SLOT!r}",
        (plataforma, nicho),
    ).fetchone()
    return datetime.fromisoformat(fila["t"]) if fila and fila["t"] else None


# ── Cambios de estado ────────────────────────────────────────

def _cambiar(conn: sqlite3.Connection, pub: dict, nuevo: str, mensaje: str,
             detalle: dict | None = None, **campos) -> None:
    campos["estado"] = nuevo
    campos["actualizada_en"] = iso(ahora())
    sets = ", ".join(f"{k} = ?" for k in campos)
    conn.execute(f"UPDATE publicaciones SET {sets} WHERE id = ?", (*campos.values(), pub["id"]))
    registrar_evento(conn, pub["id"], "transicion", f"{pub['estado']} → {nuevo}: {mensaje}", detalle)


def _orden_al_final(conn: sqlite3.Connection, nicho: str, plataforma: str) -> float:
    fila = conn.execute(
        "SELECT MAX(orden) AS m FROM publicaciones WHERE plataforma = ? AND nicho = ? AND estado = 'en_cola'",
        (plataforma, nicho),
    ).fetchone()
    return (fila["m"] or 0) + 1


def _orden_al_frente(conn: sqlite3.Connection, nicho: str, plataforma: str) -> float:
    fila = conn.execute(
        "SELECT MIN(orden) AS m FROM publicaciones WHERE plataforma = ? AND nicho = ? AND estado = 'en_cola'",
        (plataforma, nicho),
    ).fetchone()
    return (fila["m"] if fila["m"] is not None else 1) - 1


def encolar(conn: sqlite3.Connection, session_id: str, clip_id: str, nicho: str,
            ruta_video: str, titulo: str | None, texto: str | None = None, *,
            plataforma: str = PLATAFORMA, metadatos: dict | None = None) -> dict:
    """Idempotente: aprobar dos veces no duplica. Un clip cancelado (editado) vuelve al final.
    `texto` (lo que se muestra/pega) y `metadatos` (lo que va por la API) quedan congelados con el envío."""
    meta = json.dumps(metadatos, ensure_ascii=False) if metadatos else None
    with db.transaccion(conn):
        fila = conn.execute(
            "SELECT * FROM publicaciones WHERE plataforma = ? AND session_id = ? AND clip_id = ?",
            (plataforma, session_id, clip_id),
        ).fetchone()
        if fila:
            pub = dict(fila)
            if pub["estado"] == "cancelado":
                _cambiar(conn, pub, "en_cola", "aprobado de nuevo", orden=_orden_al_final(conn, nicho, plataforma),
                         ruta_video=ruta_video, titulo=titulo, texto=texto, metadatos=meta, intentos=0, slot=None,
                         publish_id=None, sesion_subida=None, error_codigo=None, error_mensaje=None)
            return obtener(conn, pub["id"])

        momento = iso(ahora())
        cur = conn.execute(
            "INSERT INTO publicaciones (plataforma, session_id, clip_id, nicho, ruta_video, titulo, texto, metadatos, "
            "orden, estado, encolada_en, actualizada_en) VALUES (?,?,?,?,?,?,?,?,?, 'en_cola', ?, ?)",
            (plataforma, session_id, clip_id, nicho, ruta_video, titulo, texto, meta,
             _orden_al_final(conn, nicho, plataforma), momento, momento),
        )
        registrar_evento(conn, cur.lastrowid, "transicion", "encolado al aprobar el clip",
                         {"session_id": session_id, "clip_id": clip_id, "nicho": nicho})
        return obtener(conn, cur.lastrowid)


def cancelar_por_clip(conn: sqlite3.Connection, session_id: str, clip_id: str, motivo: str) -> None:
    """Clip descartado o editado en la revisión: sale de las colas de todas las plataformas
    en las que todavía no se envió."""
    with db.transaccion(conn):
        for fila in conn.execute(
            "SELECT * FROM publicaciones WHERE session_id = ? AND clip_id = ? AND estado = 'en_cola'",
            (session_id, clip_id),
        ).fetchall():
            _cambiar(conn, dict(fila), "cancelado", motivo)


def quitar(conn: sqlite3.Connection, pub_id: int) -> dict:
    with db.transaccion(conn):
        pub = obtener(conn, pub_id)
        if pub["estado"] not in ("en_cola", "error"):
            raise TransicionInvalida(f"No se puede quitar una publicación en estado {pub['estado']}")
        _cambiar(conn, pub, "cancelado", "quitado a mano desde el panel")
    return obtener(conn, pub_id)


def mover(conn: sqlite3.Connection, pub_id: int, direccion: str) -> dict:
    """Intercambia el lugar con el vecino de arriba/abajo en la cola."""
    with db.transaccion(conn):
        pub = obtener(conn, pub_id)
        if pub["estado"] != "en_cola":
            raise TransicionInvalida("Solo se reordena lo que está en cola")
        if direccion == "arriba":
            vecino = conn.execute(
                "SELECT * FROM publicaciones WHERE plataforma = ? AND nicho = ? AND estado = 'en_cola' "
                "AND orden < ? ORDER BY orden DESC LIMIT 1", (pub["plataforma"], pub["nicho"], pub["orden"]),
            ).fetchone()
        elif direccion == "abajo":
            vecino = conn.execute(
                "SELECT * FROM publicaciones WHERE plataforma = ? AND nicho = ? AND estado = 'en_cola' "
                "AND orden > ? ORDER BY orden ASC LIMIT 1", (pub["plataforma"], pub["nicho"], pub["orden"]),
            ).fetchone()
        else:
            raise ValueError("direccion debe ser 'arriba' o 'abajo'")
        if vecino:
            conn.execute("UPDATE publicaciones SET orden = ? WHERE id = ?", (vecino["orden"], pub["id"]))
            conn.execute("UPDATE publicaciones SET orden = ? WHERE id = ?", (pub["orden"], vecino["id"]))
            registrar_evento(conn, pub["id"], "manual", f"movido hacia {direccion} en la cola")
    return obtener(conn, pub_id)


def reintentar(conn: sqlite3.Connection, pub_id: int) -> dict:
    """error / sin_confirmar / cancelado → al frente de la cola, con los intentos en cero."""
    with db.transaccion(conn):
        pub = obtener(conn, pub_id)
        if pub["estado"] not in ("error", "sin_confirmar", "cancelado"):
            raise TransicionInvalida(f"No se reintenta una publicación en estado {pub['estado']}")
        _cambiar(conn, pub, "en_cola", "reintento manual desde el panel",
                 orden=_orden_al_frente(conn, pub["nicho"], pub["plataforma"]), intentos=0, slot=None, publish_id=None,
                 sesion_subida=None, subida_completa=0, error_codigo=None, error_mensaje=None, proceso_pid=None,
                 proceso_inicio=None)
    return obtener(conn, pub_id)


def marcar_recibido(conn: sqlite3.Connection, pub_id: int) -> dict:
    """sin_confirmar → en_bandeja, cuando el usuario verificó en la app que el borrador llegó."""
    with db.transaccion(conn):
        pub = obtener(conn, pub_id)
        if pub["estado"] != "sin_confirmar":
            raise TransicionInvalida("Solo se marca como recibido algo sin confirmar")
        _cambiar(conn, pub, "en_bandeja", "marcado a mano: el borrador está en la bandeja",
                 confirmada_en=iso(ahora()))
    return obtener(conn, pub_id)


# ── Usadas por el motor ──────────────────────────────────────

def reclamar(conn: sqlite3.Connection, pub_id: int, slot: str | None, inicio_proceso: str) -> bool:
    """
    Toma la publicación para enviarla, ocupando `slot`. False si otro proceso ganó
    (ya no está en_cola, o el slot ya está ocupado: índice único parcial).
    """
    try:
        with db.transaccion(conn):
            pub = obtener(conn, pub_id)
            if pub["estado"] != "en_cola":
                return False
            _cambiar(conn, pub, "enviando", f"enviando (horario {slot})" if slot else "enviando (envío de prueba)",
                     slot=slot, enviada_en=iso(ahora()), intentos=pub["intentos"] + 1,
                     publish_id=None, sesion_subida=None, subida_completa=0,
                     proceso_pid=os.getpid(), proceso_inicio=inicio_proceso,
                     error_codigo=None, error_mensaje=None)
            return True
    except sqlite3.IntegrityError:
        return False


def guardar_publish_id(conn: sqlite3.Connection, pub_id: int, publish_id: str) -> None:
    conn.execute("UPDATE publicaciones SET publish_id = ?, actualizada_en = ? WHERE id = ?",
                 (publish_id, iso(ahora()), pub_id))


def guardar_sesion_subida(conn: sqlite3.Connection, pub_id: int, url: str) -> None:
    conn.execute("UPDATE publicaciones SET sesion_subida = ?, actualizada_en = ? WHERE id = ?",
                 (url, iso(ahora()), pub_id))


def marcar_subida_completa(conn: sqlite3.Connection, pub_id: int) -> None:
    conn.execute("UPDATE publicaciones SET subida_completa = 1, actualizada_en = ? WHERE id = ?",
                 (iso(ahora()), pub_id))


def resolver(conn: sqlite3.Connection, pub_id: int, resultado: str, mensaje: str,
             codigo: str | None = None, detalle: dict | None = None) -> dict:
    """
    Cierra un envío. `resultado`:
      en_bandeja    → éxito.
      reintentable  → vuelve a la cola (mismo lugar) o error si se agotaron los intentos.
      devolver      → vuelve a la cola sin gastar intento (problema de la cuenta, no del clip).
      error         → error definitivo.
      sin_confirmar → no se sabe si llegó.
    """
    with db.transaccion(conn):
        pub = obtener(conn, pub_id)
        comunes = {"proceso_pid": None, "proceso_inicio": None}
        if resultado == "en_bandeja":
            _cambiar(conn, pub, "en_bandeja", mensaje, detalle, confirmada_en=iso(ahora()), **comunes)
        elif resultado == "sin_confirmar":
            _cambiar(conn, pub, "sin_confirmar", mensaje, detalle,
                     error_codigo=codigo, error_mensaje=mensaje, **comunes)
        elif resultado == "error" or (resultado == "reintentable" and pub["intentos"] >= MAX_INTENTOS):
            texto = mensaje if resultado == "error" else f"{mensaje} (se agotaron los {MAX_INTENTOS} intentos)"
            _cambiar(conn, pub, "error", texto, detalle, slot=None, error_codigo=codigo,
                     error_mensaje=texto, **comunes)
        elif resultado in ("reintentable", "devolver"):
            intentos = pub["intentos"] if resultado == "reintentable" else max(pub["intentos"] - 1, 0)
            _cambiar(conn, pub, "en_cola", mensaje, detalle, slot=None, publish_id=None, sesion_subida=None,
                     subida_completa=0,
                     intentos=intentos,
                     error_codigo=codigo, error_mensaje=mensaje, **comunes)
        else:
            raise ValueError(f"resultado desconocido: {resultado}")
    return obtener(conn, pub_id)
