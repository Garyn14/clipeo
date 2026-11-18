"""
chunk_manager.py — Gestiona el estado de procesamiento por chunks con checkpoints.

Uso interno:
    from core.chunk_manager import ChunkManager
    mgr = ChunkManager(session_dir, duracion_total_segundos, chunk_minutos=30)
    mgr.crear_plan(url="...", config="zapatillas_peru")

Además del estado por chunk (pendiente/completado/fallido), guarda el estado de cada
PASO — de sesión (descarga, plan, revision, fin) y por chunk (transcripcion, agente0..3,
corte) — que es lo que dibuja la web como círculos. Lo escribe core/pasos.py; el estado
del chunk se deriva de sus pasos para que los lectores viejos (state_reader.py) sigan
funcionando. Un pipeline_estado.json previo a los pasos se lee igual: sus pasos aparecen
como pendientes.
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

PASOS_SESION = ["descarga", "plan", "revision", "fin"]
# Buscar amplio → decidir estricto: A1/A2 dan cobertura, el juez es el único filtro de
# calidad y el A3 escribe el copy de lo aprobado (sin memoria del nicho: juez omitido y el
# A3 puntúa como antes).
PASOS_CHUNK  = ["transcripcion", "agente0", "agente1", "agente2", "juez", "agente3", "corte"]

ESTADOS_TERMINADOS = ("ok", "omitido")


_REINTENTOS_REEMPLAZO = 20
_ESPERA_REEMPLAZO_S = 0.05


def reemplazar_con_reintentos(tmp: Path, destino: Path) -> None:
    """
    tmp.replace(destino) tolerando el bloqueo de Windows: si otro proceso tiene `destino`
    abierto en ese instante (el backend lo lee cada pocos segundos), el reemplazo da
    PermissionError [WinError 5]. Es momentáneo: se reintenta hasta ~1 s antes de fallar.
    """
    for intento in range(_REINTENTOS_REEMPLAZO):
        try:
            tmp.replace(destino)
            return
        except PermissionError:
            if intento == _REINTENTOS_REEMPLAZO - 1:
                raise
            time.sleep(_ESPERA_REEMPLAZO_S)


def completar_juez_previo(pasos_chunk: dict) -> None:
    """
    Retrocompat (2026-10-03): un chunk que ya cortó antes de existir el paso "juez" lo recibe
    como omitido — si quedara pendiente, el chunk dejaría de verse completo y se reprocesaría.
    """
    corte = pasos_chunk.get("corte") or {}
    if "juez" not in pasos_chunk and corte.get("estado") in ESTADOS_TERMINADOS:
        pasos_chunk["juez"] = {**paso_vacio(), "estado": "omitido", "nota": "sesión previa al juez"}


def _seconds_to_hms(s: int) -> str:
    h   = s // 3600
    m   = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def paso_vacio() -> dict:
    return {
        "estado":     "pendiente",
        "inicio":     None,
        "fin":        None,
        "duracion_s": None,
        "intentos":   0,
        "error":      None,
        "salidas":    [],
        "nota":       None,
        "ia":         None,
        # Eventos en orden: {"tipo": "intento", ...} por cada intento (ver core/pasos.py) y
        # {"tipo": "reinicio", ...} cada vez que --reintentar lo vuelve a pendiente.
        "historial":  [],
    }


def paso_reiniciado(previo: dict, desde: str, chunk_id: str | None) -> dict:
    """Paso vuelto a pendiente que conserva su historia (intentos e historial)."""
    paso = paso_vacio()
    paso["intentos"]  = previo.get("intentos", 0)
    paso["historial"] = list(previo.get("historial") or [])
    if paso["intentos"] or paso["historial"]:
        paso["historial"].append({
            "tipo":  "reinicio",
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "desde": desde,
            "chunk": chunk_id,
        })
    return paso


class ChunkManager:
    def __init__(self, session_dir: Path, duracion_total: int = 0, chunk_minutos: int = 30):
        self.session_dir    = Path(session_dir)
        self.duracion_total = int(duracion_total)
        self.chunk_minutos  = chunk_minutos
        self.estado_path    = self.session_dir / "pipeline_estado.json"
        self._estado        = None

    # ── Creación / carga ────────────────────────────────────

    def iniciar(self, url: str = "", config: str = "default", modo: str = "automatico") -> dict:
        """Estado mínimo antes de conocer la duración (antes de descargar): sin chunks."""
        self._estado = {
            "url":      url,
            "config":   config,
            "modo":     modo,
            "creado":   datetime.now().isoformat(timespec="seconds"),
            "pasos":    {p: paso_vacio() for p in PASOS_SESION},
            "chunks":   {},
        }
        self._guardar()
        return self._estado

    def crear_plan(self, url: str = "", config: str = "default", modo: str = "automatico") -> dict:
        chunk_secs = self.chunk_minutos * 60
        chunks     = {}
        i          = 1
        inicio     = 0

        while inicio < self.duracion_total:
            fin      = min(inicio + chunk_secs, self.duracion_total)
            chunk_id = f"chunk_{i:03d}"
            chunks[chunk_id] = {
                "inicio_segundos": inicio,
                "fin_segundos":    int(fin),
                "inicio_ts":       _seconds_to_hms(inicio),
                "fin_ts":          _seconds_to_hms(int(fin)),
                "estado":          "pendiente",
                "pasos":           {p: paso_vacio() for p in PASOS_CHUNK},
            }
            i      += 1
            inicio += chunk_secs

        previo = self._estado or {}
        self._estado = {
            "url":                     url or previo.get("url", ""),
            "config":                  config,
            "modo":                    modo,
            "duracion_total_segundos": self.duracion_total,
            "chunk_minutos":           self.chunk_minutos,
            "creado":                  previo.get("creado") or datetime.now().isoformat(timespec="seconds"),
            # Los pasos de sesión ya corridos (descarga) sobreviven a la creación del plan
            "pasos":                   previo.get("pasos") or {p: paso_vacio() for p in PASOS_SESION},
            "chunks":                  chunks,
        }
        # Campos de sesión anteriores al plan: `video` (leído en la descarga) y `fuente` (CLIP-27, medios)
        for clave in ("video", "fuente"):
            if previo.get(clave):
                self._estado[clave] = previo[clave]
        self._guardar()
        return self._estado

    def crear_chunk_unico(self, chunk_id: str = "chunk_001") -> dict:
        """Plan de un solo chunk sin rango de tiempo (modo --test: la transcripción ya existe)."""
        self._estado["chunks"] = {
            chunk_id: {
                "inicio_segundos": 0,
                "fin_segundos":    0,
                "inicio_ts":       _seconds_to_hms(0),
                "fin_ts":          _seconds_to_hms(0),
                "estado":          "pendiente",
                "pasos":           {p: paso_vacio() for p in PASOS_CHUNK},
            }
        }
        self._guardar()
        return self._estado

    def cargar_estado(self) -> dict | None:
        if self.estado_path.exists():
            self._estado = json.loads(self.estado_path.read_text(encoding="utf-8"))
            self._completar_pasos()
            return self._estado
        return None

    def _completar_pasos(self) -> None:
        """Retrocompat: estados previos a los pasos reciben pasos pendientes."""
        pasos = self._estado.setdefault("pasos", {})
        for p in PASOS_SESION:
            pasos.setdefault(p, paso_vacio()).setdefault("historial", [])
        for chunk in self._estado.setdefault("chunks", {}).values():
            cp = chunk.setdefault("pasos", {})
            completar_juez_previo(cp)
            for p in PASOS_CHUNK:
                cp.setdefault(p, paso_vacio()).setdefault("historial", [])

    def tiene_plan(self) -> bool:
        return bool(self._estado and self._estado.get("chunks"))

    # ── Persistencia ────────────────────────────────────────

    def _guardar(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.estado_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._estado, ensure_ascii=False, indent=2), encoding="utf-8")
        # Reemplazo atómico: el backend lee este archivo mientras el pipeline escribe
        reemplazar_con_reintentos(tmp, self.estado_path)

    # ── Pasos ───────────────────────────────────────────────

    def paso(self, chunk_id: str | None, nombre: str) -> dict:
        if chunk_id is None:
            contenedor = self._estado.setdefault("pasos", {})
        else:
            contenedor = self._estado["chunks"][chunk_id].setdefault("pasos", {})
        return contenedor.setdefault(nombre, paso_vacio())

    def actualizar_sesion(self, **campos) -> None:
        """Campos de nivel sesión (ej. `video`: título/canal/miniatura para la web)."""
        self._estado.update(campos)
        self._guardar()

    def actualizar_paso(self, chunk_id: str | None, nombre: str, **campos) -> dict:
        paso = self.paso(chunk_id, nombre)
        paso.update(campos)
        if chunk_id is not None:
            self._derivar_estado_chunk(chunk_id)
        self._guardar()
        return paso

    def _derivar_estado_chunk(self, chunk_id: str) -> None:
        chunk  = self._estado["chunks"][chunk_id]
        pasos  = [chunk["pasos"][p] for p in PASOS_CHUNK if p in chunk["pasos"]]
        if any(p["estado"] == "error" for p in pasos):
            chunk["estado"] = "fallido"
            chunk["error"]  = next(p["error"]["mensaje"] for p in pasos if p["estado"] == "error")
        elif pasos and all(p["estado"] in ESTADOS_TERMINADOS for p in pasos):
            chunk["estado"] = "completado"
            chunk.pop("error", None)
        else:
            chunk["estado"] = "pendiente"
            chunk.pop("error", None)

    def resetear_desde(self, nombre: str, chunk_id: str | None = None) -> list[str]:
        """
        Vuelve a 'pendiente' el paso `nombre` y todos los posteriores — en `chunk_id`, o
        en cada chunk donde ese paso esté en error si chunk_id es None. Para pasos de
        sesión resetea solo los de sesión. Devuelve las salidas (rutas relativas a la
        sesión) de los pasos reseteados, para que el llamador las borre.
        """
        salidas: list[str] = []

        def _reset(contenedor: dict, orden: list[str], cid: str | None) -> None:
            for p in orden[orden.index(nombre):]:
                previo = contenedor.get(p, {})
                salidas.extend(previo.get("salidas", []))
                contenedor[p] = paso_reiniciado(previo, nombre, cid)

        if nombre in PASOS_SESION:
            _reset(self._estado["pasos"], PASOS_SESION, None)
        elif nombre in PASOS_CHUNK:
            if chunk_id is not None:
                if chunk_id not in self._estado["chunks"]:
                    raise ValueError(f"Chunk desconocido: {chunk_id}")
                objetivos = [chunk_id]
            else:
                objetivos = [
                    cid for cid, c in self._estado["chunks"].items()
                    if c["pasos"].get(nombre, {}).get("estado") == "error"
                ]
            for cid in objetivos:
                _reset(self._estado["chunks"][cid]["pasos"], PASOS_CHUNK, cid)
                self._derivar_estado_chunk(cid)
            # Un chunk reabierto deja la revisión de la sesión sin terminar
            if objetivos:
                for p in ("revision", "fin"):
                    previo = self._estado["pasos"].get(p, {})
                    self._estado["pasos"][p] = paso_reiniciado(previo, nombre, None)
        else:
            raise ValueError(f"Paso desconocido: {nombre}")

        self._guardar()
        return salidas

    # ── Consultas y mutaciones ──────────────────────────────

    def get_pendientes(self) -> list[dict]:
        """Chunks por procesar: no completados y sin un paso en error (esos esperan reintento)."""
        return [
            {"id": k, **v}
            for k, v in self._estado.get("chunks", {}).items()
            if v["estado"] != "completado"
            and not any(p.get("estado") == "error" for p in v.get("pasos", {}).values())
        ]

    def marcar_completado(self, chunk_id: str) -> None:
        self._estado["chunks"][chunk_id]["estado"] = "completado"
        self._guardar()

    def marcar_fallido(self, chunk_id: str, error: str) -> None:
        self._estado["chunks"][chunk_id]["estado"] = "fallido"
        self._estado["chunks"][chunk_id]["error"]   = str(error)
        self._guardar()

    def ya_completado(self, chunk_id: str) -> bool:
        return self._estado.get("chunks", {}).get(chunk_id, {}).get("estado") == "completado"

    # ── Display ─────────────────────────────────────────────

    def resumen(self) -> None:
        chunks      = self._estado.get("chunks", {})
        total       = len(chunks)
        completados = sum(1 for v in chunks.values() if v["estado"] == "completado")
        pendientes  = sum(1 for v in chunks.values() if v["estado"] == "pendiente")
        fallidos    = sum(1 for v in chunks.values() if v["estado"] == "fallido")
        print(
            f"[CHUNKS] Total: {total} | Completados: {completados} | "
            f"Pendientes: {pendientes} | Fallidos: {fallidos}"
        )
