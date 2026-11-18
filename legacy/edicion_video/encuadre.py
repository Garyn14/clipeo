"""
encuadre.py — CLIP-38: encuadre 9:16 inteligente para fuentes horizontales.

En vez de dejar el video al medio con relleno (blur/barras), recorta una ventana 9:16 que sigue a las caras, con
movimiento suave. Tres piezas:

  detectar_caras(video, inicio_s, duracion_s)  → muestras [(t, [(x, y, w, h), ...])]   (OpenCV, opcional)
  planificar(muestras, ancho, alto)            → keyframes [(t, x_izquierda)] o None (= usar el layout anterior)
  expresion_x(keyframes)                       → expresión de FFmpeg para crop=x='...'

`planificar` y `expresion_x` son puras (testeables sin OpenCV ni video). `encuadrar` junta las tres y nunca lanza:
ante cualquier problema devuelve None y el render sigue con el layout de siempre.
`ENCUADRE_INTELIGENTE=0` lo apaga.
"""

from __future__ import annotations

import os
from statistics import median

PASO_S = 0.5              # una muestra cada medio segundo
ANCHO_DETECCION = 640     # los cuadros se reducen a este ancho para detectar (rápido)
MIN_CON_CARA = 0.5        # menos muestras con cara → respaldo
MAX_SEPARADAS = 0.3       # más muestras con caras que no caben en un recorte → respaldo
VENTANA_MEDIANA = 5       # suavizado
ZONA_MUERTA = 0.06        # no moverse por cambios menores al 6% del ancho de la fuente
VELOCIDAD_MAX = 0.35      # como máximo 35% del ancho de la fuente por segundo


def activado() -> bool:
    return os.environ.get("ENCUADRE_INTELIGENTE", "1").strip() not in ("0", "false", "no")


def ancho_recorte(alto: int) -> int:
    cw = int(alto * 9 / 16)
    return cw - (cw % 2)


# ── Detección (OpenCV) ──────────────────────────────────────

def detectar_caras(video_path, inicio_s: float, duracion_s: float) -> list[tuple[float, list[tuple]]]:
    """Caras por muestra, en píxeles de la fuente y con t relativo al inicio del clip. Requiere OpenCV."""
    import cv2   # opcional: sin OpenCV, encuadrar() devuelve None y se usa el layout anterior

    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(video_path))
    try:
        muestras = []
        t = 0.0
        while t <= duracion_s:
            cap.set(cv2.CAP_PROP_POS_MSEC, (inicio_s + t) * 1000)
            ok, frame = cap.read()
            if not ok:
                break
            alto, ancho = frame.shape[:2]
            escala = ANCHO_DETECCION / ancho if ancho > ANCHO_DETECCION else 1.0
            chico = cv2.resize(frame, (int(ancho * escala), int(alto * escala))) if escala < 1 else frame
            gris = cv2.cvtColor(chico, cv2.COLOR_BGR2GRAY)
            caras = detector.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5,
                                              minSize=(int(chico.shape[0] * 0.08),) * 2)
            muestras.append((round(t, 2), [tuple(int(v / escala) for v in c) for c in caras]))
            t += PASO_S
        return muestras
    finally:
        cap.release()


# ── Plan (puro) ─────────────────────────────────────────────

def _centro_sujeto(caras: list[tuple], cw: int) -> tuple[float | None, bool]:
    """(centro x del sujeto, caben_todas). Sujeto = grupo de caras si caben en el recorte; si no, la más grande."""
    if not caras:
        return None, True
    izq = min(x for x, _, _, _ in caras)
    der = max(x + w for x, _, w, _ in caras)
    if der - izq <= cw * 0.9:
        return (izq + der) / 2, True
    x, _, w, _ = max(caras, key=lambda c: c[2] * c[3])
    return x + w / 2, False


def planificar(muestras: list[tuple[float, list[tuple]]], ancho: int, alto: int) -> list[tuple[float, int]] | None:
    """Keyframes [(t, x_izquierda)] del recorte, o None si conviene el layout anterior."""
    cw = ancho_recorte(alto)
    if not muestras or ancho <= cw:
        return None
    centros, separadas = [], 0
    for t, caras in muestras:
        c, caben = _centro_sujeto(caras, cw)
        centros.append((t, c))
        separadas += 0 if caben else 1
    con_cara = sum(1 for _, c in centros if c is not None)
    if con_cara < MIN_CON_CARA * len(muestras) or separadas > MAX_SEPARADAS * len(muestras):
        return None

    # Huecos sin cara: se mantiene la última posición conocida (o la primera, al inicio)
    primera = next(c for _, c in centros if c is not None)
    rellenos, ultima = [], primera
    for t, c in centros:
        ultima = c if c is not None else ultima
        rellenos.append((t, ultima))

    # Mediana móvil
    mitad = VENTANA_MEDIANA // 2
    suavizados = [
        (t, median(c for _, c in rellenos[max(0, i - mitad): i + mitad + 1]))
        for i, (t, _) in enumerate(rellenos)
    ]

    # Zona muerta + velocidad máxima
    max_x = ancho - cw
    zona, vmax = ZONA_MUERTA * ancho, VELOCIDAD_MAX * ancho
    actual = suavizados[0][1]
    keyframes = [(suavizados[0][0], actual)]
    for (t0, _), (t, objetivo) in zip(suavizados, suavizados[1:]):
        if abs(objetivo - actual) >= zona:
            paso = vmax * (t - t0)
            actual += max(-paso, min(paso, objetivo - actual))
        keyframes.append((t, actual))

    salida = [(t, int(min(max_x, max(0, c - cw / 2)))) for t, c in keyframes]
    # Comprimir sin cambiar la trayectoria: tramos quietos quedan como 2 puntos (inicio y fin)
    compacto = [salida[0]]
    for anterior, punto in zip(salida, salida[1:]):
        if punto[1] != anterior[1]:
            if compacto[-1] != anterior:
                compacto.append(anterior)   # fin del tramo quieto = inicio del movimiento
            compacto.append(punto)
    if compacto[-1] != salida[-1]:
        compacto.append(salida[-1])
    return compacto


# ── Expresión de FFmpeg (pura) ──────────────────────────────

def expresion_x(keyframes: list[tuple[float, int]]) -> str:
    """Interpolación lineal por tramos sobre t, con las comas escapadas para el filtergraph."""
    if len(keyframes) == 1 or all(x == keyframes[0][1] for _, x in keyframes):
        return str(keyframes[0][1])
    expr = str(keyframes[-1][1])
    for (t0, x0), (t1, x1) in reversed(list(zip(keyframes, keyframes[1:]))):
        tramo = str(x0) if x0 == x1 or t1 <= t0 else f"{x0}+({x1 - x0})*(t-{t0})/{round(t1 - t0, 3)}"
        expr = f"if(lt(t\\,{t1})\\,{tramo}\\,{expr})"
    return expr


def filtro_crop(keyframes: list[tuple[float, int]], alto: int) -> str:
    return f"crop=w={ancho_recorte(alto)}:h={alto}:x='{expresion_x(keyframes)}':y=0,scale=1080:1920"


# ── Todo junto ──────────────────────────────────────────────

def encuadrar(video_path, inicio_s: float, duracion_s: float, ancho: int, alto: int) -> str | None:
    """Filtro de crop dinámico para el clip, o None (apagado, fuente vertical, sin OpenCV o sin caras claras)."""
    if not activado() or not ancho or not alto or ancho <= alto:
        return None
    try:
        muestras = detectar_caras(video_path, inicio_s, duracion_s)
    except ImportError:
        print("         Encuadre: OpenCV no está instalado → layout anterior")
        return None
    except Exception as e:   # noqa: BLE001 — el encuadre nunca rompe un clip
        print(f"         Encuadre: falló la detección ({type(e).__name__}: {e}) → layout anterior")
        return None
    plan = planificar(muestras, ancho, alto)
    con_cara = sum(1 for _, c in muestras if c)
    if plan is None:
        print(f"         Encuadre: caras en {con_cara}/{len(muestras)} muestras, no hay un recorte claro → layout anterior")
        return None
    print(f"         Encuadre: siguiendo caras ({con_cara}/{len(muestras)} muestras, {len(plan)} puntos de cámara)")
    return filtro_crop(plan, alto)
