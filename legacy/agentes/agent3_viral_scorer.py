"""
===========================================
  IDEA MILLONARIA - Pipeline Paso 4
  Agent 3: Viral Scorer y Generador de Contenido
===========================================

Lee rangos.json, extrae el clip exacto de la transcripción,
llama a Claude para scorearlo y generar título/hook/hashtags,
guarda el resultado en contenido.json.

Uso:
  python agent3_viral_scorer.py stream_data/<session_id>/rangos.json
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import re
import anthropic
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.utils import _timestamp_to_seconds, _parse_segments
from ai_client import get_client

# ─────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
# ─────────────────────────────────────────


def _extract_clip(segments: list[tuple[int, str]], inicio: str, fin: str) -> str:
    """Extrae las líneas exactas entre inicio y fin del rango."""
    start = _timestamp_to_seconds(inicio)
    end   = _timestamp_to_seconds(fin)
    lines = [line for secs, line in segments if start <= secs <= end]
    return "\n".join(lines)


def _detect_personajes_in_range(text: str, config: dict) -> list[str]:
    """Detecta personajes conocidos dentro de un texto arbitrario."""
    personajes = config.get("personajes", [])
    if not personajes:
        return []
    texto = text.lower()
    encontrados = []
    for personaje in personajes:
        canonical = (personaje.get("nombres") or [None])[0]
        if not canonical:
            continue
        for nombre in personaje.get("nombres", []):
            if nombre.lower() in texto:
                encontrados.append(canonical)
                break
    return encontrados


def _build_personajes_note(
    session_dir: Path,
    config: dict,
    segments: list | None = None,
    inicio: str | None = None,
    fin: str | None = None,
    all_in_chunk: list[str] | None = None,
    margin: int = 30,
) -> str:
    """
    Construye la nota de personajes para el prompt del Agente 3.

    Cuando recibe segments + inicio/fin, escanea SOLO el rango ±margin segundos,
    evitando que personajes de otros momentos del chunk contaminen el clip actual.
    """
    if segments is not None and inicio is not None and fin is not None:
        start = max(0, _timestamp_to_seconds(inicio) - margin)
        end   = _timestamp_to_seconds(fin) + margin
        scan_text   = "\n".join(line for secs, line in segments if start <= secs <= end)
        encontrados = _detect_personajes_in_range(scan_text, config)

        excluidos = [n for n in (all_in_chunk or []) if n not in encontrados]
        label = f"{inicio}→{fin}"
        if encontrados:
            print(f"[AGENT3] Personajes en rango {label}: {', '.join(encontrados)}")
        else:
            print(f"[AGENT3] Personajes en rango {label}: (ninguno)")
        if excluidos:
            print(f"           excluidos (fuera de rango): {', '.join(excluidos)}")
    else:
        # Modo legacy sin rango: escanea transcripción completa
        for fname in ("transcripcion_enriquecida.txt", "transcripcion_completa.txt"):
            tp = session_dir / fname
            if tp.exists():
                scan_text = tp.read_text(encoding="utf-8")
                break
        else:
            scan_text = ""
        encontrados = _detect_personajes_in_range(scan_text, config)

    if not encontrados:
        for meta_path in [
            session_dir / "metadata.json",
            session_dir.parent.parent / "metadata.json",
        ]:
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    uploader = meta.get("uploader") or meta.get("channel") or ""
                    if uploader:
                        return (
                            f"PERSONAJE PRESENTE EN ESTE FRAGMENTO:\n"
                            f" - {uploader}\n\n"
                            f"Este nombre está confirmado y puedes usarlo en el título,\n"
                            f"pero analiza el TEXTO del clip para entender su ROL real\n"
                            f"(¿habla él? ¿es mencionado como sujeto? ¿como receptor?).\n"
                            f"No asumas que es automáticamente el sujeto de la frase.\n"
                            f"Si el speaker que actúa es [sin identificar], redacta\n"
                            f"con la acción como sujeto implícito — no le asignes\n"
                            f"el nombre de otro personaje mencionado como referencia."
                        )
                except Exception:
                    pass
        return ""

    nombres_str = "\n ".join(f"- {n}" for n in encontrados)
    return (
        f"PERSONAJES PRESENTES EN ESTE FRAGMENTO:\n"
        f" {nombres_str}\n\n"
        f"Estos nombres están confirmados y puedes usarlos en el título,\n"
        f"pero analiza el TEXTO del clip para entender el ROL real de cada uno\n"
        f"(¿quién habla? ¿quién es sujeto de la acción? ¿quién es receptor?).\n"
        f"No asumas que un personaje listado aquí es automáticamente el sujeto.\n"
        f"Si el speaker que confiesa/actúa es [sin identificar], redacta con\n"
        f"la acción como sujeto implícito — no le asignes el nombre de otro\n"
        f"personaje mencionado solo como referencia."
    )


def _merge_hashtags(base: list[str], extra: list[str]) -> list[str]:
    """Combina hashtags base + extra sin duplicados, preservando el orden (base primero)."""
    return list(dict.fromkeys((base or []) + (extra or [])))


def _format_seo_context(seo_base: dict) -> str:
    """
    Arma el bloque de texto 'SEO BASE POR PLATAFORMA' a partir de
    config["seo_base"] (ver contexto/nichos/<id>.yaml) para inyectarlo en el
    prompt cacheado de _call_claude(), igual que el bloque de aprendizajes.
    """
    if not seo_base:
        return ""

    bloques = []
    actualizado = seo_base.get("actualizado")
    if actualizado:
        bloques.append(f"(última actualización: {actualizado})")

    for plataforma_id, etiqueta in (("tiktok", "TikTok"), ("youtube_shorts", "YouTube Shorts")):
        datos        = seo_base.get(plataforma_id) or {}
        hashtags     = datos.get("hashtags") or []
        tags_backend = datos.get("tags_backend") or []
        notas        = (datos.get("notas") or "").strip()
        if not hashtags and not tags_backend and not notas:
            continue
        partes = [f"{etiqueta}:"]
        if hashtags:
            partes.append(f"  Hashtags base: {', '.join(hashtags)}")
        if tags_backend:
            partes.append(f"  Tags backend base: {', '.join(tags_backend)}")
        if notas:
            partes.append(f"  Notas: {notas}")
        bloques.append("\n".join(partes))

    return "\n\n".join(bloques).strip()


def _call_claude(
    client: anthropic.Anthropic, rango: dict, clip_text: str, prompt: str,
    aprendizajes_context: str | None = None,
    seo_context: str | None = None,
    extra_note: str = "",
) -> dict:
    # Bloque cacheado: prompt del nicho + aprendizajes + SEO base (grande, repetido por cada clip)
    cached_context = prompt
    if aprendizajes_context:
        cached_context += f"\n\n---\nREGLAS ACTIVAS DEL NICHO:\n{aprendizajes_context}\n---"
    if seo_context:
        cached_context += f"\n\n---\nSEO BASE POR PLATAFORMA:\n{seo_context}\n---"

    # Bloque no cacheado: datos específicos del clip (cambia en cada llamada)
    clip_block = (
        f"RANGO A EVALUAR:\n"
        f"  Timestamp : {rango.get('inicio')} → {rango.get('fin')}\n"
        f"  Duración  : {rango.get('duracion_segundos')}s\n"
        f"  Razón A2  : {rango.get('razon')}\n"
        f"  Gancho A2 : {rango.get('gancho')}\n\n"
        f"Transcripción:\n{clip_text}\n---"
    )

    if extra_note:
        clip_block += "\n\n" + extra_note

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": cached_context,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": clip_block,
                },
            ],
        }],
    )

    raw = response.content[0].text.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"  ⚠️  Respuesta no es JSON válido: {raw[:200]}")
        return {"score": 0, "publicar": False, "razon_score": "respuesta no parseable"}

    try:
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Error parseando JSON: {e}")
        return {"score": 0, "publicar": False, "razon_score": f"JSON inválido: {e}"}


def _completar_item(resultado: dict, config: dict, seo_base: dict, hashtags_base: list[str]) -> dict:
    """
    Post-proceso de la respuesta de Claude para un clip (común al modo score y al modo
    copy): limpieza de nombres, merge de hashtags con los base y el SEO por plataforma,
    defaults de los campos que lee el Agente 4.
    """
    # Limpiar nombres canónicos en el texto generado
    if config.get("personajes"):
        from transcripcion.transcript_cleaner import clean_known_names as _clean
        l1 = resultado.get("texto_linea1", "")
        l2 = resultado.get("texto_linea2", "")
        if l1 or l2:
            cleaned = _clean(l1 + "\n" + l2, config, silent=True)
            partes = cleaned.split("\n", 1)
            resultado["texto_linea1"] = partes[0].strip()
            if len(partes) > 1:
                resultado["texto_linea2"] = partes[1].strip()

    # Mergear hashtags: base del config + específicos de Claude, sin duplicados
    resultado["hashtags"] = _merge_hashtags(hashtags_base, resultado.get("hashtags", []))

    # Default defensivo por si el prompt no pide/Claude omite el mood
    # (usado por Agente 4 para elegir música de fondo — ver edicion_video/)
    resultado.setdefault("mood", "neutral")

    # Default defensivo por si el prompt no pide/Claude omite el estilo
    # de texto (usado por Agente 4 para decidir el modo de subtítulo —
    # "fijo" preserva el comportamiento previo a este campo)
    resultado.setdefault("estilo_texto", "fijo")

    # Defaults defensivos para los campos opcionales de la Fase 6
    # (CTA y resaltado de palabra clave — ver edicion_video/)
    resultado.setdefault("cta_texto", "")
    resultado.setdefault("palabras_clave", [])

    # Default defensivo para el relleno de fuente horizontal (Fase 7).
    # "blur" es el default temporal (2026-07-30, ver contexto/nichos/*.yaml)
    # mientras "imagen"/"crop" maduran — revertir a "pillarbox" cuando eso
    # cambie.
    resultado.setdefault("layout", "blur")

    # Publicación por plataforma (SEO) — Claude redacta descripción/hashtags
    # específicos del clip; se mezclan con los hashtags base de seo_base
    # (contexto/nichos/<id>.yaml) igual que el merge global de arriba, para
    # garantizar que los "siempre incluir" (ej. #Shorts) sobrevivan aunque
    # Claude no los repita. Defaults vacíos si Claude omite el campo entero.
    publicacion = resultado.get("publicacion") or {}
    tiktok_seo  = seo_base.get("tiktok", {})
    yt_seo      = seo_base.get("youtube_shorts", {})
    tiktok_pub  = publicacion.get("tiktok") or {}
    yt_pub      = publicacion.get("youtube_shorts") or {}
    resultado["publicacion"] = {
        "tiktok": {
            "descripcion": tiktok_pub.get("descripcion", ""),
            "hashtags": _merge_hashtags(tiktok_seo.get("hashtags", []), tiktok_pub.get("hashtags", [])),
        },
        "youtube_shorts": {
            "titulo_alt":   yt_pub.get("titulo_alt", ""),
            "descripcion":  yt_pub.get("descripcion", ""),
            "hashtags":     _merge_hashtags(yt_seo.get("hashtags", []), yt_pub.get("hashtags", [])),
            "tags_backend": _merge_hashtags(yt_seo.get("tags_backend", []), yt_pub.get("tags_backend", [])),
        },
    }

    # Efecto de sonido corto (stinger/whoosh) anclado al momento de
    # énfasis (Fase 15) — None preserva el comportamiento previo; no
    # está en el prompt todavía (sin assets curados en
    # edicion_video/assets/efectos_sonido/, ver docs/ESTRUCTURA_DATOS.md)
    resultado.setdefault("efecto_sonido", None)

    # layout_streaming (Fase 9) es un hecho TÉCNICO del canal (cómo
    # está armada la escena de OBS del streamer), no una decisión de
    # Claude — se copia tal cual desde la config del canal, nunca se
    # le pide a Claude. Agente 4 sigue sin recibir config directamente
    # (se mantiene "técnico puro"): esto viaja igual que mood/estilo_texto,
    # a través de contenido.json.
    resultado["layout_streaming"] = config.get("layout_streaming")
    return resultado


def run_agent(rangos_path: str, config: dict) -> list[dict]:
    rangos_file = Path(rangos_path)
    if not rangos_file.exists():
        print(f"[AGENT3] ❌ No se encontró: {rangos_file}")
        sys.exit(1)

    session_dir = rangos_file.parent

    # Prefiere enriquecida (tiene marcadores [sin identificar]); cae a completa
    for _fname in ("transcripcion_enriquecida.txt", "transcripcion_completa.txt"):
        transcripcion = session_dir / _fname
        if transcripcion.exists():
            print(f"[AGENT3] Transcripción: {_fname}")
            break
    else:
        print(f"[AGENT3] ❌ No se encontró transcripción en {session_dir}")
        sys.exit(1)

    prompt        = config["contenido"]["prompt"]
    score_minimo  = config["contenido"]["score_minimo_publicar"]
    hashtags_base = config["contenido"]["hashtags_base"]
    palabras_prohibidas = (
        config.get("contenido_restricciones", {})
              .get("palabras_prohibidas", [])
    )
    if palabras_prohibidas:
        print(f"[AGENT3] Palabras prohibidas: {len(palabras_prohibidas)} configuradas")

    # Cargar aprendizajes optimizados si existen
    canal_id          = config.get("meta", {}).get("id", "default")
    aprendizajes_path = Path(__file__).parent.parent / "aprendizajes" / f"{canal_id}_optimizado.md"
    if aprendizajes_path.exists():
        aprendizajes_context = aprendizajes_path.read_text(encoding="utf-8")
        tokens_aprox = len(aprendizajes_context.split())
        print(f"[AGENT3] Aprendizajes: {aprendizajes_path.name}")
        print(f"         cargado (~{tokens_aprox} palabras)")
    else:
        aprendizajes_context = None
        print(f"[AGENT3] Aprendizajes: no encontrado para {canal_id}")

    seo_base    = config.get("seo_base", {})
    seo_context = _format_seo_context(seo_base)
    if seo_context:
        print(f"[AGENT3] SEO base: cargado (actualizado {seo_base.get('actualizado', '?')})")
    else:
        print(f"[AGENT3] SEO base: no configurado para {canal_id}")

    rangos_data  = json.loads(rangos_file.read_text(encoding="utf-8")).get("rangos", [])
    conservados  = [r for r in rangos_data if r.get("conservar")]
    text         = transcripcion.read_text(encoding="utf-8")
    segments     = _parse_segments(text)
    # Pre-computar el conjunto completo del chunk para poder reportar exclusiones
    all_in_chunk = _detect_personajes_in_range(text, config) if config.get("personajes") else []

    print(f"\n[AGENT3] Sesión      : {session_dir.name}")
    print(f"[AGENT3] Rangos total: {len(rangos_data)}  |  Conservados: {len(conservados)}")
    print(f"[AGENT3] Score mínimo: {score_minimo}  |  Hashtags base: {' '.join(hashtags_base)}")
    print(f"[AGENT3] Prompt Caching activo para lore del nicho")
    print(f"[AGENT3] {'─'*40}\n")

    client     = get_client()
    contenido  = []
    a_publicar = 0
    descartados = 0

    for i, rango in enumerate(conservados):
        inicio = rango.get("inicio", "00:00")
        fin    = rango.get("fin", "00:00")
        razon  = rango.get("razon", "")[:60]

        print(f"[AGENT3] Rango {i + 1}/{len(conservados)} — {inicio} → {fin}  \"{razon}\"")

        clip_text = _extract_clip(segments, inicio, fin)

        # Personajes scoped al rango actual (±30s) — evita contaminación de otros momentos
        personajes_note = _build_personajes_note(
            session_dir, config, segments, inicio, fin, all_in_chunk
        )

        if not clip_text.strip():
            print(f"  ⚠️  Sin texto en el rango, descartando")
            resultado = {"score": 0, "publicar": False, "razon_score": "clip vacío"}
        else:
            resultado = _call_claude(
                client, rango, clip_text, prompt, aprendizajes_context, seo_context, personajes_note
            )

        # Verificar palabras prohibidas y regenerar si es necesario
        if palabras_prohibidas:
            texto_gen = (
                resultado.get("texto_linea1", "") + " " +
                resultado.get("texto_linea2", "")
            ).lower()
            encontradas = [p for p in palabras_prohibidas if p.lower() in texto_gen]
            if encontradas:
                print(f"  ⚠️  Palabras prohibidas: {encontradas} — regenerando...")
                palabras_str = ", ".join(f'"{p}"' for p in palabras_prohibidas)
                extra = (
                    (personajes_note + "\n\n" if personajes_note else "") +
                    f"IMPORTANTE: No uses las siguientes palabras en el texto: "
                    f"{palabras_str}.\n"
                    f"Reformula usando términos alternativos que transmitan el mismo "
                    f"morbo sin las palabras prohibidas."
                )
                resultado = _call_claude(
                    client, rango, clip_text, prompt, aprendizajes_context, seo_context, extra
                )

        _completar_item(resultado, config, seo_base, hashtags_base)

        # Aplicar score mínimo del config
        score    = resultado.get("score", 0)
        publicar = score >= score_minimo
        resultado["publicar"]       = publicar
        resultado["rango_original"] = rango

        if publicar:
            a_publicar += 1
            print(f"  🔥 Score {score}/10 — PUBLICAR")
            print(f"     Línea 1  : {resultado.get('texto_linea1', '')}")
            print(f"     Línea 2  : {resultado.get('texto_linea2', '')}")
            print(f"     Hashtags : {' '.join(resultado.get('hashtags', []))}")
            print(f"     Razón    : {resultado.get('razon_score', '')}")
            print(f"     TikTok   : {resultado['publicacion']['tiktok']['descripcion'][:70]}")
            print(f"     YouTube  : {resultado['publicacion']['youtube_shorts']['titulo_alt']}")
        else:
            descartados += 1
            print(f"  💤 Score {score}/10 — no publicar  ({resultado.get('razon_score', '')})")

        contenido.append(resultado)
        print()

    output_path = session_dir / "contenido.json"
    output_path.write_text(
        json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[AGENT3] {'─'*40}")
    print(f"[AGENT3] 🔥 {a_publicar} para publicar  |  💤 {descartados} descartados")
    print(f"[AGENT3] ✅ Contenido guardado en {output_path}\n")

    return contenido


_NOTA_COPY = """TÍTULO DECIDIDO POR EL JUEZ (no lo cambies, ni lo reescribas):
  Línea 1: {l1}
  Línea 2: {l2}
Este clip YA fue aprobado para publicar: no puntúes ni decidas si publicar.
Completa mood, estilo_texto, cta_texto, palabras_clave, layout y publicacion (TikTok y YouTube
Shorts) de forma coherente con ESE título — la descripción debe hablar del mismo momento y
nombrar al mismo personaje. Devuelve el mismo formato JSON (texto_linea1/2 = el título de arriba)."""


def run_copy(juez_path: str, config: dict) -> tuple[list[dict], list[str]]:
    """
    Modo copy (con juez): escribe el copy solo de los rangos que el juez aprobó, a partir de
    su título — así la descripción de cada plataforma habla del mismo momento que el texto
    quemado. Los rechazados se registran sin llamar a Claude (trazabilidad en contenido_final).
    Guarda contenido.json junto a juez.json. Devuelve (contenido, advertencias).
    """
    juez_file = Path(juez_path)
    chunk_dir = juez_file.parent
    decisiones = json.loads(juez_file.read_text(encoding="utf-8")).get("decisiones", [])

    for _fname in ("transcripcion_enriquecida.txt", "transcripcion_completa.txt"):
        if (chunk_dir / _fname).exists():
            segments = _parse_segments((chunk_dir / _fname).read_text(encoding="utf-8"))
            break
    else:
        segments = []

    prompt        = config["contenido"]["prompt"]
    hashtags_base = config["contenido"]["hashtags_base"]
    prohibidas    = config.get("contenido_restricciones", {}).get("palabras_prohibidas", [])
    canal_id      = config.get("meta", {}).get("id", "default")
    apr_path      = Path(__file__).parent.parent / "aprendizajes" / f"{canal_id}_optimizado.md"
    aprendizajes  = apr_path.read_text(encoding="utf-8") if apr_path.exists() else None
    seo_base      = config.get("seo_base", {})
    seo_context   = _format_seo_context(seo_base)

    from agentes.juez import bloque_juez
    from core import fuente as _fuente

    fuente_sesion = _fuente.leer(chunk_dir)   # CLIP-27: viaja en cada clip (revisión web, R-01)
    credito = _fuente.credito(fuente_sesion)

    aprobadas = [d for d in decisiones if d.get("publicar")]
    print(f"\n[AGENT3] Modo copy — {len(aprobadas)} clip(s) aprobado(s) por el juez de {len(decisiones)}")
    client = get_client() if aprobadas else None
    contenido, advertencias = [], []

    for d in sorted(decisiones, key=lambda x: _timestamp_to_seconds(str(x.get("inicio") or "0:0"))):
        rango = d.get("rango") or {"inicio": d.get("inicio"), "fin": d.get("fin")}
        if not d.get("publicar"):
            contenido.append({
                "score": d.get("fuerza") or 0, "publicar": False,
                "texto_linea1": d.get("linea1") or "", "texto_linea2": d.get("linea2") or "",
                "hashtags": [], "juez": bloque_juez(d), "rango_original": rango,
                **({"fuente": fuente_sesion} if fuente_sesion else {}),
            })
            continue

        l1, l2 = d.get("linea1") or "", d.get("linea2") or ""
        print(f"[AGENT3] {rango.get('inicio')} → {rango.get('fin')}  «{l1} / {l2}»")
        # Dirección editorial (CLIP-31): el plan se aplica ANTES del copy, para que hable del clip dirigido
        plan, montaje = rango.get("plan_edicion"), None
        if plan and (len(plan["segmentos"]) > 1 or plan.get("estructura") == "gancho_primero"):
            montaje = plan["segmentos"]   # varios tramos → `_cut_compilation` del Agente 4
        elif plan:                        # un solo tramo: se corta como siempre, con los bordes de la dirección
            rango["inicio"], rango["fin"] = plan["segmentos"][0]["inicio"], plan["segmentos"][0]["fin"]
        if montaje:
            from agentes.direccion import texto_del_plan
            clip_text = texto_del_plan(segments, montaje)
        else:
            clip_text = _extract_clip(segments, rango.get("inicio", "00:00"), rango.get("fin", "00:00"))
        resultado = _call_claude(client, rango, clip_text, prompt, aprendizajes, seo_context,
                                 _NOTA_COPY.format(l1=l1, l2=l2))
        _completar_item(resultado, config, seo_base, hashtags_base)
        # El título y la decisión son del juez, no del copy
        resultado.update(texto_linea1=l1, texto_linea2=l2, score=d.get("fuerza") or 0, publicar=True)
        resultado.pop("razon_score", None)
        resultado["juez"] = bloque_juez(d)
        resultado["rango_original"] = rango
        if montaje:
            resultado["segmentos"] = montaje
        if fuente_sesion:
            resultado["fuente"] = fuente_sesion
        if credito:   # R-01: crédito al titular en cada plataforma
            for pub in resultado["publicacion"].values():
                desc = (pub.get("descripcion") or "").rstrip()
                if credito not in desc:
                    pub["descripcion"] = f"{desc}\n\n{credito}" if desc else credito

        encontradas = [p for p in prohibidas if p.lower() in f"{l1} {l2}".lower()]
        if encontradas:
            advertencias.append(f"palabras prohibidas en el título del juez ({', '.join(encontradas)}): «{l1} / {l2}»")
            print(f"  ⚠️  {advertencias[-1]}")
        print(f"  ✍️  TikTok: {resultado['publicacion']['tiktok']['descripcion'][:80]}")
        contenido.append(resultado)

    (chunk_dir / "contenido.json").write_text(
        json.dumps({"contenido": contenido}, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return contenido, advertencias


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUso: python agent3_viral_scorer.py <rangos.json> [canal_id]")
        print("Ejemplo: python agent3_viral_scorer.py stream_data/test/rangos.json zapatillas_peru\n")
        sys.exit(1)

    from contexto.config_loader import ConfigLoader

    canal_id = sys.argv[2] if len(sys.argv) >= 3 else None
    cfg      = ConfigLoader(config_dir=str(Path(__file__).parent.parent / "config"))
    config   = cfg.load(canal_id)

    print(f"[AGENT3] Canal : {cfg.get('meta', 'id')}  (config: {cfg.loaded_file.name})")

    run_agent(sys.argv[1], config)
