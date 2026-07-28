# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

A pipeline that downloads TikTok/video content, transcribes it (WhisperX), and runs it through a chain of Claude-based agents to detect viral moments, refine their exact boundaries, score/caption them, and cut them as vertical (9:16) clips with burned-in subtitles ready for TikTok/Shorts/Reels.

For full architectural detail (components, data flow, session persistence, known gaps), see **[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md)**. Command reference: **[docs/COMANDOS.md](docs/COMANDOS.md)**. Data/config file schemas: **[docs/ESTRUCTURA_DATOS.md](docs/ESTRUCTURA_DATOS.md)**. How the system learns from feedback over time: **[docs/APRENDIZAJE.md](docs/APRENDIZAJE.md)**. This section only covers what's needed to run and orient in the codebase.

## Dependencies

```
pip install -r requirements.txt
```

Includes `yt-dlp`, `whisperx` (transcription + diarization — not `openai-whisper`, which is only used by the archived v1.1 script), `anthropic`, `python-dotenv`, `pyyaml`.

ffmpeg must be installed system-wide (https://ffmpeg.org/download.html). `core/utils.py::setup_ffmpeg_path()` also injects a hardcoded WinGet ffmpeg path into `PATH` for this machine.

Requires a `.env` file (gitignored) with:
- `ANTHROPIC_API_KEY` — required by all Claude-calling agents.
- `HF_TOKEN` — optional; enables speaker diarization in WhisperX. Without it, transcripts have no speaker labels.

## Running

Main entry point is `pipeline.py`, with three mutually exclusive modes:

```
python pipeline.py --video <url_or_local_path> [--config <canal_id>] [--revisar]
python pipeline.py --test  stream_data/<session_id>/    [--config <canal_id>]
python pipeline.py --live  <url>   # currently broken — see note below
```

- `--config` selects a channel/niche config (see below). Omitted → `config/default.yaml`.
- `--revisar` pauses before cutting each clip for manual approval/edit/discard via terminal.
- `--test` skips capture/transcription and runs agents 1→4 directly on an existing `transcripcion_completa.txt` in the given session directory.

**`--live` is currently non-functional**: it shells out to a `capture_pipeline.py` at the project root that no longer exists (it was moved to `archive/capture_pipeline.py`, an older v1.1 script using classic `whisper` instead of WhisperX). The supported path for live streams today is:

```
python tiktok_capture.py --usuario @handle [--chunk 30m]   # records live to disk in chunks
python pipeline.py --video stream_data/<session>/chunk_001.mp4 --config <canal_id>  # process each recorded chunk
```

Other standalone tools:
- `feedback.py --session <session_id>` — collect human feedback on generated clips, distilled by Claude into `aprendizajes/<canal_id>_optimizado.md` (fed back into Agent 3's prompt).
- `clip_manual.py --video ... --inicio ... --fin ... --linea1 ... --linea2 ...` — cut one manual clip bypassing agents 1–4.
- `contexto_refresh.py <entidad_id>` — web-search recent news about an entity and save approved findings as context events.
- Ctrl+C during `--video`/`--live` processing waits for the in-flight chunk, then stops; chunk progress is checkpointed in `pipeline_estado.json` and resumable.

## Configuration systems

Two config systems coexist, auto-selected per `canal_id` (see docs/ARQUITECTURA.md §4 for detail):
- **v1 — `ConfigLoader`**, plain YAML under `config/`: either `config/<canal_id>.yaml` (single file) or `config/<canal_id>/_index.yaml` + per-character YAMLs (ecosystem).
- **v2 — `ContextLoader`**, modular YAML under `contexto/`: `contexto/nichos/<id>.yaml` + `contexto/entidades/<id>.yaml` + `contexto/eventos/<YYYY-MM>/*.yaml`. Takes priority if `contexto/nichos/<canal_id>.yaml` exists.

Both expose the same interface to the agents (`get()`, `loaded_file`, `get_ecosystem_type()`, `enrich_with_speakers()`), so agents don't know or care which one loaded the config.

## Pipeline stages (per chunk, `--video` mode)

```
audio extraction → WhisperX transcription → name cleanup → Agent 0 (speaker ID)
  → Agent 1 (peak detection) → Agent 2 (range refinement) → Agent 3 (scoring + copy) → Agent 4 (video cutting)
```

Agents 1–3 call Claude and are driven entirely by the resolved `config` dict (prompts, thresholds, hashtags). Agent 4 is pure FFmpeg/technical — no Claude, no config. Agent 0 runs only when the transcript has speaker diarization.

## Output structure

```
stream_data/<session_id>/            (session_id = YYYYMMDD_HHMMSS, or tiktok_<user>_<timestamp>)
  metadata.json                      yt-dlp video metadata
  stream_completo.mp4 / audio/       downloaded source video + audio
  pipeline_estado.json               chunk plan + progress checkpoint (resumable)
  chunks/<chunk_id>/
    transcripcion_raw.txt            WhisperX output, real timestamps
    transcripcion_enriquecida.txt    after Agent 0 speaker-name resolution
    picos.json / rangos.json / contenido.json   Agent 1 / 2 / 3 outputs
  contenido_chunks/<chunk_id>.json   per-chunk content summary (post --revisar if used)
  contenido_final.json               merge of all chunks, sorted by score
  clips/clip_NNN.mp4 + .json          Agent 4 output, continuous numbering across chunks
  clips_custom/                      manual clips from clip_manual.py
```
