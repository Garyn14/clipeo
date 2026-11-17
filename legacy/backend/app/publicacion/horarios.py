"""
horarios.py — Cuándo toca enviar. Regla pura: sin base de datos ni red, testeable con
fechas fijas.

En cada revisión, por cuenta:
  1. slot = último horario que ya pasó (puede ser el de las 20:00 de ayer).
  2. Ese slot está vigente hasta el siguiente horario o hasta el inicio del silencio
     nocturno, lo que llegue antes. Fuera de esa ventana no se hace nada: los horarios
     perdidos (PC apagada) no se recuperan, la cola solo se corre.
  3. Si el slot ya está ocupado por una publicación → nada.
  4. Si no pasaron SEPARACION_MINIMA desde la revisión del último envío → esperar (si la
     ventana todavía da, una revisión siguiente lo envía).
  5. Si no, se envía el primero de la cola cubriendo ese slot.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Lima")

HORARIOS_DEFAULT = "8,12,16,20"
SILENCIO_DESDE_HORA = 22            # de 22:00 hasta el primer horario del día no se envía
SEPARACION_MINIMA = timedelta(hours=2)
REVISION_CADA_MIN = 10              # el motor revisa alineado al reloj: xx:00, xx:10, xx:20...


@dataclass
class Decision:
    enviar: bool
    slot: datetime | None
    motivo: str


def ahora() -> datetime:
    return datetime.now(ZONA)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def clave_slot(slot: datetime) -> str:
    return slot.isoformat(timespec="minutes")


def parsear_horarios(texto: str) -> list[int]:
    horas = sorted({int(h) for h in texto.split(",") if h.strip()})
    if not horas or any(h < 0 or h >= SILENCIO_DESDE_HORA for h in horas):
        raise ValueError(f"Horarios inválidos: {texto!r} (horas enteras antes de las {SILENCIO_DESDE_HORA})")
    return horas


def _slots_alrededor(momento: datetime, horas: list[int]) -> list[datetime]:
    """Horarios de ayer, hoy y mañana, en orden."""
    base = momento.astimezone(ZONA).replace(minute=0, second=0, microsecond=0)
    return [
        (base + timedelta(days=d)).replace(hour=h)
        for d in (-1, 0, 1)
        for h in horas
    ]


def ultimo_slot(momento: datetime, horas: list[int]) -> datetime:
    return [s for s in _slots_alrededor(momento, horas) if s <= momento][-1]


def proximo_slot(momento: datetime, horas: list[int]) -> datetime:
    return [s for s in _slots_alrededor(momento, horas) if s > momento][0]


def fin_ventana(slot: datetime, horas: list[int]) -> datetime:
    siguiente = proximo_slot(slot, horas)
    silencio = slot.replace(hour=SILENCIO_DESDE_HORA)
    return min(siguiente, silencio)


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def decidir(
    momento: datetime,
    horarios: str,
    slots_ocupados: set[str],
    ultimo_envio: datetime | None,
    hay_cola: bool,
) -> Decision:
    horas = parsear_horarios(horarios)
    slot = ultimo_slot(momento, horas)

    if momento >= fin_ventana(slot, horas):
        prox = proximo_slot(momento, horas)
        if momento.hour >= SILENCIO_DESDE_HORA or momento.hour < horas[0]:
            return Decision(False, None, f"horario de silencio — próximo envío a las {_hhmm(prox)}")
        return Decision(False, None, f"el horario de las {_hhmm(slot)} ya pasó sin envío — próximo a las {_hhmm(prox)}")

    if clave_slot(slot) in slots_ocupados:
        return Decision(False, None, f"horario de las {_hhmm(slot)} ya cubierto")

    if not hay_cola:
        return Decision(False, None, f"toca el horario de las {_hhmm(slot)} pero la cola está vacía")

    if ultimo_envio is not None and momento < habilitado_desde(ultimo_envio):
        return Decision(
            False, None,
            f"horario de las {_hhmm(slot)} pendiente: el último envío fue a las {_hhmm(ultimo_envio)}, "
            f"sale en la revisión de las {_hhmm(revision_desde(habilitado_desde(ultimo_envio)))}",
        )

    return Decision(True, slot, f"toca el horario de las {_hhmm(slot)}")


# ── Revisiones del reloj y estimación ────────────────────────

def _en_grilla(t: datetime) -> bool:
    return t.second == 0 and t.microsecond == 0 and t.minute % REVISION_CADA_MIN == 0


def proxima_revision(momento: datetime) -> datetime:
    """Próxima revisión del reloj estrictamente posterior a `momento`."""
    base = momento.replace(second=0, microsecond=0)
    base -= timedelta(minutes=base.minute % REVISION_CADA_MIN)
    return base + timedelta(minutes=REVISION_CADA_MIN)


def revision_desde(t: datetime) -> datetime:
    """Primera revisión del reloj en `t` o después."""
    return t if _en_grilla(t) else proxima_revision(t)


def piso_grilla(t: datetime) -> datetime:
    """La revisión del reloj en la que cayó `t` (un envío queda registrado segundos después)."""
    base = t.replace(second=0, microsecond=0)
    return base - timedelta(minutes=base.minute % REVISION_CADA_MIN)


def habilitado_desde(ultimo_envio: datetime) -> datetime:
    """Desde cuándo se puede volver a enviar: SEPARACION_MINIMA contada desde la revisión del último envío."""
    return piso_grilla(ultimo_envio) + SEPARACION_MINIMA


def estimar(
    momento: datetime,
    horarios: str,
    slots_ocupados: set[str],
    ultimo_envio: datetime | None,
    n: int,
    disponible_desde: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    """
    Para los `n` primeros de la cola, en orden: (hora en que sale, horario que cubre).
    Simula las mismas reglas que decidir(), con el motor revisando en la grilla del reloj
    (REVISION_CADA_MIN). Supone backend prendido y envíos sin error.
    """
    horas = parsear_horarios(horarios)
    ocupados = set(slots_ocupados)
    resultado: list[tuple[datetime, datetime]] = []
    slot = ultimo_slot(momento, horas)
    for _ in range(len(horas) * 400):          # tope de seguridad (~400 días)
        if len(resultado) >= n:
            break
        fin = fin_ventana(slot, horas)
        if clave_slot(slot) not in ocupados:
            candidato = max(t for t in (slot, momento, disponible_desde,
                                        habilitado_desde(ultimo_envio) if ultimo_envio else None) if t)
            sale = revision_desde(candidato)
            if sale < fin:
                resultado.append((sale, slot))
                ocupados.add(clave_slot(slot))
                ultimo_envio = sale
        slot = proximo_slot(slot, horas)
    return resultado
