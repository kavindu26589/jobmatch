# Agentic Job-Matching System

A production-grade job-matching agent: parse a resume into a structured
profile, discover **live jobs from the internet** (no-key sources), rank them
against the profile, and produce a concrete **resume-improvement plan**.

Built on [`opencode-gateway`](./gateway), an engine-agnostic LLM gateway that
is compatible with OpenCode API keys and `opencode.json` provider configs, so
**any third-party system can reuse the LLM layer** with its own keys.

## What it does

1. **Analyze** a resume (PDF/DOCX/TXT/MD) → structured ATS-style profile
   (skills, experience, years, target titles, summary).
2. **Search** live job boards for matching openings (Remotive, Greenhouse,
   Lever, optional USAJobs — all without paid keys).
3. **Score** each job against the profile: hybrid lexical fit + LLM scoring,
   with a deterministic missing-keywords breakdown.
4. **Improve** — diagnose weak resume sections and prescribe concrete edits
   with before/after rewrites, prioritized by impact.
5. **Agent** — an autonomous ReAct loop (`LangGraph`) that chains the tools
   above to answer natural-language goals like *"which backend roles fit me
   best and what should I change?"*.

## Repository layout

| Path | Contents |
| --- | --- |
| `gateway/` | `opencode-gateway` pip package — LLM access, retries, rate limiting, circuit breaker, usage ledger, structured output. Reusable standalone. |
| `app/` | `jobmatcher` pip package — resume parsing, job sources, matching, reporting, CLI, FastAPI server, and the LangGraph agent. |
| `tests/` | Shared pytest suite for both packages (offline; `live` marker excluded by default). |
| `docker/` | Production image for the HTTP server. |

## Prerequisites

- Python **>= 3.11**
- An OpenCode Zen API key from https://opencode.ai/auth (default provider), or
  a key for any provider in the gateway registry (OpenAI, Anthropic,
  OpenRouter, Ollama, custom).

## Install

```bash
pip install -e gateway -e "app[dev]"
cp .env.example .env   # then fill in OPENCODE_API_KEY
```

`app[dev]` adds the dev toolchain (pytest, respx, ruff, mypy).

## Quickstart

```bash
# Analyze a resume into a structured profile
jobmatcher analyze --resume resume.pdf

# Search live job boards
jobmatcher search --query "python backend" --location "Remote" --limit 20

# Full pipeline: analyze + search + score + improvement plan
jobmatcher match --resume resume.pdf --query python --save

# Autonomous agent in natural language
jobmatcher agent --resume resume.pdf "Which backend roles fit me best?"

# HTTP API server + browser UI (http://127.0.0.1:8000)
jobmatcher serve
```

Open `http://127.0.0.1:8000` for the built-in web UI (React):

1. **CV** — drop your resume (PDF / DOCX / TXT / MD / RTF). The server extracts
   the text, caches the original file, and you can edit the text directly.
2. **Jobs** — search live job boards and see a list of openings ranked by how
   well they match your CV (fit %). Expand any job for **"How to match this
   job"**: the LLM names the exact CV parts to change (summary, skills,
   experience…) with before→after rewrites you can *Accept* straight into the
   CV (undoable, then exported).
3. **Improve** — the pipeline analyzes the CV, searches live jobs, scores fit,
   and lists *which* parts to optimize and *how* (per-section rewrites, missing
   keywords, priority actions). Accept an edit to apply the rewrite to the CV.
4. **Agent** — a natural-language agent that plans its own tool calls over your CV.
5. **Download CV** — the edited text is exported back to a file; it defaults to
   the *same format you uploaded* (`.pdf`, `.docx`, `.txt`, `.md`, `.rtf`).

Building the UI: `cd web && npm install && npm run build` (output lands in
`app/src/jobmatcher/server/static/`, which the server serves and the wheel
ships). For development `cd web && npm run dev` serves the app on :5173 and
proxies the API to FastAPI on :8000. The UI needs no external CDNs.

API docs live at `/docs` (Swagger) and the raw spec at `/openapi.json`.

## HTTP API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Browser UI (React SPA). |
| `GET` | `/health` | Liveness + configured provider/sources. |
| `POST` | `/api/v1/upload` | Multipart resume upload → extracted text + cached file. |
| `GET` | `/api/v1/cv/{id}/file` | Original uploaded bytes (for side-by-side preview). |
| `GET` | `/api/v1/cv/{id}/positions` | Per-page word boxes + `editable` flag (PDF/DOCX only). |
| `POST` | `/api/v1/cv/export` | Edited text → file in the upload's format (or `as_format`). |
| `POST` | `/api/v1/analyze` | Resume → structured profile. |
| `POST` | `/api/v1/search` | Live job search (no matching). |
| `POST` | `/api/v1/match` | Full pipeline (analyze + search + score + improve). |

`POST /api/v1/match` returns each match with a `score.improvement` block: a
per-job summary plus actions that tell you **which CV parts to update** for that
specific job (`area`, `advice`, and optional `original` / `rewritten` pairs the
UI can apply directly). Advice requires a working `OPENCODE_API_KEY`; jobs scored
lexically-only still get keyword-based guidance via a fallback.
| `POST` | `/api/v1/agent` | Autonomous agent for natural-language goals. |
| `POST` | `/api/v1/report` | Like `match`, but persists Markdown + JSON to `REPORT_DIR`. |

Set `SERVER_API_KEY` to require `Authorization: Bearer <key>` (or
`X-API-Key`). Per-IP rate limiting is enabled via `SERVER_RATE_LIMIT_PER_MIN`.

## Configuration

See [`.env.example`](./.env.example) for every variable: gateway provider/keys,
cost limits, job sources, server auth/rate limits, and report output. Settings
are read from environment variables (pydantic-settings), so the same config
drives the CLI and the server.

## Docker

```bash
cp .env.example .env        # fill in OPENCODE_API_KEY
docker compose up --build   # http://127.0.0.1:8000
```

Reports are written to a named volume (`reports`). The image runs as a
non-root user and exposes a `/health` healthcheck.

## Development

```bash
# tests (offline; everything is mocked with respx/FakeGateway)
pytest -q -m "not live"

# lint + formatting + types
ruff check gateway app tests
ruff format --check gateway app tests
mypy gateway/src app/src
```

Optional live smoke test of real job boards (network access):

```bash
pytest -m live
```

## License

MIT.