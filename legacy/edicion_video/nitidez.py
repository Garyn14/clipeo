"""
nitidez.py — CLIP-41: el clip no arranca en un cuadro movido (el primer cuadro es la miniatura).

Mide la nitidez (varianza del laplaciano) del cuadro inicial y del que está 1 s después (el corte trabaja en segundos
enteros); si el inicial vale menos de la mitad que el siguiente, el corte arranca 1 s después. Sin OpenCV o ante
cualquier error, no corre nada (devuelve 0).
"""

from __future__ import annotations

VENTANA_S = 1.0
PASOS = 2   # t = 0 y t = 1 s
UMBRAL = 0.5     # el primer cuadro debe tener al menos la mitad de la nitidez del mejor


def elegir_desfase(nitideces: list[tuple[float, float]]) -> int:
    """[(t, nitidez)] → segundos enteros a correr el inicio (0 si el primero ya es suficientemente nítido). Puro."""
    if not nitideces:
        return 0
    t_mejor, mejor = max(nitideces, key=lambda tn: tn[1])
    primero = nitideces[0][1]
    return int(t_mejor) if mejor > 0 and primero < UMBRAL * mejor else 0


def medir(video_path, inicio_s: float) -> list[tuple[float, float]]:
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    try:
        salida = []
        for i in range(PASOS):
            t = round(VENTANA_S * i / (PASOS - 1), 2)
            cap.set(cv2.CAP_PROP_POS_MSEC, (inicio_s + t) * 1000)
            ok, frame = cap.read()
            if not ok:
                break
            gris = cv2.cvtColor(cv2.resize(frame, (640, int(640 * frame.shape[0] / frame.shape[1]))),
                                cv2.COLOR_BGR2GRAY)
            salida.append((t, float(cv2.Laplacian(gris, cv2.CV_64F).var())))
        return salida
    finally:
        cap.release()


def desfase_inicio(video_path, inicio_s: float) -> int:
    try:
        return elegir_desfase(medir(video_path, inicio_s))
    except Exception:   # noqa: BLE001 — nunca rompe un clip (sin OpenCV, video ilegible...)
        return 0
