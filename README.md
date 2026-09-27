# Vera Sentinel — Magicpin AI Challenge

Vera Sentinel is a context-aware merchant engagement engine built for the Magicpin Vera challenge. It accepts merchant, category, trigger, and optional customer context, then produces a concise next action with a message, CTA, sender identity, suppression key, and rationale.

## What it does

The engine combines deterministic, fact-grounded composition with optional Gemini/OpenAI refinement.

- Uses merchant context and trigger data to keep messages specific and grounded.
- Uses BM25 retrieval to select relevant messaging patterns.
- Supports customer-scoped reminders and merchant-facing growth actions.
- Applies suppression keys, recent-body deduplication, send caps, and unanswered-nudge backoff.
- Handles merchant replies, opt-outs, common WhatsApp auto-replies, and conversation state.
- Supports fresh context versions through the FastAPI context endpoint.
- Includes a deterministic `submission.jsonl` with the 30 required test cases.

## Project structure

```text
.
├── bot.py
├── requirements.txt
├── pyproject.toml
├── submission.jsonl
├── vera_bot/
│   ├── composer.py
│   ├── deterministic.py
│   ├── fact_extractor.py
│   ├── retrieval.py
│   ├── reply_handler.py
│   ├── routes.py
│   ├── store.py
│   └── ...
├── dataset/
├── expanded/
├── tests/
└── tools/
```

## API

The application exposes the following endpoints under `/v1`:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/v1/healthz` | Health and runtime status |
| HEAD | `/v1/healthz` | Health check for monitors |
| GET | `/v1/metadata` | Team, model, approach and version metadata |
| POST | `/v1/context` | Add or update context |
| POST | `/v1/tick` | Generate actions for available triggers |
| POST | `/v1/reply` | Process a merchant reply and decide the next action |

Interactive API documentation is available at `/docs` when the server is running.

## Run locally

Python 3.12 or newer is required.

### Install

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Then install dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Start the API

```bash
uvicorn bot:app --host 0.0.0.0 --port 8080
```

Open:

```text
http://127.0.0.1:8080/docs
```

## LLM configuration

The deterministic path works without external credentials and is the default.

To enable optional Gemini refinement, set these environment variables:

```text
VERA_ENABLE_LLM=true
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-3-flash-preview
```

For OpenAI, set `LLM_PROVIDER=openai` and provide `OPENAI_API_KEY` and `OPENAI_MODEL` instead.

Do not commit `.env` or API keys to source control.

## Validation and tests

Validate the 30-row submission contract:

```bash
python tools/validate_submission.py
```

Run the test suite:

```bash
python -m pytest
```

Start the server and run the HTTP smoke test:

```bash
python tools/smoke_endpoints.py http://127.0.0.1:8080
```

A healthy local build should report successful validation, all tests passing, and `smoke passed`.

## Submission

`submission.jsonl` contains the 30 deterministic test outputs required by the challenge. The file is intentionally kept deterministic so it can be replayed and validated consistently.

## Deployment

The project can be deployed as a standard Python web service. For Render, use:

```text
Build command:
pip install -r requirements.txt

Start command:
uvicorn bot:app --host 0.0.0.0 --port $PORT
```

Configure the required LLM environment variables in the hosting platform rather than storing credentials in the repository.

## Design trade-offs

The deterministic path prioritizes factual grounding, repeatability, predictable latency, and safe fallback behavior. Optional LLM refinement provides additional language flexibility when external model access is enabled.
