"""
db.py — SQLite de la cola de publicación (backend/publicacion.db, fuera de git).

Es la excepción a "sin base de datos" del backend (ver DECISIONES.md): el motor puede
correr en dos procesos a la vez (uvicorn --reload) y tiene que ser imposible ocupar un
mismo horario dos veces. Eso lo garantiza el índice único parcial ux_publicaciones_slot
más el UPDATE condicional de cola.reclamar(), no un candado en memoria.

Fechas: ISO 8601 con zona de Lima (ver horarios.ZONA), ej. 2026-10-09T12:00:00-05:00.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.paths import PROJECT_ROOT

# PUBLICACION_DB permite apuntar a otra base (pruebas sin tocar la cola real)
from core.config_local import ruta  # noqa: E402

# CLIP-54: PUBLICACION_DB del .env (p. ej. data/publicacion.db, relativo a la raíz del repo)
DB_PATH: Path = ruta("PUBLICACION_DB", PROJECT_ROOT / "backend" / "publicacion.db")

PLATAFORMAS = ("tiktok", "youtube")

# Estados en los que una publicación ocupa su horario (no se puede volver a usar)
ESTADOS_OCUPAN_SLOT = ("enviando", "en_bandeja", "sin_confirmar")

_ESQUEMA = f"""
CREATE TABLE IF NOT EXISTS cuentas (
    id             INTEGER PRIMARY KEY,
    plataforma     TEXT NOT NULL,
    nicho          TEXT NOT NULL,
    modo           TEXT NOT NULL,              -- 'real' | 'simulado'
    nombre         TEXT,
    estado         TEXT NOT NULL,              -- conectada | requiere_reconexion | pausada
    motivo         TEXT,
    pausada_hasta  TEXT,
    open_id        TEXT,
    access_token   TEXT,
    access_vence   TEXT,
    refresh_token  TEXT,
    refresh_vence  TEXT,
    horarios       TEXT NOT NULL,              -- "8,12,16,20"
    creada         TEXT NOT NULL,
    actualizada    TEXT NOT NULL,
    UNIQUE (plataforma, nicho)
);

CREATE TABLE IF NOT EXISTS publicaciones (
    id              INTEGER PRIMARY KEY,
    plataforma      TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    clip_id         TEXT NOT NULL,
    nicho           TEXT NOT NULL,
    ruta_video      TEXT NOT NULL,
    titulo          TEXT,
    texto           TEXT,                      -- descripción + # para pegar al activar el borrador (se congela al encolar)
    metadatos       TEXT,                      -- JSON (titulo, descripcion, tags) que va por la API (YouTube)
    sesion_subida   TEXT,                      -- URL de la subida reanudable de YouTube (nunca a eventos ni al panel)
    orden           REAL NOT NULL,
    estado          TEXT NOT NULL,             -- en_cola | enviando | en_bandeja | sin_confirmar | error | cancelado
    slot            TEXT,                      -- horario que cubre (ISO, minutos)
    publish_id      TEXT,
    subida_completa INTEGER NOT NULL DEFAULT 0, -- 1 = TikTok respondió 201 (desde ahí puede existir el borrador)
    intentos        INTEGER NOT NULL DEFAULT 0,
    error_codigo    TEXT,
    error_mensaje   TEXT,
    proceso_pid     INTEGER,                   -- proceso que la está enviando (recuperación)
    proceso_inicio  TEXT,
    encolada_en     TEXT NOT NULL,
    enviada_en      TEXT,
    confirmada_en   TEXT,
    actualizada_en  TEXT NOT NULL,
    UNIQUE (plataforma, session_id, clip_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_publicaciones_slot
    ON publicaciones (plataforma, nicho, slot)
    WHERE estado IN {ESTADOS_OCUPAN_SLOT!r};

CREATE INDEX IF NOT EXISTS ix_publicaciones_cola
    ON publicaciones (plataforma, nicho, estado, orden);

CREATE TABLE IF NOT EXISTS eventos (
    id              INTEGER PRIMARY KEY,
    publicacion_id  INTEGER,
    cuenta_id       INTEGER,
    ts              TEXT NOT NULL,
    tipo            TEXT NOT NULL,             -- transicion | init | chunk | status | error | manual | cuenta
    mensaje         TEXT NOT NULL,
    detalle         TEXT                       -- JSON; nunca tokens
);

CREATE INDEX IF NOT EXISTS ix_eventos_pub ON eventos (publicacion_id, id);

CREATE TABLE IF NOT EXISTS revisiones (
    id         INTEGER PRIMARY KEY,
    plataforma TEXT NOT NULL DEFAULT 'tiktok',
    nicho      TEXT NOT NULL,
    desde      TEXT NOT NULL,
    hasta      TEXT NOT NULL,
    veces      INTEGER NOT NULL DEFAULT 1,
    decision   TEXT NOT NULL,
    envio      INTEGER NOT NULL DEFAULT 0      -- 1 si en esa revisión se envió algo
);

CREATE TABLE IF NOT EXISTS oauth_estados (
    state   TEXT PRIMARY KEY,
    nicho   TEXT NOT NULL,
    creado  TEXT NOT NULL
);
"""

_inicializadas: set[str] = set()


def conectar() -> sqlite3.Connection:
    """Conexión en autocommit; las escrituras que deben ser atómicas usan transaccion()."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    clave = str(DB_PATH)
    if clave not in _inicializadas:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_ESQUEMA)
        _migrar(conn)
        _inicializadas.add(clave)
    return conn


def _migrar(conn: sqlite3.Connection) -> None:
    """Columnas agregadas después de crear la base (CREATE TABLE IF NOT EXISTS no las suma)."""
    nuevas = {
        "publicaciones": {"texto": "TEXT", "metadatos": "TEXT", "sesion_subida": "TEXT"},
        "revisiones": {"plataforma": "TEXT NOT NULL DEFAULT 'tiktok'"},
    }
    for tabla, columnas in nuevas.items():
        existentes = {f["name"] for f in conn.execute(f"PRAGMA table_info({tabla})")}
        for nombre, tipo in columnas.items():
            if nombre not in existentes:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")


@contextmanager
def transaccion(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE: toma el candado de escritura al empezar (no a mitad)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
