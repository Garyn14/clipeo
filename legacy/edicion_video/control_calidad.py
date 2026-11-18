"""
control_calidad.py — CLIP-51/52 (Q4): revisa cada clip cortado antes de que llegue a la revisión del operador.

Detecta defectos técnicos con FFmpeg (sin IA, sin costo) y los deja en `clips/<id>.json` → `control_calidad`, que la
revisión web muestra como aviso. No descarta nada: el operador decide.

  - duracion_corta   el video salió más corto que el rango pedido (corte truncado)
  - negro            cuadros negros > 1 s, o el clip arranca en negro (miniatura negra)
  - congelado        imagen congelada ≥ 2 s
  - mudo / silencio  sin audio útil (volumen medio < -45 dB) o silencios ≥ 3 s
  - saturado         ≥ 1% de las muestras en 0 dB (recorte sostenido; un pico suelto no cuenta)
  - acercamiento     el encuadre amplía la fuente más de 2× (pérdida de nitidez y de contexto: demo S9, clip del guardia)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

NEGRO_MIN_S = 1.0
INICIO_NEGRO_S = 0.3
CONGELADO_MIN_S = 2.0
SILENCIO_MIN_S = 3.0
MUDO_DB = -45.0
SATURADO_FRACCION = 0.01   # ≥ 1% de las muestras en 0 dB = recorte sostenido (un pico suelto no se oye)
ESCALA_MAX = 2.0
TOLERANCIA_DURACION_S = 2.0

_NUM = r"(-?[\d.]+)"


def parsear(salida: str) -> dict:
    """Salida de ffmpeg (blackdetect, freezedetect, volumedetect, silencedetect) → mediciones. Puro."""
    negros = [(float(a), float(b)) for a, b in re.findall(rf"black_start:{_NUM} black_end:{_NUM}", salida)]
    congelados = [float(d) for d in re.findall(rf"freeze_duration: {_NUM}", salida)]
    silencios = [float(d) for d in re.findall(rf"silence_duration: {_NUM}", salida)]
    media = re.search(rf"mean_volume: {_NUM} dB", salida)
    maximo = re.search(rf"max_volume: {_NUM} dB", salida)
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", salida)
    muestras = [int(x) for x in re.findall(r"n_samples: (\d+)", salida) if int(x) > 0]
    en_cero = re.search(r"histogram_0db: (\d+)", salida)
    return {
        "negros": negros, "congelados": congelados, "silencios": silencios,
        "volumen_medio": float(media.group(1)) if media else None,
        "volumen_max": float(maximo.group(1)) if maximo else None,
        "fraccion_0db": (int(en_cero.group(1)) / muestras[-1]) if en_cero and muestras else 0.0,
        "duracion": (int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))) if dur else None,
    }


def hallazgos(m: dict, duracion_esperada: float | None = None, escala_encuadre: float | None = None) -> list[dict]:
    """Mediciones → [{codigo, detalle}] para el operador. Puro."""
    salida = []

    def aviso(codigo, detalle):
        salida.append({"codigo": codigo, "detalle": detalle})

    if duracion_esperada and m.get("duracion") is not None and m["duracion"] < duracion_esperada - TOLERANCIA_DURACION_S:
        aviso("duracion_corta", f"dura {m['duracion']:.0f} s de {duracion_esperada:.0f} s pedidos")
    total_negro = sum(b - a for a, b in m.get("negros", []))
    if any(a <= INICIO_NEGRO_S for a, _ in m.get("negros", [])):
        aviso("negro", "arranca en negro (la miniatura sale negra)")
    elif total_negro >= NEGRO_MIN_S:
        aviso("negro", f"{total_negro:.1f} s de cuadros negros")
    congelado = max(m.get("congelados") or [0])
    if congelado >= CONGELADO_MIN_S:
        aviso("congelado", f"imagen congelada {congelado:.1f} s")
    if m.get("volumen_medio") is not None and m["volumen_medio"] < MUDO_DB:
        aviso("mudo", f"casi sin audio (volumen medio {m['volumen_medio']:.0f} dB)")
    else:
        silencio = max(m.get("silencios") or [0])
        if silencio >= SILENCIO_MIN_S:
            aviso("silencio", f"silencio de {silencio:.1f} s")
    if (m.get("fraccion_0db") or 0) >= SATURADO_FRACCION:
        aviso("saturado", f"audio recortado en el {m['fraccion_0db']:.0%} de las muestras (suena distorsionado)")
    if escala_encuadre and escala_encuadre > ESCALA_MAX:
        aviso("acercamiento", f"el encuadre amplía {escala_encuadre:.1f}× la fuente (se pierde nitidez y contexto)")
    return salida


def medir(video: Path) -> dict:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(video),
         "-vf", "blackdetect=d=0.2:pix_th=0.10,freezedetect=n=0.003:d=2",
         "-af", f"volumedetect,silencedetect=n={MUDO_DB}dB:d={SILENCIO_MIN_S}",
         "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    return parsear(r.stderr)


def revisar(video: Path, duracion_esperada: float | None = None, escala_encuadre: float | None = None) -> list[dict]:
    """Hallazgos del clip, o [] si no se pudo medir (el control nunca rompe un corte)."""
    try:
        return hallazgos(medir(video), duracion_esperada, escala_encuadre)
    except Exception:   # noqa: BLE001
        return []
