"""
chunk_manager.py — Gestiona el estado de procesamiento por chunks con checkpoints.

Uso interno:
    from core.chunk_manager import ChunkManager
    mgr = ChunkManager(session_dir, duracion_total_segundos, chunk_minutos=30)
    mgr.crear_plan(url="...", config="zapatillas_peru")
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


def _seconds_to_hms(s: int) -> str:
    h   = s // 3600
    m   = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


class ChunkManager:
    def __init__(self, session_dir: Path, duracion_total: int, chunk_minutos: int = 30):
        self.session_dir    = Path(session_dir)
        self.duracion_total = int(duracion_total)
        self.chunk_minutos  = chunk_minutos
        self.estado_path    = self.session_dir / "pipeline_estado.json"
        self._estado        = None

    # ── Creación / carga ────────────────────────────────────

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
            }
            i      += 1
            inicio += chunk_secs

        self._estado = {
            "url":                     url,
            "config":                  config,
            "modo":                    modo,
            "duracion_total_segundos": self.duracion_total,
            "chunk_minutos":           self.chunk_minutos,
            "creado":                  datetime.now().isoformat(timespec="seconds"),
            "chunks":                  chunks,
        }
        self._guardar()
        return self._estado

    def cargar_estado(self) -> dict | None:
        if self.estado_path.exists():
            self._estado = json.loads(self.estado_path.read_text(encoding="utf-8"))
            return self._estado
        return None

    # ── Persistencia ────────────────────────────────────────

    def _guardar(self) -> None:
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.estado_path.write_text(
            json.dumps(self._estado, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Consultas y mutaciones ──────────────────────────────

    def get_pendientes(self) -> list[dict]:
        return [
            {"id": k, **v}
            for k, v in self._estado.get("chunks", {}).items()
            if v["estado"] == "pendiente"
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
