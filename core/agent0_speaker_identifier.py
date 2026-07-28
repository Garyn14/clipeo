"""
agent0_speaker_identifier.py — Identifica hablantes con Claude + metadata del video.

Uso interno:
    from core.agent0_speaker_identifier import identify_speakers
    enriched_path = identify_speakers(raw_path, metadata_path, session_dir)

Uso CLI:
    python core/agent0_speaker_identifier.py <raw_path> <metadata_path>
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import anthropic

SYSTEM_PROMPT = """Eres un identificador de hablantes para contenido
en español latino.

Recibirás metadata de un video, los primeros minutos
de transcripción con speakers genéricos, y — si aplica —
un ROSTER de personajes conocidos del nicho/canal.

Tu tarea es identificar quién es cada speaker.

ESTRATEGIA DE IDENTIFICACIÓN:
- Si hay ROSTER: priorízalo. Busca coincidencias con los
  nombres/alias listados, o con su vocabulario característico
  si se menciona.
- Busca presentaciones explícitas:
  "soy Juan", "me llamo", "hoy tenemos a..."
- Infiere roles por comportamiento:
  quien hace preguntas = host/entrevistador
  quien responde y narra = invitado/protagonista
  voz continua sin interrupciones = narrador
- Usa el título, descripción y el canal/uploader del video
  para confirmar nombres — el uploader suele ser el dueño
  del canal y el hablante principal

IMPORTANTE — NO FUERCES IDENTIDADES:
- Un speaker puede no pertenecer a nadie del ROSTER
  (invitado ocasional, tercero, alguien fuera del nicho).
  Eso es normal y esperado — déjalo como SPEAKER_XX con
  confianza 0.0. NO es un error dejar gente sin identificar.
- Solo asigna un nombre cuando haya evidencia razonable
  (coincidencia con ROSTER, autopresentación, o consenso
  claro del contexto). Ante la duda, mantén SPEAKER_XX.

FORMATO DE RESPUESTA — solo JSON válido:
{
  "mapa": {
    "SPEAKER_00": "Juan (host)",
    "SPEAKER_01": "Bruce (invitado)",
    "SPEAKER_02": "SPEAKER_02"
  },
  "confianza": {
    "SPEAKER_00": 0.95,
    "SPEAKER_01": 0.88,
    "SPEAKER_02": 0.0
  }
}"""


def _extract_preview(raw_text: str, max_seconds: int = 180) -> str:
    """Extrae los primeros max_seconds segundos de la transcripción raw."""
    lines   = []
    pattern = re.compile(r"\[(\d+):(\d+)\]")

    for line in raw_text.splitlines():
        m = pattern.match(line)
        if m:
            secs = int(m.group(1)) * 60 + int(m.group(2))
            if secs > max_seconds:
                break
        lines.append(line)

    return "\n".join(lines)


def _unique_speakers(raw_text: str) -> list[str]:
    """Extrae la lista de SPEAKER_XX únicos del texto."""
    return sorted(set(re.findall(r"SPEAKER_\d+", raw_text)))


def _build_roster_context(config: dict, metadata: dict) -> str:
    """
    Arma el bloque ROSTER con los personajes conocidos del nicho/canal
    (nombres + alias + vocabulario si hay lore) y el uploader del video
    como pista. Retorna "" si no hay personajes en config (canal sin
    ecosistema) — Agente 0 se comporta igual que antes en ese caso.
    """
    personajes = (config or {}).get("personajes", [])
    if not personajes:
        return ""

    vocabulario_por_id: dict[str, list[str]] = {}
    for ent_data in (config or {}).get("entidades", []):
        eid  = ent_data.get("entidad", {}).get("id")
        voc  = ent_data.get("lore", {}).get("vocabulario", [])
        if eid and voc:
            vocabulario_por_id[eid] = [v.get("termino", "") for v in voc if v.get("termino")]

    lines = ["ROSTER DE PERSONAJES CONOCIDOS DEL NICHO:"]
    for p in personajes:
        nombres = ", ".join(p.get("nombres", []))
        linea   = f"- {nombres}"
        voc     = vocabulario_por_id.get(p.get("id", ""))
        if voc:
            linea += f"  (vocabulario propio: {', '.join(voc[:5])})"
        lines.append(linea)

    uploader = (
        metadata.get("uploader") or
        metadata.get("channel") or
        metadata.get("channel_id") or ""
    )
    if uploader:
        lines.append(
            f"\nCANAL/UPLOADER DEL VIDEO: {uploader}"
            f"\n(es probable, aunque no seguro, que el hablante principal "
            f"sea el dueño de este canal — úsalo como pista, no como regla fija)"
        )

    return "\n".join(lines)


def _call_claude(
    client: anthropic.Anthropic, preview: str, metadata: dict, roster: str = "",
) -> dict:
    titulo      = metadata.get("title", "") or metadata.get("fulltitle", "")
    descripcion = (metadata.get("description", "") or "")[:800]

    user_content = (
        f"TÍTULO: {titulo}\n"
        f"DESCRIPCIÓN: {descripcion}\n\n"
        + (f"{roster}\n\n" if roster else "")
        + f"TRANSCRIPCIÓN (primeros 3 min):\n{preview}"
    )

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = resp.content[0].text.strip()
    m   = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"Claude no devolvió JSON válido: {raw[:200]}")
    return json.loads(m.group())


def _fallback_single_speaker(
    transcripcion: str,
    metadata: dict,
    config: dict,
) -> dict:
    """
    Cuando Claude no identifica ningún speaker con confianza, usa el uploader
    del metadata para asignar el speaker que más habla al personaje del canal.
    """
    uploader = (
        metadata.get("uploader") or
        metadata.get("channel") or
        metadata.get("channel_id") or ""
    ).lower().strip()

    for personaje in config.get("personajes", []):
        for nombre in personaje.get("nombres", []):
            if nombre.lower() in uploader or uploader in nombre.lower():
                speaker_counts: dict[str, int] = {}
                for line in transcripcion.splitlines():
                    if "SPEAKER_" in line:
                        token = line.split(":")[0].strip()
                        if "SPEAKER_" in token:
                            speaker_counts[token] = speaker_counts.get(token, 0) + 1
                if speaker_counts:
                    main_speaker    = max(speaker_counts, key=speaker_counts.get)
                    nombre_canonico = personaje["nombres"][0]
                    print(
                        f"[AGENT0] Fallback metadata: {main_speaker} → "
                        f"{nombre_canonico}  (uploader: {uploader})"
                    )
                    return {main_speaker: nombre_canonico}
    return {}


def identify_speakers(
    raw_path: Path,
    metadata_path: Path,
    session_dir: Path,
    config: dict | None = None,
) -> Path:
    """
    Lee transcripcion_raw.txt + metadata.json, identifica hablantes con Claude,
    guarda transcripcion_enriquecida.txt + speaker_map.json.

    Si la transcripción no tiene speakers (sin SPEAKER_XX), copia raw como enriquecida.
    Si todos los speakers quedan con confianza 0, aplica fallback por metadata del video.

    Retorna Path a transcripcion_enriquecida.txt.
    """
    raw_text = Path(raw_path).read_text(encoding="utf-8")
    metadata = {}
    if Path(metadata_path).exists():
        try:
            metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
        except Exception:
            pass

    speakers      = _unique_speakers(raw_text)
    enriched_path = session_dir / "transcripcion_enriquecida.txt"
    map_path      = session_dir / "speaker_map.json"

    if not speakers:
        print("[AGENT0] No se detectaron speakers — copiando raw como enriquecida")
        enriched_path.write_text(raw_text, encoding="utf-8")
        map_path.write_text(
            json.dumps({"mapa": {}, "confianza": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return enriched_path

    ident_cfg   = (config or {}).get("identificacion", {})
    umbral_alto = ident_cfg.get("umbral_alto", 0.70)
    umbral_bajo = ident_cfg.get("umbral_bajo", 0.40)

    print(f"[AGENT0] Speakers detectados: {len(speakers)}  ({', '.join(speakers)})")

    client  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    preview = _extract_preview(raw_text, max_seconds=180)
    roster  = _build_roster_context(config or {}, metadata)
    if roster:
        n_personajes = len((config or {}).get("personajes", []))
        print(f"[AGENT0] Roster cargado: {n_personajes} personaje(s) del nicho")

    try:
        result    = _call_claude(client, preview, metadata, roster)
        mapa      = result.get("mapa", {})
        confianza = result.get("confianza", {})
    except Exception as e:
        print(f"[AGENT0] ⚠ Claude falló ({e}) — usando speakers genéricos")
        mapa      = {s: s for s in speakers}
        confianza = {s: 0.0 for s in speakers}

    # Completar mapa con speakers no identificados
    for s in speakers:
        if s not in mapa:
            mapa[s]      = s
            confianza[s] = 0.0

    # Fallback: si todos quedaron sin confianza, usar metadata del video
    todos_sin_confianza = all(v == 0.0 for v in confianza.values())
    if todos_sin_confianza and config:
        fallback = _fallback_single_speaker(raw_text, metadata, config)
        if fallback:
            mapa.update(fallback)
            confianza[list(fallback.keys())[0]] = 0.60
            print("[AGENT0] ✅ Fallback aplicado")

    # Clasificar cada speaker según umbrales
    speaker_map_detallado: dict[str, dict] = {}
    for spk in speakers:
        nombre_raw = mapa.get(spk, spk)
        conf       = confianza.get(spk, 0.0)
        tiene_nombre = (nombre_raw != spk)

        if conf >= umbral_alto:
            estado        = "confirmado"
            nombre_final  = nombre_raw if tiene_nombre else spk
            print(f"[AGENT0] {spk} → {nombre_final} (confirmado, {conf:.2f})")
        elif conf >= umbral_bajo:
            estado        = "posible"
            nombre_final  = nombre_raw if tiene_nombre else None
            label         = nombre_raw if tiene_nombre else spk
            print(f"[AGENT0] {spk} → {label} (posible, {conf:.2f}) — no usado")
        else:
            estado        = "desconocido"
            nombre_final  = None
            print(f"[AGENT0] {spk} → desconocido ({conf:.2f}) — no usado")

        speaker_map_detallado[spk] = {
            "nombre":    nombre_final,
            "confianza": round(conf, 2),
            "estado":    estado,
        }

    # Aplicar mapa a toda la transcripción respetando estados
    enriched_lines = []
    for line in raw_text.splitlines():
        new_line = line
        for spk, info in speaker_map_detallado.items():
            if info["estado"] == "confirmado":
                new_line = new_line.replace(spk, info["nombre"])
            else:
                # Marca [sin identificar] sólo en la etiqueta de hablante
                new_line = new_line.replace(
                    f"{spk}:", f"{spk} [sin identificar]:"
                )
        enriched_lines.append(new_line)

    enriched_path.write_text("\n".join(enriched_lines), encoding="utf-8")
    map_path.write_text(
        json.dumps(speaker_map_detallado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[AGENT0] ✅ transcripcion_enriquecida.txt guardada")
    return enriched_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python core/agent0_speaker_identifier.py <raw_path> <metadata_path>")
        sys.exit(1)

    raw_path      = Path(sys.argv[1])
    metadata_path = Path(sys.argv[2])
    session_dir   = raw_path.parent

    result_path = identify_speakers(raw_path, metadata_path, session_dir)

    print(f"\nResultado: {result_path}")
    lines = result_path.read_text(encoding="utf-8").splitlines()[:20]
    print("\n--- Primeras 20 líneas de transcripcion_enriquecida.txt ---")
    for line in lines:
        print(line)
