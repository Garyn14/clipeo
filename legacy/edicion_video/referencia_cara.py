"""
referencia_cara.py — CLIP-40: arma las caras de referencia de una persona a partir de videos de su propio canal.

    python -m edicion_video.referencia_cara fritz ../stream_data/20260607_172241/stream_completo.mp4 [...] [--muestras 40]

En un stream del canal de la persona, la cara grande que más se repite es la suya: se toman cuadros repartidos en cada
video, se calculan los embeddings SFace de las caras grandes y se queda el grupo más numeroso de caras parecidas.
Escribe edicion_video/assets/caras/<slug del nombre>.npy (matriz N×128 normalizada). Es un dato biométrico: queda
fuera del repo (.gitignore). Requiere OpenCV y los modelos YuNet y SFace (ver assets/modelos/README.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from edicion_video import encuadre

CARA_MIN = 0.12          # solo caras grandes (alto ≥ 12% del cuadro): primeros planos del dueño del canal
MAX_REFERENCIAS = 30


def _embeddings_de_video(cv2, np, yunet, sface, video: Path, n: int) -> list:
    cap = cv2.VideoCapture(str(video))
    try:
        total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        duracion = total / fps if total else 0
        salida = []
        for i in range(n):
            cap.set(cv2.CAP_PROP_POS_MSEC, duracion * (i + 0.5) / n * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            alto, ancho = frame.shape[:2]
            escala = 960 / ancho if ancho > 960 else 1.0
            img = cv2.resize(frame, (int(ancho * escala), int(alto * escala))) if escala < 1 else frame
            yunet.setInputSize((img.shape[1], img.shape[0]))
            _, caras = yunet.detect(img)
            for fila in caras if caras is not None else []:
                if fila[3] >= CARA_MIN * img.shape[0]:
                    f = sface.feature(sface.alignCrop(img, fila)).flatten()
                    salida.append(f / (np.linalg.norm(f) or 1))
        return salida
    finally:
        cap.release()


def grupo_mayor(embeddings, umbral: float = encuadre.UMBRAL_SFACE):
    """El grupo más numeroso de caras parecidas entre sí (la persona que más aparece). Puro: recibe una matriz."""
    import numpy as np
    if len(embeddings) == 0:
        return embeddings
    sim = embeddings @ embeddings.T
    vecinos = (sim >= umbral).sum(axis=1)
    centro = int(np.argmax(vecinos))
    grupo = embeddings[sim[centro] >= umbral]
    orden = np.argsort(-(grupo @ embeddings[centro]))
    return grupo[orden[:MAX_REFERENCIAS]]


def main() -> None:
    ap = argparse.ArgumentParser(description="CLIP-40: caras de referencia de una persona desde su propio canal")
    ap.add_argument("entidad", help="id de contexto/entidades/ (ej. fritz) o nombre")
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--muestras", type=int, default=40, help="cuadros por video")
    args = ap.parse_args()

    import cv2
    import numpy as np
    from core.fuente import nombre_sobre

    if not encuadre.MODELO_SFACE.exists():
        sys.exit(f"Falta el modelo SFace: {encuadre.MODELO_SFACE} (ver assets/modelos/README.md)")
    yunet = cv2.FaceDetectorYN.create(str(encuadre.MODELO_YUNET), "", (320, 320), 0.7)
    sface = cv2.FaceRecognizerSF.create(str(encuadre.MODELO_SFACE), "")

    todos = []
    for v in args.videos:
        caras = _embeddings_de_video(cv2, np, yunet, sface, v, args.muestras)
        print(f"[REFERENCIA] {v}: {len(caras)} cara(s) grande(s)")
        todos += caras
    if not todos:
        sys.exit("No se encontraron caras grandes en los videos")
    refs = grupo_mayor(np.array(todos))
    nombre = nombre_sobre(args.entidad)
    destino = encuadre.DIR_CARAS / f"{encuadre.slug(nombre)}.npy"
    destino.parent.mkdir(parents=True, exist_ok=True)
    np.save(destino, refs)
    print(f"[REFERENCIA] {nombre}: {len(refs)} referencia(s) de {len(todos)} caras → {destino}")


if __name__ == "__main__":
    main()
