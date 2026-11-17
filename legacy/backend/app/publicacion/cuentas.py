"""
cuentas.py — Una cuenta por (plataforma, nicho), y su estado operativo.

  conectada           → el motor le envía clips en sus horarios.
  pausada             → la plataforma frenó por límite (borradores pendientes, cuota); se reanuda
                        sola al pasar `pausada_hasta` (o a mano desde el panel).
  requiere_reconexion → token inválido/revocado; hay que volver a conectar.

modo 'simulado' (para probar todo sin la app de la plataforma) o 'real'. Los tokens nunca salen
de acá hacia la API del panel (ver publica()).
"""

import sqlite3
from datetime import datetime, timedelta

from app.publicacion import db
from app.publicacion.cola import PLATAFORMA, registrar_evento
from app.publicacion.horarios import HORARIOS_DEFAULT, ahora, iso, parsear_horarios

PAUSA_PENDIENTES = timedelta(hours=24)

_CAMPOS_PUBLICOS = ("id", "plataforma", "nicho", "modo", "nombre", "estado", "motivo", "pausada_hasta",
                    "access_vence", "refresh_vence", "horarios", "creada", "actualizada")


class CuentaNoEncontrada(Exception):
    pass


def publica(cuenta: dict) -> dict:
    return {k: cuenta.get(k) for k in _CAMPOS_PUBLICOS}


def por_nicho(conn: sqlite3.Connection, nicho: str, plataforma: str = PLATAFORMA) -> dict | None:
    fila = conn.execute("SELECT * FROM cuentas WHERE plataforma = ? AND nicho = ?",
                        (plataforma, nicho)).fetchone()
    return dict(fila) if fila else None


def obtener(conn: sqlite3.Connection, cuenta_id: int) -> dict:
    fila = conn.execute("SELECT * FROM cuentas WHERE id = ?", (cuenta_id,)).fetchone()
    if not fila:
        raise CuentaNoEncontrada(cuenta_id)
    return dict(fila)


def listar(conn: sqlite3.Connection, plataforma: str | None = None) -> list[dict]:
    """Las cuentas de una plataforma, o de todas (None: lo que recorre el motor)."""
    if plataforma is None:
        filas = conn.execute("SELECT * FROM cuentas ORDER BY plataforma, nicho").fetchall()
    else:
        filas = conn.execute("SELECT * FROM cuentas WHERE plataforma = ? ORDER BY nicho", (plataforma,)).fetchall()
    return [dict(f) for f in filas]


def _actualizar(conn: sqlite3.Connection, cuenta_id: int, **campos) -> None:
    campos["actualizada"] = iso(ahora())
    sets = ", ".join(f"{k} = ?" for k in campos)
    conn.execute(f"UPDATE cuentas SET {sets} WHERE id = ?", (*campos.values(), cuenta_id))


def conectar(conn: sqlite3.Connection, nicho: str, modo: str, nombre: str | None = None,
             tokens: dict | None = None, plataforma: str = PLATAFORMA) -> dict:
    """Alta o reconexión. `tokens`: open_id, access_token, access_vence, refresh_token, refresh_vence."""
    tokens = tokens or {}
    momento = iso(ahora())
    with db.transaccion(conn):
        existente = por_nicho(conn, nicho, plataforma)
        if existente:
            _actualizar(conn, existente["id"], modo=modo, nombre=nombre or existente["nombre"],
                        estado="conectada", motivo=None, pausada_hasta=None, **tokens)
            cuenta_id = existente["id"]
        else:
            cuenta_id = conn.execute(
                "INSERT INTO cuentas (plataforma, nicho, modo, nombre, estado, horarios, creada, actualizada, "
                "open_id, access_token, access_vence, refresh_token, refresh_vence) "
                "VALUES (?,?,?,?, 'conectada', ?,?,?, ?,?,?,?,?)",
                (plataforma, nicho, modo, nombre, HORARIOS_DEFAULT, momento, momento,
                 tokens.get("open_id"), tokens.get("access_token"), tokens.get("access_vence"),
                 tokens.get("refresh_token"), tokens.get("refresh_vence")),
            ).lastrowid
        registrar_evento(conn, None, "cuenta", f"cuenta {plataforma} de {nicho} conectada (modo {modo})",
                         {"nombre": nombre}, cuenta_id=cuenta_id)
    return obtener(conn, cuenta_id)


def guardar_tokens(conn: sqlite3.Connection, cuenta_id: int, tokens: dict) -> dict:
    _actualizar(conn, cuenta_id, **tokens)
    return obtener(conn, cuenta_id)


def pausar(conn: sqlite3.Connection, cuenta_id: int, motivo: str, duracion: timedelta = PAUSA_PENDIENTES) -> None:
    hasta = iso(ahora() + duracion)
    _actualizar(conn, cuenta_id, estado="pausada", motivo=motivo, pausada_hasta=hasta)
    registrar_evento(conn, None, "cuenta", f"cuenta pausada hasta {hasta}: {motivo}", cuenta_id=cuenta_id)


def requiere_reconexion(conn: sqlite3.Connection, cuenta_id: int, motivo: str) -> None:
    _actualizar(conn, cuenta_id, estado="requiere_reconexion", motivo=motivo, pausada_hasta=None)
    registrar_evento(conn, None, "cuenta", f"hay que reconectar la cuenta: {motivo}", cuenta_id=cuenta_id)


def reanudar(conn: sqlite3.Connection, cuenta_id: int, motivo: str = "reanudada a mano desde el panel") -> dict:
    cuenta = obtener(conn, cuenta_id)
    if cuenta["estado"] != "pausada":
        return cuenta
    _actualizar(conn, cuenta_id, estado="conectada", motivo=None, pausada_hasta=None)
    registrar_evento(conn, None, "cuenta", motivo, cuenta_id=cuenta_id)
    return obtener(conn, cuenta_id)


def reanudar_vencidas(conn: sqlite3.Connection, momento: datetime) -> None:
    for c in listar(conn):
        if c["estado"] == "pausada" and c["pausada_hasta"] and datetime.fromisoformat(c["pausada_hasta"]) <= momento:
            reanudar(conn, c["id"], "pausa terminada: la cuenta vuelve a enviar")


def cambiar_horarios(conn: sqlite3.Connection, cuenta_id: int, horarios: str) -> dict:
    horas = parsear_horarios(horarios)
    _actualizar(conn, cuenta_id, horarios=",".join(str(h) for h in horas))
    return obtener(conn, cuenta_id)
