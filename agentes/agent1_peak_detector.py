"""
===========================================
  IDEA MILLONARIA - Pipeline Paso 2
  Agent 1: Detector de Picos Virales
===========================================

Analiza transcripcion_completa.txt con Claude y detecta momentos
donde el streamer recibe un gift importante y reacciona.

Uso:
  python agent1_peak_detector.py stream_data/<session_id>/transcripcion_completa.txt
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

# ─────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────
MODEL           = "claude-sonnet-4-6"
MAX_WORDS       = 10_000
CHUNK_MINUTES   = 10
OVERLAP_MINUTES = 1
# ─────────────────────────────────────────


def _split_into_chunks(segments: list, chunk_secs: int = 600, overlap_secs: int = 60) -> list[tuple[int, str]]:
    """
    Divide segmentos en ventanas de chunk_secs con overlap_secs de solapamiento.
    Retorna lista de (offset_inicio, texto_del_chunk).
    """
    if not segments:
        return []

    chunks = []
    first_sec = segments[0][0]
    last_sec  = segments[-1][0]
    window_start = first_sec

    while window_start <= last_sec:
        window_end = window_start + chunk_secs
        lines = [line for secs, line in segments if window_start <= secs < window_end]
        if lines:
            chunks.append((window_start, "\n".join(lines)))
        window_start += chunk_secs - overlap_secs

    return chunks


def _call_claude(client: anthropic.Anthropic, text: str, prompt: str) -> list[dict]:
    """Llama a Claude con el texto y retorna la lista de picos parseada."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": text,
                },
            ],
        }],
    )

    raw = response.content[0].text.strip()

    # Extraer el JSON aunque venga con texto extra
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"[AGENT1] ⚠️  Respuesta no es JSON válido: {raw[:200]}")
        return []

    try:
        data = json.loads(m.group())
        return data.get("picos", [])
    except json.JSONDecodeError as e:
        print(f"[AGENT1] ⚠️  JSON truncado: {e} — intentando recuperación parcial...")
        candidatos = re.findall(r"\{[^{}]+\}", m.group())
        recuperados = []
        for cand in candidatos:
            try:
                obj = json.loads(cand)
                if "timestamp" in obj:
                    recuperados.append(obj)
            except json.JSONDecodeError:
                pass
        if recuperados:
            print(f"[AGENT1] ⚠️  JSON parcial — recuperados {len(recuperados)}/{len(candidatos)} picos antes del corte")
            return recuperados
        print(f"[AGENT1] ⚠️  No se pudieron recuperar picos del JSON truncado")
        return []


def _merge_peaks(all_peaks: list[dict], tolerance_secs: int = 30) -> list[dict]:
    """Elimina picos duplicados que estén a menos de tolerance_secs entre sí."""
    seen_seconds = []
    merged = []

    for peak in all_peaks:
        secs = _timestamp_to_seconds(peak.get("timestamp", ""))
        if any(abs(secs - s) <= tolerance_secs for s in seen_seconds):
            continue
        seen_seconds.append(secs)
        merged.append(peak)

    return merged


def run_agent(transcripcion_path: str, config: dict) -> list[dict]:
    """
    Lee la transcripción, llama a Claude con el prompt del config
    y guarda picos.json filtrando por confianza_minima.
    """
    path = Path(transcripcion_path)
    if not path.exists():
        print(f"[AGENT1] ❌ No se encontró el archivo: {path}")
        sys.exit(1)

    prompt           = config["deteccion"]["prompt"]
    confianza_minima = config["deteccion"]["confianza_minima"]

    session_dir = path.parent
    text        = path.read_text(encoding="utf-8")
    word_count  = len(text.split())

    print(f"\n[AGENT1] Transcripción cargada — {word_count:,} palabras")
    print(f"[AGENT1] Confianza mínima : {confianza_minima}")
    print(f"[AGENT1] Prompt Caching activo para lore del nicho")

    client = anthropic.Anthropic()

    if word_count <= MAX_WORDS:
        print("[AGENT1] Procesando transcripción completa en una sola llamada...")
        peaks = _call_claude(client, text, prompt)
    else:
        segments = _parse_segments(text)
        chunks   = _split_into_chunks(
            segments,
            chunk_secs=CHUNK_MINUTES * 60,
            overlap_secs=OVERLAP_MINUTES * 60,
        )
        print(f"[AGENT1] Transcripción larga — {len(chunks)} chunks de {CHUNK_MINUTES} min")

        all_peaks = []
        for i, (offset, chunk_text) in enumerate(chunks):
            offset_ts = f"{offset // 60:02d}:{offset % 60:02d}"
            print(f"[AGENT1] Chunk {i + 1}/{len(chunks)} (desde {offset_ts})...")
            all_peaks.extend(_call_claude(client, chunk_text, prompt))

        peaks = _merge_peaks(all_peaks)

    # Filtrar por confianza mínima
    antes   = len(peaks)
    peaks   = [p for p in peaks if p.get("confianza", 0) >= confianza_minima]
    filtrados = antes - len(peaks)
    if filtrados:
        print(f"[AGENT1] Filtrados {filtrados} pico(s) bajo confianza {confianza_minima}")

    output_path = session_dir / "picos.json"
    output_path.write_text(
        json.dumps({"picos": peaks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[AGENT1] ✅ {len(peaks)} pico(s) guardados en {output_path}")

    return peaks


# ─────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("\nUso: python agent1_peak_detector.py <transcripcion.txt> [canal_id]")
        print("Ejemplo: python agent1_peak_detector.py stream_data/test/transcripcion_completa.txt papi_jhos\n")
        sys.exit(1)

    from contexto.config_loader import ConfigLoader

    canal_id = sys.argv[2] if len(sys.argv) >= 3 else None
    cfg      = ConfigLoader(config_dir=str(Path(__file__).parent.parent / "config"))
    config   = cfg.load(canal_id)

    print(f"[AGENT1] Canal : {cfg.get('meta', 'id')}  (config: {cfg.loaded_file.name})")

    peaks = run_agent(sys.argv[1], config)

    print(f"\n[AGENT1] {'─'*40}")
    print(f"[AGENT1] Picos detectados: {len(peaks)}")
    for p in peaks:
        print(f"  [{p.get('timestamp', '?')}] {p.get('razon', '')}  (confianza: {p.get('confianza', '?')})")
    print()
