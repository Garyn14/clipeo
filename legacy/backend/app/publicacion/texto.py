"""
texto.py — El texto de cada publicación, armado del copy que escribió el Agente 3
(`publicacion.<plataforma>` del clip; el "hashtags" general mezcla a todos los vendedores).

TikTok: el endpoint de bandeja no acepta texto (solo el video), así que la descripción y
los # se muestran en el panel para pegar al activar el borrador.
YouTube: título, descripción y tags van por la API con el video (metadatos_youtube).
"""

import re

TITULO_MAX = 100          # caracteres (límite de YouTube)
DESCRIPCION_MAX = 5000    # bytes
TAGS_MAX = 500            # caracteres sumando todos los tags


def _ya_esta(tag: str, texto: str) -> bool:
    # "#fyp" no cuenta como presente dentro de "#fypage"
    return re.search(re.escape(tag) + r"(?!\w)", texto, re.IGNORECASE) is not None


def _con_hashtags(descripcion: str | None, hashtags: list | None) -> str:
    """La descripción + los hashtags de la lista que no estén ya escritos en ella. El crédito "Fuente: …" (medios,
    R-01) va siempre al final, después de los hashtags (antes quedaba en medio: "… Fuente: X #parati")."""
    lineas = (descripcion or "").strip().splitlines()
    creditos = [l.strip() for l in lineas if l.strip().startswith("Fuente:")]
    texto = "\n".join(l for l in lineas if not l.strip().startswith("Fuente:")).strip()
    for tag in hashtags or []:
        tag = (tag or "").strip()
        if tag and not _ya_esta(tag, texto):
            texto = f"{texto} {tag}".strip()
    return "\n\n".join(x for x in [texto, *creditos] if x)


def texto_tiktok(clip: dict) -> str | None:
    """Descripción de TikTok + los hashtags de la lista que no estén ya escritos en ella."""
    tiktok = ((clip or {}).get("publicacion") or {}).get("tiktok") or {}
    return _con_hashtags(tiktok.get("descripcion"), tiktok.get("hashtags")) or None


def _sin_angulos(texto: str) -> str:
    # YouTube rechaza "<" y ">" en título y descripción
    return texto.replace("<", "").replace(">", "")


def _recortar_bytes(texto: str, maximo: int) -> str:
    return texto.encode("utf-8")[:maximo].decode("utf-8", errors="ignore")


def metadatos_youtube(clip: dict) -> dict | None:
    """{titulo, descripcion, tags} para la API de YouTube. None si no hay ni título."""
    yt = ((clip or {}).get("publicacion") or {}).get("youtube_shorts") or {}
    quemado = " ".join(x.strip() for x in ((clip or {}).get("texto_linea1"), (clip or {}).get("texto_linea2")) if x)
    titulo = _sin_angulos((yt.get("titulo_alt") or "").strip() or quemado).strip()[:TITULO_MAX].strip()
    if not titulo:
        return None
    descripcion = _recortar_bytes(_sin_angulos(_con_hashtags(yt.get("descripcion"), yt.get("hashtags"))),
                                  DESCRIPCION_MAX)
    tags, total = [], 0
    for tag in yt.get("tags_backend") or []:
        tag = _sin_angulos((tag or "").strip())
        if not tag or tag in tags:
            continue
        # YouTube cuenta las comillas que agrega a los tags con espacios, y una coma entre tags
        largo = len(tag) + (2 if " " in tag else 0) + (1 if tags else 0)
        if total + largo > TAGS_MAX:
            break
        tags.append(tag)
        total += largo
    return {"titulo": titulo, "descripcion": descripcion, "tags": tags}


def texto_youtube(meta: dict | None) -> str | None:
    """Lo que el panel muestra de un envío a YouTube (lo que va por la API)."""
    if not meta:
        return None
    partes = [f"Título: {meta['titulo']}"]
    if meta.get("descripcion"):
        partes.append(f"Descripción: {meta['descripcion']}")
    if meta.get("tags"):
        partes.append(f"Tags: {', '.join(meta['tags'])}")
    return "\n\n".join(partes)
