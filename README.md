# Acadza AI Report-to-Fix

An existing Python triage engine and faculty console for JEE/NEET question-error reports. It combines deterministic detectors and guards with three optional LLM stages; LLM output is always a proposal, never a production question-bank write.

## Architecture

```text
reports + questions
  -> comment screening + deterministic detectors
  -> blind solver (stem/options only)
  -> judge (record + findings + reports + blind solve)
  -> Python guards and routing
  -> reply consistency check / optional reply generator
  -> results, run log, evaluation snapshot, review console
```

- `engine/records.py` normalizes the source JSON; `detectors.py`, `comments.py`, and `guards.py` are deterministic.
- `engine/llm.py` provides Groq, optional Anthropic, and hash-checked replay modes.
- `engine/run.py` groups reports by question, executes the pipeline, and writes namespaced output files.
- `engine/replay/` contains the original Claude-authored offline recordings. They are retained as a comparison baseline and are not live Claude API output or verified ground truth.
- `api/main.py` is an optional FastAPI/SQLite report-ingestion and faculty-decision service. Approval only records a faculty decision; question-bank publishing is deliberately not implemented.
- `console/` is a static faculty console. Its original sample queue is a browser-only demo; the Backend drawer connects to the API inbox when available.

The original baseline remains in `results.json`, `run_log.json`, `findings_unreported.json`, `console/data.json`, `data/questions.patched.json`, and `engine/replay/`. Live Groq runs write separate `_groq` outputs and `engine/replay_groq/`.

## Install and configure

Python 3.10+ is recommended. On Windows, use an installed supported version explicitly:

```powershell
py -3.12 -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `GROQ_API_KEY` in your local `.env` (or the process environment). `.env` is ignored by Git. `.env.example` contains placeholders only. Never put credentials in source code or frontend configuration. The default configuration is:

```dotenv
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-120b
GROQ_API_KEY=
ACADZA_MODE=replay
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
```

`python-dotenv` loads `.env` for local runs. Live requests use the Groq SDK, Chat Completions, strict JSON Schema response format, a timeout and bounded retries for rate limits/transient outages. Invalid JSON gets one controlled retry; schema-invalid output is rejected. Authentication and provider failures are reported explicitly and never switch the run to replay. Optional per-million-token prices can be configured in `.env` to estimate cost; otherwise cost is `null`.

Anthropic remains available by setting `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, and optionally `ANTHROPIC_MODEL`. The solver, judge, and reply prompt wording is shared between providers.

## Run the pipeline

### Original Claude replay

```powershell
py -3.12 -m engine.run
```

By default this replays the original hash-checked Claude recordings but writes to `results_replay.json`, `run_log_replay.json`, `findings_unreported_replay.json`, `console/data.replay.json`, and `data/questions.patched.replay.json`. It does not overwrite the original baseline. Use `--output-suffix <name>` to choose another output namespace.

### One-request live smoke test

```powershell
py -3.12 -m engine.run --smoke-test
```

This makes one solver request and prints the actual provider and model returned. Run it before a full live evaluation. If no key is configured, it exits with an explicit configuration error; no API result is fabricated.

### Full Groq evaluation

After the smoke test succeeds:

```powershell
py -3.12 -m engine.run --live --record
py -3.12 tools/evaluate_groq.py
```

Groq outputs are written to `results_groq.json`, `run_log_groq.json`, `findings_unreported_groq.json`, `data/questions.patched.groq.json`, and `console/data.groq.json`; new recordings go to `engine/replay_groq/`. These are separate from the original Claude files.

`evaluation_groq_vs_claude.json` reports model agreement separately from correctness. The repository has no independently verified full-set ground-truth labels; quality metrics such as classification accuracy, false-positive/negative rate, answer-key accuracy, repair correctness, and auto-apply precision remain `null` until verified labels are supplied as `data/ground_truth.json`. Operational rates, API failures, token counts, and latency are reported when a Groq run exists. Estimated cost is `null` unless token prices are configured.

To replay Groq recordings without making API calls:

```powershell
py -3.12 -m engine.run --replay-set groq --output-suffix groq_replay
```

This is replay, not a live Groq evaluation.

## Backend and faculty console

Start the API (SQLite is created at `data/acadza.sqlite3` by default):

```powershell
py -3.12 -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

OpenAPI documentation is at `http://127.0.0.1:8000/docs`; health is at `/health`. The API implements report intake/list/detail/process, decision retrieval/approval/rejection, and audit history. Exact duplicate comments for the same question are idempotent. Processing runs in a background task and stores proposed decisions, provider metadata, and errors in SQLite.

Serve the static console in another terminal:

```powershell
py -3.12 -m http.server 8765 --directory console
```

Open `http://127.0.0.1:8765`. The Backend drawer submits reports and connects to the API for processing, decisions, and server audit history. Override the API base URL with `?api=https://your-api.example`. No provider key is sent to browser code.

The static sample queue remains a demonstration: its approve/edit/reject/reply actions are stored in browser `localStorage` and do not update the API, send messages, or publish questions. Only actions in the Backend inbox are persisted by the API, and even API approval does not publish an edit or send a reply.

## Safety and production boundaries

- Solver input excludes answer key, stored solution, and report text.
- The model proposes structured edits only; Python enforces taxonomy and field scopes, anchors, answer/question-type checks, confidence thresholds, injection blocking, and repair-specific invariants.
- Missing distractors and other non-derivable authored content are not invented or auto-applied.
- No engine or API path writes to the production question bank.
- API CORS is restricted to local console origins by default. The minimal API has no faculty authentication and is intended for local/demo use; deployment requires an identity-aware access layer, managed secrets, HTTPS, database backups, and operational monitoring before external access.

## Tests

```powershell
py -3.12 -m unittest discover -s tests -t .
```

Provider responses are mocked in unit tests; the suite uses no API credits. The existing safety and detector tests remain in place.

## Existing baseline snapshot

The checked-in original evaluation contains 44 reports on 39 reported questions and 18 unreported findings. Its recorded outcomes include 19 `auto_apply`, 8 `faculty_review`, and 17 `no_change` routes. These are outputs of the original offline replay, not verified production changes or independently labeled accuracy metrics.

See [PROMPTS.md](PROMPTS.md) for the actual prompts, recorded-development history, and provider compatibility notes; [PRODUCT.md](PRODUCT.md) for the review flow, safety model, and production roadmap; [BRIEF.md](BRIEF.md) for the original assignment.
