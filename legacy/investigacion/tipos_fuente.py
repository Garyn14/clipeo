"""
tipos_fuente.py — CLIP-66/67: tipos de fuente desacoplados (registro de plataformas).

Cada tipo sabe resolver lo que pega el operador (link o usuario) y listar videos recientes. El resto del sistema
(búsqueda, filtro, historial, panel) solo habla con este registro: agregar una plataforma = una clase + registrar().

Implementados: youtube (feed RSS, sin cuenta ni costo), manual (links sueltos de cualquier sitio que yt-dlp
descargue; sin búsqueda automática) y kick (CLIP-70: directos grabados de canales propios, API pública v2).
Registrados como "próximamente": twitch, tiktok (cada uno necesita su análisis de viabilidad: API, costo, términos, R-01).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

_NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
       "media": "http://search.yahoo.com/mrss/"}


class FuenteError(ValueError):
    """Error explicable al operador (link inválido, tipo no disponible...)."""


class TipoFuente:
    clave = ""
    nombre = ""
    implementado = True
    automatico = True                 # se revisa con "Buscar ahora"; si no, se agregan links a mano
    pide = "Link del canal"
    roles = ("propio", "medios")      # CLIP-70: roles que admite el tipo (Kick: solo propio)

    def resolver(self, entrada: str) -> dict:
        """Lo que pegó el operador → {nombre, url} del canal. Lanza FuenteError si no es válido."""
        raise FuenteError(f"{self.nombre}: todavía no disponible")

    def listar(self, canal: dict) -> list[dict]:
        """Videos recientes del canal → [{id, titulo, descripcion, publicado (datetime UTC), url}]."""
        raise FuenteError(f"{self.nombre}: todavía no disponible")

    def info_video(self, link: str) -> dict:
        """Un video suelto (tipos manuales) → {id, titulo, canal, publicado, url}."""
        raise FuenteError(f"{self.nombre}: no admite videos sueltos")

    def describir(self) -> dict:
        return {"clave": self.clave, "nombre": self.nombre, "implementado": self.implementado,
                "automatico": self.automatico, "pide": self.pide, "roles": list(self.roles)}


REGISTRO: dict[str, TipoFuente] = {}


def registrar(tipo: TipoFuente) -> TipoFuente:
    REGISTRO[tipo.clave] = tipo
    return tipo


def obtener(clave: str | None) -> TipoFuente:
    tipo = REGISTRO.get(clave or "youtube")
    if tipo is None:
        raise FuenteError(f"tipo de fuente desconocido: {clave}")
    return tipo


def tipos() -> list[dict]:
    return [t.describir() for t in REGISTRO.values()]


# ── YouTube ─────────────────────────────────────────────────

# CLIP-72: plataforma de un video a partir de su link (sirve también para el historial ya guardado)
_PLATAFORMAS = {"youtube.com": "YouTube", "youtu.be": "YouTube", "kick.com": "Kick", "tiktok.com": "TikTok",
                "twitch.tv": "Twitch", "facebook.com": "Facebook", "fb.watch": "Facebook",
                "instagram.com": "Instagram", "x.com": "X", "twitter.com": "X"}


def plataforma_de(url: str | None) -> str:
    """'YouTube', 'Kick'…; sitio sin nombre conocido → su dominio; sin link → ''. Puro."""
    m = re.match(r"^(?:[a-z][a-z0-9+.-]*://)?([^/?#:]+)", (url or "").strip().lower())
    if not m:
        return ""
    host = m.group(1)
    host = host[4:] if host.startswith("www.") else host
    for dominio, nombre in _PLATAFORMAS.items():
        if host == dominio or host.endswith("." + dominio):
            return nombre
    return host


def channel_id(url: str) -> str | None:
    m = re.search(r"/channel/(UC[\w-]{20,})", url or "")
    return m.group(1) if m else None


def parsear_feed(xml: str) -> tuple[str, list[dict]]:
    """Feed RSS de un canal → (nombre del canal, videos). Puro."""
    raiz = ET.fromstring(xml)
    nombre = raiz.findtext("a:title", default="", namespaces=_NS)
    videos = []
    for e in raiz.findall("a:entry", _NS):
        vid = e.findtext("yt:videoId", default="", namespaces=_NS)
        publicado = e.findtext("a:published", default="", namespaces=_NS)
        videos.append({
            "id": vid,
            "titulo": e.findtext("a:title", default="", namespaces=_NS),
            "descripcion": e.findtext("media:group/media:description", default="", namespaces=_NS) or "",
            "publicado": datetime.fromisoformat(publicado.replace("Z", "+00:00")) if publicado else None,
            "url": f"https://www.youtube.com/watch?v={vid}",
        })
    return nombre, videos


def _yt_dlp_info(link: str, plano: bool = False) -> dict:
    import yt_dlp
    opciones = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    if plano:
        opciones.update({"extract_flat": True, "playlist_items": "1"})
    try:
        with yt_dlp.YoutubeDL(opciones) as ydl:
            return ydl.extract_info(link, download=False) or {}
    except Exception as e:  # noqa: BLE001
        raise FuenteError(f"no se pudo leer el link ({str(e)[:120]})") from e


class YouTube(TipoFuente):
    clave = "youtube"
    nombre = "YouTube"
    pide = "Link del canal (/@usuario o /channel/UC…) o de uno de sus videos"

    def _feed(self, cid: str) -> tuple[str, list[dict]]:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "clipeo"}), timeout=30) as r:
            return parsear_feed(r.read().decode("utf-8"))

    def resolver(self, entrada: str) -> dict:
        entrada = (entrada or "").strip()
        if entrada.startswith("@"):
            entrada = f"https://www.youtube.com/{entrada}"
        if not re.search(r"(youtube\.com|youtu\.be)/", entrada):
            raise FuenteError("pega un link de YouTube (canal o video)")
        cid = channel_id(entrada)
        if not cid:
            info = _yt_dlp_info(entrada, plano=True)
            cid = info.get("channel_id") or (info.get("id") if str(info.get("id", "")).startswith("UC") else None)
        if not cid:
            raise FuenteError("no se encontró el canal de ese link")
        nombre, _ = self._feed(cid)
        return {"nombre": nombre or cid, "url": f"https://www.youtube.com/channel/{cid}"}

    def listar(self, canal: dict) -> list[dict]:
        cid = channel_id(canal.get("url", ""))
        if not cid:
            raise FuenteError(f"URL sin /channel/UC…: {canal.get('url')}")
        return self._feed(cid)[1]


# ── Lista manual (CLIP-67) ──────────────────────────────────

class ListaManual(TipoFuente):
    clave = "manual"
    nombre = "Lista manual"
    automatico = False
    pide = "Links de videos (uno por línea), de cualquier sitio que se pueda descargar"

    def info_video(self, link: str) -> dict:
        link = (link or "").strip()
        if not re.match(r"https?://", link):
            raise FuenteError(f"no es un link: {link[:60]}")
        info = _yt_dlp_info(link)
        if not info.get("id"):
            raise FuenteError(f"sitio no soportado o video no disponible: {link[:60]}")
        fecha = info.get("upload_date")
        publicado = datetime.strptime(fecha, "%Y%m%d").replace(tzinfo=timezone.utc) if fecha else None
        return {"id": str(info["id"]), "titulo": info.get("title") or link,
                "canal": info.get("channel") or info.get("uploader") or info.get("extractor_key") or "",
                "publicado": publicado, "url": info.get("webpage_url") or link}


# ── Kick (CLIP-70): directos grabados (VODs) de canales propios ──

KICK_API = "https://kick.com/api/v2/channels"


def kick_slug(entrada: str) -> str | None:
    """`kick.com/usuario`, `https://kick.com/usuario/videos/…`, `@usuario` o `usuario` → usuario. Puro."""
    entrada = (entrada or "").strip()
    m = re.search(r"kick\.com/([A-Za-z0-9_-]+)", entrada)
    if m:
        return m.group(1).lower()
    entrada = entrada.lstrip("@")
    return entrada.lower() if re.fullmatch(r"[A-Za-z0-9_-]{3,}", entrada) else None


def parsear_vods(slug: str, items: list[dict]) -> list[dict]:
    """Respuesta de /channels/<slug>/videos → videos. Puro. Las horas de Kick vienen en UTC."""
    videos = []
    for v in items or []:
        uuid = (v.get("video") or {}).get("uuid")
        if not uuid or v.get("is_live"):
            continue                                   # solo directos ya terminados (el vivo es el módulo Live)
        cuando = v.get("start_time") or v.get("created_at")
        try:
            publicado = datetime.fromisoformat(str(cuando)).replace(tzinfo=timezone.utc) if cuando else None
        except ValueError:
            publicado = None
        videos.append({"id": uuid, "titulo": v.get("session_title") or "Directo grabado", "descripcion": "",
                       "publicado": publicado, "url": f"https://kick.com/{slug}/videos/{uuid}",
                       "duracion_s": round((v.get("duration") or 0) / 1000)})
    return videos


def _kick_get(ruta: str):
    import json
    req = urllib.request.Request(f"{KICK_API}/{ruta}", headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise FuenteError(f"no existe el canal de Kick «{ruta.split('/')[0]}»") from e
        raise FuenteError(f"Kick no respondió (HTTP {e.code})") from e
    except Exception as e:  # noqa: BLE001 — la API pública no es oficial: puede cambiar o bloquearse
        raise FuenteError(f"Kick no respondió ({str(e)[:100]})") from e


class Kick(TipoFuente):
    clave = "kick"
    nombre = "Kick"
    pide = "Link del canal de Kick (kick.com/usuario)"
    roles = ("propio",)               # los títulos de Kick son genéricos: el filtro por palabras no aplica

    def resolver(self, entrada: str) -> dict:
        slug = kick_slug(entrada)
        if not slug:
            raise FuenteError("pega el link del canal de Kick (kick.com/usuario)")
        datos = _kick_get(slug)
        if not isinstance(datos, dict) or not datos.get("slug"):
            raise FuenteError(f"no existe el canal de Kick «{slug}»")
        return {"nombre": (datos.get("user") or {}).get("username") or datos["slug"],
                "url": f"https://kick.com/{datos['slug']}"}

    def listar(self, canal: dict) -> list[dict]:
        slug = kick_slug(canal.get("url", ""))
        if not slug:
            raise FuenteError(f"URL de Kick inválida: {canal.get('url')}")
        datos = _kick_get(f"{slug}/videos")
        return parsear_vods(slug, datos if isinstance(datos, list) else (datos or {}).get("data", []))


class Proximamente(TipoFuente):
    implementado = False

    def __init__(self, clave: str, nombre: str):
        self.clave, self.nombre = clave, nombre


registrar(YouTube())
registrar(ListaManual())
registrar(Kick())
for _clave, _nombre in (("twitch", "Twitch"), ("tiktok", "TikTok")):
    registrar(Proximamente(_clave, _nombre))
