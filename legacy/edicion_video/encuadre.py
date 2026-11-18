"""
encuadre.py — CLIP-38: encuadre inteligente para fuentes horizontales.

En vez de dejar el video 16:9 al medio con mucho relleno, recorta una ventana **4:5** que sigue a las caras y la
muestra en una caja de 1080×1350 (70% de la pantalla) sobre fondo blur. Solo en algunos tramos — un primer plano
claro y estable — se acerca un poco más (zoom suave, ver `secciones_zoom`). Decisión del operador (demo S6): el
recorte 9:16 completo exageraba el acercamiento; el zoom va solo donde suma.

  detectar_caras(video, inicio_s, duracion_s)  → muestras [(t, [(x, y, w, h), ...])]   (OpenCV, opcional)
  planificar(muestras, ancho, alto)            → keyframes [(t, x_izquierda)] o None (= usar el layout anterior)
  secciones_zoom(muestras, alto)               → tramos [(t_ini, t_fin)] con acercamiento
  filtro(keyframes, secciones, alto)           → filtro de FFmpeg (fondo blur + caja con la ventana que sigue)

Todo salvo `detectar_caras` es puro (testeable sin OpenCV ni video). `encuadrar` junta las piezas y nunca lanza:
ante cualquier problema devuelve None y el render sigue con el layout de siempre.
`ENCUADRE_INTELIGENTE=0` lo apaga.
"""

from __future__ import annotations

import os
from pathlib import Path
from statistics import median

# Modelo YuNet (OpenCV Zoo, licencia MIT): OpenCV 5 ya no trae el detector Haar. Si el archivo no está, se usa Haar
# (OpenCV 4.x); si tampoco hay Haar, el encuadre se desactiva solo.
MODELO_YUNET = Path(__file__).resolve().parent / "assets" / "modelos" / "face_detection_yunet_2023mar.onnx"
# CLIP-40: SFace reconoce a la persona del clip (37 MB, fuera del repo: ver assets/modelos/README.md). Las caras de
# referencia (datos biométricos) viven en assets/caras/<slug>.npy, también fuera del repo.
MODELO_SFACE = MODELO_YUNET.parent / "face_recognition_sface_2021dec.onnx"
DIR_CARAS = MODELO_YUNET.parent.parent / "caras"
UMBRAL_SFACE = 0.363      # similitud coseno de "misma persona" recomendada por OpenCV para SFace

PASO_S = 0.5              # una muestra cada medio segundo
ANCHO_DETECCION = 640     # los cuadros se reducen a este ancho para detectar (rápido)
MIN_CON_CARA = 0.5        # menos muestras con cara → respaldo
MAX_SEPARADAS = 0.3       # más muestras con caras que no caben en un recorte → respaldo
VENTANA_MEDIANA = 5       # suavizado
ZONA_MUERTA = 0.06        # no moverse por cambios menores al 6% del ancho de la fuente
VELOCIDAD_MAX = 0.35      # como máximo 35% del ancho de la fuente por segundo
SUPERPUESTA_ALTO = 0.10   # cara fija y chica (alto < 10% del cuadro) en ≥ 60% de las muestras = gráfico de TV
SUPERPUESTA_FRECUENCIA = 0.6
SUPERPUESTA_TOLERANCIA = 0.02   # "misma posición": centro a menos de 2% del ancho
MARGEN_RECUADRO = 2.5     # CLIP-42: el recuadro de TV mide ~2,5 veces el ancho de la cara a cada lado


def activado() -> bool:
    return os.environ.get("ENCUADRE_INTELIGENTE", "1").strip() not in ("0", "false", "no")


PROPORCION = 4 / 5        # ventana base: 4:5 (ancho/alto)
CAJA_ANCHO, CAJA_ALTO = 1080, 1350          # caja de video en el cuadro 1080×1920
BARRA = (1920 - CAJA_ALTO) // 2             # 285 px de fondo blur arriba y abajo (el título va arriba)

ZOOM = 1.35               # acercamiento de los tramos de primer plano
ZOOM_RAMPA_S = 0.5        # entrada y salida suaves
ZOOM_CARA_MIN = 0.22      # primer plano: alto de la cara ≥ 22% del alto útil
ZOOM_MIN_S = 3.0          # el primer plano debe durar al menos 3 s
ZOOM_MAX_FRACCION = 0.4   # como máximo 40% del clip acercado ("solo en algunas secciones")


def ancho_recorte(alto: int) -> int:
    cw = int(alto * PROPORCION)
    return cw - (cw % 2)


# ── Detección (OpenCV) ──────────────────────────────────────

def _detector(cv2):
    """Función imagen → [((x, y, w, h), fila_yunet | None)]: YuNet si está el modelo, si no Haar (OpenCV 4.x)."""
    if MODELO_YUNET.exists() and hasattr(cv2, "FaceDetectorYN"):
        yunet = cv2.FaceDetectorYN.create(str(MODELO_YUNET), "", (320, 320), 0.7)

        def detectar(img):
            yunet.setInputSize((img.shape[1], img.shape[0]))
            _, caras = yunet.detect(img)
            return [] if caras is None else [(tuple(int(v) for v in c[:4]), c) for c in caras]
        return detectar
    if hasattr(cv2, "CascadeClassifier"):
        haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

        def detectar(img):
            gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            return [(tuple(c), None) for c in haar.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=5,
                                                                     minSize=(int(img.shape[0] * 0.08),) * 2)]
        return detectar
    raise ImportError(f"OpenCV {cv2.__version__} sin detector de caras: falta el modelo YuNet en {MODELO_YUNET}")


def slug(nombre: str) -> str:
    import unicodedata
    plano = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    return "_".join("".join(ch if ch.isalnum() else " " for ch in plano).split())


def cargar_referencias(persona: str | None):
    """Embeddings SFace normalizados de la persona (matriz N×128), o None si no hay referencia o modelo."""
    if not persona or not MODELO_SFACE.exists():
        return None
    ruta = DIR_CARAS / f"{slug(persona)}.npy"
    if not ruta.exists():
        return None
    import numpy as np
    return np.load(ruta)


def _reconocedor(cv2, referencias):
    """Función (imagen, fila_yunet) → es_sujeto, o None si no se puede reconocer."""
    if referencias is None or not hasattr(cv2, "FaceRecognizerSF"):
        return None
    import numpy as np
    sface = cv2.FaceRecognizerSF.create(str(MODELO_SFACE), "")

    def es_sujeto(img, fila) -> bool:
        if fila is None:
            return False
        f = sface.feature(sface.alignCrop(img, fila)).flatten()
        f = f / (np.linalg.norm(f) or 1)
        return bool(float((referencias @ f).max()) >= UMBRAL_SFACE)
    return es_sujeto


def detectar_caras(video_path, inicio_s: float, duracion_s: float, referencias=None) -> list[tuple[float, list[tuple]]]:
    """Caras por muestra, en píxeles de la fuente y con t relativo al inicio del clip: (x, y, w, h) o, con
    `referencias` (CLIP-40), (x, y, w, h, es_sujeto). Requiere OpenCV."""
    import cv2   # opcional: sin OpenCV, encuadrar() devuelve None y se usa el layout anterior

    detector = _detector(cv2)
    reconocer = _reconocedor(cv2, referencias)
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
            caras = []
            for caja, fila in detector(chico):
                c = tuple(int(v / escala) for v in caja)
                caras.append(c + (reconocer(chico, fila),) if reconocer else c)
            muestras.append((round(t, 2), caras))
            t += PASO_S
        return muestras
    finally:
        cap.release()


# ── Plan (puro) ─────────────────────────────────────────────

def _centro_sujeto(caras: list[tuple], cw: int) -> tuple[float | None, bool]:
    """(centro x del sujeto, caben_todas). Sujeto = grupo de caras si caben en el recorte; si no, la más grande.
    CLIP-40: si alguna cara está reconocida como la persona del clip, manda ella (con las demás solo si caben)."""
    if not caras:
        return None, True
    reconocidas = [c for c in caras if len(c) > 4 and c[4]]
    if reconocidas:
        x, _, w, _ = max(reconocidas, key=lambda c: c[2] * c[3])[:4]
        izq = min(c[0] for c in caras)
        der = max(c[0] + c[2] for c in caras)
        return ((izq + der) / 2 if der - izq <= cw * 0.9 else x + w / 2), True
    caras = [c[:4] for c in caras]
    if len(caras) == 1:   # un primer plano, aunque sea más ancho que el recorte, se centra igual
        x, _, w, _ = caras[0]
        return x + w / 2, True
    izq = min(x for x, _, _, _ in caras)
    der = max(x + w for x, _, w, _ in caras)
    if der - izq <= cw * 0.9:
        return (izq + der) / 2, True
    x, _, w, _ = max(caras, key=lambda c: c[2] * c[3])
    return x + w / 2, False


def quitar_superpuestas(muestras: list[tuple[float, list[tuple]]], ancho: int, alto: int):
    """Quita caras de gráficos fijos de TV (intérprete de señas, recuadro del conductor): chicas y en la misma
    posición en casi todo el clip. Una persona real, aunque esté quieta, se mueve algo o es más grande."""
    def reconocida(c):   # la persona del clip (CLIP-40) nunca es un gráfico, aunque esté quieta y chica
        return len(c) > 4 and c[4]

    chicas = [(c[0] + c[2] / 2, c[1] + c[3] / 2, c[2]) for _, caras in muestras for c in caras
              if c[3] < SUPERPUESTA_ALTO * alto and not reconocida(c)]
    tol = SUPERPUESTA_TOLERANCIA * ancho
    fijas = []
    for cx, cy, ancho_cara in chicas:
        if any(abs(cx - fx) < tol and abs(cy - fy) < tol for fx, fy, _ in fijas):
            continue
        presentes = sum(
            1 for _, caras in muestras
            if any(abs(c[0] + c[2] / 2 - cx) < tol and abs(c[1] + c[3] / 2 - cy) < tol
                   and c[3] < SUPERPUESTA_ALTO * alto for c in caras)
        )
        if presentes >= SUPERPUESTA_FRECUENCIA * len(muestras):
            fijas.append((cx, cy, ancho_cara))

    def es_fija(c):
        x, y, w, h = c[:4]
        return not reconocida(c) and h < SUPERPUESTA_ALTO * alto and any(abs(x + w / 2 - fx) < tol and abs(y + h / 2 - fy) < tol
                                                   for fx, fy, _ in fijas)
    return [(t, [c for c in caras if not es_fija(c)]) for t, caras in muestras], fijas


def planificar(muestras: list[tuple[float, list[tuple]]], ancho: int, alto: int) -> list[tuple[float, int]] | None:
    """Keyframes [(t, x_izquierda)] del recorte, o None si conviene el layout anterior."""
    cw = ancho_recorte(alto)
    if not muestras or ancho <= cw:
        return None
    muestras, fijas = quitar_superpuestas(muestras, ancho, alto)
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

    # CLIP-42: la ventana deja fuera los recuadros fijos de TV (margen MARGEN_RECUADRO × ancho de la cara), salvo
    # que eso saque al sujeto del recorte
    min_x, max_xr = 0, max_x
    for fx, fy, fw in fijas:
        if fy >= alto:
            continue
        if fx > ancho / 2:
            max_xr = min(max_xr, max(0, int(fx - MARGEN_RECUADRO * fw - cw)))
        else:
            min_x = max(min_x, min(max_x, int(fx + MARGEN_RECUADRO * fw)))

    def ubicar(c):
        x = min(max_x, max(0, c - cw / 2))
        x_limpio = min(max_xr, max(min_x, x))
        return int(x_limpio if x_limpio <= c <= x_limpio + cw else x)

    salida = [(t, ubicar(c)) for t, c in keyframes]
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


def secciones_zoom(muestras: list[tuple[float, list[tuple]]], alto: int) -> list[tuple[float, float]]:
    """Tramos de primer plano claro (una sola cara, grande, ≥ ZOOM_MIN_S) donde conviene acercarse. Como máximo
    ZOOM_MAX_FRACCION del clip, eligiendo los tramos más largos. `alto` = alto útil."""
    if not muestras:
        return []
    tramos, inicio = [], None
    for i, (t, caras) in enumerate(muestras):
        primer_plano = (len(caras) == 1 and caras[0][3] >= ZOOM_CARA_MIN * alto
                        and (len(caras[0]) < 5 or caras[0][4]))   # CLIP-40: con referencia, solo del sujeto
        if primer_plano and inicio is None:
            inicio = t
        fin_tramo = (not primer_plano or i == len(muestras) - 1) and inicio is not None
        if fin_tramo:
            fin = t if not primer_plano else t + PASO_S
            if fin - inicio >= ZOOM_MIN_S:
                tramos.append((inicio, fin))
            inicio = None
    duracion = muestras[-1][0] + PASO_S
    elegidos, total = [], 0.0
    for a, b in sorted(tramos, key=lambda tr: tr[0] - tr[1]):     # más largos primero
        if total + (b - a) <= ZOOM_MAX_FRACCION * duracion:
            elegidos.append((a, b))
            total += b - a
    return sorted(elegidos)


def expresion_zoom(secciones: list[tuple[float, float]]) -> str:
    """z(t): 1 fuera de los tramos, ZOOM dentro, con rampas de ZOOM_RAMPA_S (comas escapadas)."""
    if not secciones:
        return "1"
    d, r = ZOOM - 1, ZOOM_RAMPA_S
    expr = "1"
    for a, b in reversed(secciones):
        expr = (f"if(lt(t\\,{a})\\,{expr}\\,"
                f"if(lt(t\\,{a + r:.2f})\\,1+{d:.2f}*(t-{a})/{r}\\,"
                f"if(lt(t\\,{b - r:.2f})\\,{ZOOM}\\,"
                f"if(lt(t\\,{b})\\,{ZOOM}-{d:.2f}*(t-{b - r:.2f})/{r}\\,{expr}))))")
    return expr


def filtro(keyframes: list[tuple[float, int]], secciones: list[tuple[float, float]], alto: int) -> str:
    """Fondo blur de todo el cuadro + caja 1080×1350 con la ventana 4:5 que sigue al sujeto (y se acerca en los
    tramos de `secciones`). `alto` es el alto útil desde y=0 (menor que el de la fuente si se excluye el zócalo)."""
    cw = ancho_recorte(alto)
    z = expresion_zoom(secciones)
    caja = f"crop=w={cw}:h={alto}:x='{expresion_x(keyframes)}':y=0,scale={CAJA_ANCHO}:{CAJA_ALTO}"
    if secciones:
        caja += (f",scale=w='trunc({CAJA_ANCHO}*({z})/2)*2':h='trunc({CAJA_ALTO}*({z})/2)*2':eval=frame,"
                 f"crop={CAJA_ANCHO}:{CAJA_ALTO}")
    return (
        "split=2[_encbg][_encfg];"
        # El fondo también sale del alto útil: sin la franja excluida no se ve el zócalo difuminado
        f"[_encbg]crop=iw:{alto}:0:0,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=20[_encbg2];"
        f"[_encfg]{caja}[_encfg2];"
        "[_encbg2][_encfg2]overlay=(W-w)/2:(H-h)/2"
    )


# Medios (TV/prensa): la franja de abajo es del noticiero (zócalo con el titular, reloj, intérprete de señas). En
# la demo del S6 el zócalo de Latina empezaba en ~83% del alto; se excluye el 20% inferior (algo más de zoom).
FRANJA_MEDIOS = 0.20


def alto_util(alto: int, franja_inferior: float = 0.0) -> int:
    util = int(alto * (1 - franja_inferior))
    return util - (util % 2)


# ── Todo junto ──────────────────────────────────────────────

def encuadrar(video_path, inicio_s: float, duracion_s: float, ancho: int, alto: int,
              franja_inferior: float = 0.0, persona: str | None = None) -> str | None:
    """Filtro de crop dinámico para el clip, o None (apagado, fuente vertical, sin OpenCV o sin caras claras).
    `franja_inferior` (0–1): parte de abajo del cuadro que queda fuera del recorte (zócalo de TV en medios).
    `persona` (CLIP-40): de quién trata el clip; si tiene caras de referencia, el encuadre la sigue a ella."""
    if not activado() or not ancho or not alto or ancho <= alto:
        return None
    alto_total, alto = alto, alto_util(alto, franja_inferior)
    try:
        referencias = cargar_referencias(persona)
        muestras = (detectar_caras(video_path, inicio_s, duracion_s, referencias) if referencias is not None
                    else detectar_caras(video_path, inicio_s, duracion_s))
    except ImportError as e:
        print(f"         Encuadre: sin detector de caras ({e}) → layout anterior")
        return None
    except Exception as e:   # noqa: BLE001 — el encuadre nunca rompe un clip
        print(f"         Encuadre: falló la detección ({type(e).__name__}: {e}) → layout anterior")
        return None
    if alto < alto_total:   # caras dentro de la franja excluida (intérprete, recuadros del zócalo) no cuentan
        muestras = [(t, [c for c in caras if c[1] + c[3] / 2 < alto]) for t, caras in muestras]
    plan = planificar(muestras, ancho, alto)
    con_cara = sum(1 for _, c in muestras if c)
    if plan is None:
        print(f"         Encuadre: caras en {con_cara}/{len(muestras)} muestras, no hay un recorte claro → layout anterior")
        return None
    secciones = secciones_zoom(quitar_superpuestas(muestras, ancho, alto)[0], alto)
    acercado = sum(b - a for a, b in secciones)
    reconocida = sum(1 for _, caras in muestras if any(len(c) > 4 and c[4] for c in caras))
    if referencias is not None:
        print(f"         Encuadre: {persona} reconocido en {reconocida}/{len(muestras)} muestras")
    print(f"         Encuadre: 4:5 siguiendo caras ({con_cara}/{len(muestras)} muestras, {len(plan)} puntos de cámara)"
          f" · acercamiento en {len(secciones)} tramo(s), {acercado:.0f}s")
    return filtro(plan, secciones, alto)
