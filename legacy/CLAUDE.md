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

**Claude calls go through Claude Code headless by default** (`AI_PROVIDER=claude_cli`, `ai_client/cli_provider.py`): each agent call runs an isolated `claude -p` (no tools, no CLAUDE.md/memories, no MCP) using the machine's logged-in Claude Code session — no API key, no API spend. Requires Claude Code installed and logged in for the user that runs the pipeline/backend. Optional env: `AI_CLI_MODEL` (default `sonnet`), `AI_CLI_TIMEOUT` (seconds per call, default 600), `AI_CLI_PATH`. **Several Claude accounts (CLIP-83, `ai_client/perfiles.py`):** each profile is its own Claude Code config folder (`CLAUDE_CONFIG_DIR`) under `~/.clipeo/claude_perfiles/<name>` (outside the repo; override `AI_CLI_PERFILES_DIR`), logged in once by the operator (`$env:CLAUDE_CONFIG_DIR="<folder>"; claude auth login`); the active one is `AI_CLI_PERFIL` in `.env` (empty = default session), chosen in the web Configuración and re-read on every call, so a switch applies to the next call of a running pipeline. The app never sees tokens. Alternatives, kept decoupled: `AI_PROVIDER=anthropic` (real API, needs `ANTHROPIC_API_KEY`) and `AI_PROVIDER=manual` (file protocol, debugging only).

`.env` file (gitignored), all optional:
- `AI_PROVIDER` — `claude_cli` (default) | `anthropic` | `manual`.
- `ANTHROPIC_API_KEY` — only for `AI_PROVIDER=anthropic`.
- `HF_TOKEN` — enables speaker diarization in WhisperX. Without it, transcripts have no speaker labels.
- `COLAB_TRANSCRIBE_URL` / `COLAB_AUTH_TOKEN` — remote GPU transcription (`--colab`, always used by the web backend). The URL works with or without the `/transcribe` suffix, and both are re-read from `.env` on every transcription attempt (`video_transcriber._colab_config`), so fixing a stale tunnel URL mid-run is picked up by the next automatic retry.

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
- `--session-id <id>` (`--video` only; used by the web backend): use/resume `stream_data/<id>` without interactive prompts — also for local videos, so the session isn't created next to the file.
- `--reintentar <paso> [--chunk <id>[,<id>...]]`: reset that step and every later one (deleting what they produced) and resume. Without `--chunk`, applies to every chunk where that step is in error.

Every run is orchestrated as **steps** (`core/pasos.py`): session steps `descarga → plan → … → revision → fin`, and per chunk `transcripcion → agente0 → agente1 → agente2 → juez → agente3 → corte`. Each step's state, timing, error (retryable or not) and outputs live in `pipeline_estado.json`; steps already `ok` are skipped on resume. Retryable errors (Claude usage limit, Colab down, network) are retried automatically (`PIPELINE_ESPERAS_REINTENTO`, default `30,120,300` s); after that, or for non-retryable errors (config, credentials, missing input, private video), the step stays in `error` until `--reintentar`. A finished session ends with the `revision` step `esperando` — closed from the web's clip review.

**`--live` is currently non-functional**: it shells out to a `capture_pipeline.py` at the project root that no longer exists (it was moved to `archive/capture_pipeline.py`, an older v1.1 script using classic `whisper` instead of WhisperX). The supported path for live streams today is:

```
python captura/tiktok_capture.py --usuario @handle [--chunk 30m]   # records live to disk in chunks
python pipeline.py --video stream_data/<session>/chunk_001.mp4 --session-id <session>_c001 --config <canal_id>  # process each recorded chunk
```

Pass a distinct `--session-id` per recorded chunk: without it, a local video's session is its parent folder, so every `chunk_NNN.mp4` of the same recording would share one `pipeline_estado.json` (the second chunk would see the first one's steps as done).

Other standalone tools:
- `contexto/feedback.py --session <session_id>` — collect human feedback on generated clips, distilled by Claude into `aprendizajes/<canal_id>_optimizado.md` (fed back into Agent 3's prompt).
- `entrenamiento/clip_manual.py --video ... --inicio ... --fin ... --linea1 ... --linea2 ...` — cut one manual clip bypassing agents 1–4.
- `contexto/contexto_refresh.py <entidad_id>` — web-search recent news about an entity and save approved findings as context events. **Deprecated in practice (2026-07-31)**: spends real API budget (web search runs inside the Claude API call). Prefer asking a Claude Code agent to research directly in-session (own `WebSearch`, no `ANTHROPIC_API_KEY` spend) and save in the same file format — see `.claude/skills/seo-refresh/SKILL.md` for this pattern applied to per-platform SEO hashtags.
- Ctrl+C during `--video` processing stops the in-flight step and leaves it `pendiente`; every finished step is checkpointed in `pipeline_estado.json` and the next run resumes from there.

Web panel (operates the same pipeline; see `backend/docs/ARQUITECTURA.md`, `backend/docs/API.md`):
```
cd backend && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev          # http://localhost:5173
```
Sessions list → session detail with one circle per step (click: state, error, Claude REQUEST/RESPONSE, outputs, "Reintentar desde este paso") → "Revisión" circle opens clip review (approve/edit/discard) → "Finalizar revisión" closes `fin`. "Errores" lists every failed step across sessions with bulk retry. The backend launches `pipeline.py` as a subprocess (own process group, `stdin` null, unbuffered) and records runs in `backend/runs_logs/runs.json`, so a backend restart doesn't lose track of a running pipeline.

**Publication** (`backend/app/publicacion/`, web "Publicaciones", one tab per platform): every clip approved in the review enters its niche's queue on each platform — TikTok and YouTube Shorts, independent queues (own account, schedule, order, pauses) driven by the same engine (SQLite `backend/publicacion.db`, gitignored). YouTube (`youtube.py`, Data API v3 resumable upload) sends title/description/tags from Agent 3, directly as **public** (Google says unaudited API projects get locked private; the real visibility is read back and a mismatch is logged as an error event), and responsibility ends at `uploadStatus = processed`; OAuth returns straight to the backend (`YOUTUBE_CLIENT_ID/SECRET` in Configuración). The rest of this paragraph describes TikTok. A thread in the backend checks at startup and then every 10 min aligned to the clock (xx:00, xx:10…, so `horarios.estimar` can show the exact send time of each queued clip) and, per account, sends one clip per slot (8/12/16/20 Lima, quiet 22:00–08:00, missed slots not recovered) to TikTok as an **inbox draft** (Content Posting API Upload flow — unaudited apps can't post publicly); the user activates it in the app. Responsibility ends when TikTok confirms `SEND_TO_USER_INBOX`. Every TikTok call and state change is an event (no tokens). Never resend blindly: `publish_id` saved before upload, orphaned sends are re-checked with TikTok. Accounts are `real` (OAuth by pasting the redirect URL; `TIKTOK_CLIENT_KEY/SECRET/REDIRECT_URI` in Configuración) or `simulado` (no network; `PUBLICACION_SIMULAR_FALLA` injects failures). `PUBLICACION_MOTOR=0` disables the thread; `PUBLICACION_DB` points to another DB. Details: `backend/docs/ARQUITECTURA.md` §Publicación.

Each Claude-calling agent (0-3) is also runnable standalone on an intermediate JSON/txt file from a previous stage, for iterating on one prompt/config without re-running the whole pipeline:
```
python agentes/agent1_peak_detector.py <transcripcion.txt> [canal_id]
python agentes/agent2_range_refiner.py <picos.json> [canal_id]
python agentes/agent3_viral_scorer.py <rangos.json> [canal_id]
python edicion_video/agent4_video_cutter.py <contenido.json>   # no canal_id — doesn't use config
```

## Testing

```
pytest                    # all tests; no network calls, no Claude calls (HTTP mocked with requests-mock, `claude` CLI subprocess mocked)
pytest tests/test_ai_client.py -v
pytest tests/test_ai_client.py::test_manual_client_timeout
```

## Configuration systems

Two config systems coexist, auto-selected per `canal_id` (see docs/ARQUITECTURA.md §4 for detail):
- **v1 — `ConfigLoader`**, plain YAML under `config/`: either `config/<canal_id>.yaml` (single file) or `config/<canal_id>/_index.yaml` + per-character YAMLs (ecosystem).
- **v2 — `ContextLoader`**, modular YAML under `contexto/`: `contexto/nichos/<id>.yaml` + `contexto/entidades/<id>.yaml` + `contexto/eventos/<YYYY-MM>/*.yaml`. Takes priority if `contexto/nichos/<canal_id>.yaml` exists.

Both expose the same interface to the agents (`get()`, `loaded_file`, `get_ecosystem_type()`, `enrich_with_speakers()`), so agents don't know or care which one loaded the config.

## Pipeline stages (per chunk, `--video` mode)

```
audio extraction → WhisperX transcription → name cleanup → Agent 0 (speaker ID)
  → Agent 1 (detect, broad) → Agent 2 (borders) → Juez (only quality filter + title) → Agent 3 (copy of approved) → Agent 4 (video cutting)
```

Agents 1–3 call Claude and are driven entirely by the resolved `config` dict (prompts, thresholds, hashtags). Agent 4 is pure FFmpeg/technical — no Claude, no config. Agent 0 runs only when the transcript has speaker diarization; a "possible" (0.40–0.69) speaker whose name matches the channel owner (uploader) is applied as `confirmado_por_canal`.

**Search broad → decide strict.** When the niche has a memory file (`investigacion/<canal_id>/referencias.yaml`), Agent 1 searches broadly with it (memory block in the prompt, `confianza_minima_con_juez` default 0.5 instead of 0.75) and Agent 2 only sets borders ("start in the conflict"; it no longer discards for quality — only duplicates or moments with no text). The Juez is the only quality filter, and Agent 3 then writes the copy (descriptions, hashtags, style) **only for approved clips, from the Juez's title** (`run_copy`). Without a memory file, the flow is the old one: Juez skipped, Agent 3 scores and titles.

**Juez** (`agentes/juez.py`) makes the final call per chunk: it sees all of Agent 2's ranges together and decides against the niche **memory** `investigacion/<canal_id>/referencias.yaml` (real TikTok clips measured by outlier = views ÷ account median): forced type of viral moment (or "ninguno"), what is at stake, the 2 nearest real references, publish or not (no cap), strength 1–10 (becomes `score`) and a title that names the character. It writes `chunks/<id>/juez.json` (each decision carries its full range). It also receives the editor's corrections: approve/edit/discard in the web review append to `investigacion/<canal_id>/correcciones.jsonl` (`investigacion/comun.py`), and the last 30 go into the Juez prompt. `python -m agentes.auditoria <session_id> [--chunk id]` lists moments of working types that never reached the Juez (coverage check, writes `auditoria.json`).

Niche research that builds that memory lives in `investigacion/` (see docs/COMANDOS.md, "Investigación del nicho"): `recolectar.py` (metrics of the accounts in `cuentas.yaml` → `videos.jsonl`), `muestrear.py` (top/bottom clips → `muestra/`, gitignored), `transcribir_muestra.py` (Colab). `referencias.yaml` itself is curated by Claude in-session from those files (frames + transcripts), not generated.

## Output structure

```
stream_data/<session_id>/            (session_id = YYYYMMDD_HHMMSS, or tiktok_<user>_<timestamp>)
  metadata.json                      yt-dlp video metadata
  stream_completo.mp4 / audio/       downloaded source video + audio
  pipeline_estado.json               chunk plan + per-step state (resumable; what the web draws as circles)
  chunks/<chunk_id>/
    transcripcion_raw.txt            WhisperX output, real timestamps
    transcripcion_enriquecida.txt    after Agent 0 speaker-name resolution
    picos.json / rangos.json / contenido.json   Agent 1 / 2 / 3 outputs (contenido.json final after the Juez)
    juez.json                         Juez verdict per candidate (type, stakes, nearest references, publish, full range)
    auditoria.json                    on-demand coverage audit (agentes/auditoria.py)
    trazas/<paso>/NNN_request.json + NNN_response.json (or NNN_error.json)   every Claude call of that step
  contenido_chunks/<chunk_id>.json   per-chunk content summary (post --revisar if used); each clip entry carries its "clip_id"
  contenido_final.json               merge of all chunks, sorted by score
  clips/clip_c<NNN>_<NN>.mp4 + .json  Agent 4 output, named per chunk (clip_c002_01...) so retrying one chunk's cut never renumbers others; sessions before 2026-09-30 use global clip_NNN (core/clip_ids.py reads both)
  clips_custom/                      manual clips from entrenamiento/clip_manual.py
```
