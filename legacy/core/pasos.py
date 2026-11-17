"""
pasos.py — Orquestación genérica de pasos: estado, trazas, clasificación de errores y
reintentos automáticos. No sabe nada de agentes ni de video — eso lo pone pipeline.py
como funciones de paso.

Uso interno:
    from core.pasos import ejecutar_paso, PasoFallido, ErrorPaso
    ejecutar_paso(mgr, "chunk_001", "agente1", lambda: {...}, trace_dir=...)

Una función de paso devuelve None o un dict opcional:
    {"salidas": [Path|str, ...], "omitido": bool, "nota": str}
- salidas: archivos que produjo (se borran si el paso se reintenta desde la web).
- omitido: el paso no aplicaba (ej. Agente 0 sin diarización); cuenta como terminado.

Errores: se clasifican en reintentables (límite de uso de Claude, Colab caído, red) y no
reintentables (configuración, entrada faltante, video privado). Los reintentables se
reintentan solos con espera creciente (PIPELINE_ESPERAS_REINTENTO, default "30,120,300"
segundos — 3 reintentos); si se agotan, o si el error no es reintentable, el paso queda en
'error' y se lanza PasoFallido. El reintento manual (pipeline.py --reintentar) siempre
está permitido.
"""

import os
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from core.chunk_manager import ESTADOS_TERMINADOS

_ESPERAS_DEFAULT = (30, 120, 300)


class ErrorPaso(RuntimeError):
    """Error explícito de una función de paso, con su clasificación."""

    def __init__(self, mensaje: str, reintentable: bool = False):
        super().__init__(mensaje)
        self.reintentable = reintentable


class PasoFallido(Exception):
    def __init__(self, chunk_id: str | None, paso: str, error: dict):
        donde = f"{chunk_id}/{paso}" if chunk_id else paso
        super().__init__(f"{donde}: {error['mensaje']}")
        self.chunk_id = chunk_id
        self.paso     = paso
        self.error    = error


def _esperas() -> tuple[int, ...]:
    raw = os.environ.get("PIPELINE_ESPERAS_REINTENTO", "").strip()
    if not raw:
        return _ESPERAS_DEFAULT
    return tuple(int(x) for x in raw.split(",") if x.strip())


def clasificar_error(exc: BaseException) -> tuple[bool, str]:
    """Devuelve (reintentable, tipo)."""
    tipo = type(exc).__name__
    if hasattr(exc, "reintentable"):  # AIError, ColabError, DescargaError, ErrorPaso
        return bool(exc.reintentable), tipo
    if isinstance(exc, SystemExit):
        # Los agentes hacen sys.exit(1) cuando falta su archivo de entrada
        return False, "EntradaFaltante"
    if isinstance(exc, (KeyError, FileNotFoundError, ValueError, TypeError)):
        return False, tipo  # config incompleta, archivo ausente, datos inválidos
    return True, tipo


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _relativa(path, base: Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(p)


def _n_trazas(trace_dir: Path | None) -> int:
    # Misma numeración que ai_client/client.py: la llamada n es el request n-ésimo del dir
    if not trace_dir or not trace_dir.exists():
        return 0
    return len(list(trace_dir.glob("*_request.json")))


def _resumen_ia(trace_dir: Path | None) -> dict | None:
    if not trace_dir or not trace_dir.exists():
        return None
    llamadas = len(list(trace_dir.glob("*_request.json")))
    if not llamadas:
        return None
    return {
        "llamadas": llamadas,
        "errores":  len(list(trace_dir.glob("*_error.json"))),
        "trazas":   trace_dir.name,
    }


class Subpasos:
    """
    Progreso interno de un paso que agrupa varias tareas (ej. la Descarga: metadata → video
    → audio → duración), para que la web muestre en cuál va y con qué avance. Lo crea la
    función del paso, así que se reinicia en cada intento.

        sub = Subpasos(mgr, None, "descarga", [("video", "Descarga del video"), ...])
        with sub.paso("video"):
            ...
            sub.progreso("video", pct=45.0, bytes=..., total=...)
    """

    _INTERVALO_S = 1.0  # escribir progreso a disco como mucho una vez por segundo

    def __init__(self, mgr, chunk_id: str | None, nombre: str, definicion: list[tuple[str, str]]):
        self._mgr      = mgr
        self._chunk_id = chunk_id
        self._nombre   = nombre
        self._lista    = [
            {"id": i, "label": label, "estado": "pendiente", "detalle": None, "progreso": None}
            for i, label in definicion
        ]
        self._por_id      = {s["id"]: s for s in self._lista}
        self._ultima_esc  = 0.0
        self._guardar()

    def _guardar(self) -> None:
        self._ultima_esc = time.time()
        self._mgr.actualizar_paso(self._chunk_id, self._nombre, subpasos=self._lista)

    @contextmanager
    def paso(self, sid: str):
        sub = self._por_id[sid]
        sub.update(estado="corriendo", progreso=None)
        self._guardar()
        try:
            yield sub
        except BaseException:
            sub["estado"] = "error"
            self._guardar()
            raise
        sub["estado"] = "ok"
        if sub["progreso"] and sub["progreso"].get("pct") is not None:
            sub["progreso"]["pct"] = 100.0
        self._guardar()

    def detalle(self, sid: str, texto: str | None) -> None:
        self._por_id[sid]["detalle"] = texto
        self._guardar()

    def progreso(self, sid: str, **campos) -> None:
        sub   = self._por_id[sid]
        prev  = sub["progreso"] or {}
        cambia_pista = campos.get("pista") is not None and campos.get("pista") != prev.get("pista")
        sub["progreso"] = {**prev, **campos}
        if cambia_pista or time.time() - self._ultima_esc >= self._INTERVALO_S:
            try:
                self._guardar()
            except OSError as e:
                # El progreso es informativo: si no se pudo escribir, se escribe en el
                # próximo tick. Nunca debe tumbar la descarga (pasó con WinError 5).
                print(f"[PASOS] ⚠ progreso no guardado ({e}) — se reintenta en el próximo avance")


def ejecutar_paso(
    mgr,
    chunk_id: str | None,
    nombre: str,
    fn,
    *,
    trace_dir: Path | None = None,
    reintentar_auto: bool = True,
) -> dict:
    """Corre `fn` como el paso `nombre` y deja su estado en pipeline_estado.json."""
    paso = mgr.paso(chunk_id, nombre)
    if paso["estado"] in ESTADOS_TERMINADOS:
        return paso

    etiqueta = f"{chunk_id}/{nombre}" if chunk_id else nombre
    esperas  = _esperas() if reintentar_auto else ()
    base     = mgr.session_dir

    # Las trazas de intentos anteriores (incluso de corridas previas) se conservan: la
    # numeración sigue y cada evento del historial apunta a sus llamadas por rango.
    trace_previo = os.environ.get("PIPELINE_TRACE_DIR")
    if trace_dir is not None:
        os.environ["PIPELINE_TRACE_DIR"] = str(trace_dir)

    historial = paso.setdefault("historial", [])
    hubo_intentos = any(ev.get("tipo") == "intento" for ev in historial)

    def _cerrar(evento: dict, t0: float, resultado: str, error: dict | None, n_antes: int) -> None:
        n_despues = _n_trazas(trace_dir)
        evento.update(
            fin=_ahora(),
            duracion_s=round(time.time() - t0, 1),
            resultado=resultado,
            error=None if error is None else {k: v for k, v in error.items() if k != "detalle"},
            llamadas=[n_antes + 1, n_despues] if n_despues > n_antes else None,
        )

    try:
        intento = 0
        espera_previa = None
        while True:
            intento += 1
            t0 = time.time()
            n_antes = _n_trazas(trace_dir)
            evento = {
                "tipo":            "intento",
                "n":               paso.get("intentos", 0) + 1,
                "origen":          ("automatico" if intento > 1
                                    else "relanzado" if hubo_intentos else "inicial"),
                "espera_previa_s": espera_previa,
                "inicio":          _ahora(),
                "fin":             None,
                "duracion_s":      None,
                "resultado":       "corriendo",
                "error":           None,
                "llamadas":        None,
            }
            historial.append(evento)
            mgr.actualizar_paso(
                chunk_id, nombre,
                estado="corriendo", inicio=evento["inicio"], fin=None, duracion_s=None,
                intentos=evento["n"], historial=historial,
            )
            try:
                resultado = fn() or {}
            except KeyboardInterrupt:
                _cerrar(evento, t0, "interrumpido", None, n_antes)
                mgr.actualizar_paso(chunk_id, nombre, estado="pendiente", fin=None, historial=historial)
                raise
            except BaseException as e:  # noqa: BLE001 — incluye SystemExit de los agentes
                reintentable, tipo = clasificar_error(e)
                error = {
                    "tipo":         tipo,
                    "mensaje":      str(e) or tipo,
                    "reintentable": reintentable,
                    "detalle":      "".join(traceback.format_exception(e))[-4000:],
                    "fecha":        _ahora(),
                }
                _cerrar(evento, t0, "error", error, n_antes)
                quedan = intento <= len(esperas)
                if reintentable and quedan:
                    espera = esperas[intento - 1]
                    print(
                        f"[PASOS] ⚠ {etiqueta} falló ({tipo}: {str(e)[:200]}) — "
                        f"reintento {intento}/{len(esperas)} en {espera}s"
                    )
                    mgr.actualizar_paso(chunk_id, nombre, error=error, historial=historial)
                    time.sleep(espera)
                    espera_previa = espera
                    continue

                mgr.actualizar_paso(
                    chunk_id, nombre,
                    estado="error", error=error, fin=evento["fin"],
                    duracion_s=evento["duracion_s"],
                    ia=_resumen_ia(trace_dir), historial=historial,
                )
                print(
                    f"[PASOS] ❌ {etiqueta} — {tipo}: {str(e)[:300]} "
                    f"({'reintentable' if reintentable else 'no reintentable'})"
                )
                raise PasoFallido(chunk_id, nombre, error) from e

            estado = "omitido" if resultado.get("omitido") else "ok"
            _cerrar(evento, t0, estado, None, n_antes)
            return mgr.actualizar_paso(
                chunk_id, nombre,
                estado=estado, error=None, fin=evento["fin"],
                duracion_s=evento["duracion_s"], historial=historial,
                salidas=[_relativa(s, base) for s in resultado.get("salidas", []) if s],
                nota=resultado.get("nota"),
                ia=_resumen_ia(trace_dir),
            )
    finally:
        if trace_dir is not None:
            if trace_previo is None:
                os.environ.pop("PIPELINE_TRACE_DIR", None)
            else:
                os.environ["PIPELINE_TRACE_DIR"] = trace_previo
