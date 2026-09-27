# Vera Sentinel — Magicpin AI Challenge Submission

`Vera Sentinel` is an end-to-end, deployment-ready merchant engagement bot.
It accepts the judge's four context layers, produces concise WhatsApp messages,
and exposes the required FastAPI lifecycle endpoints.

## Why this design

The hot path is a deterministic, fact-anchored composer. Each trigger family
(performance movement, research/compliance, account state, events, competitor
activity, review signals, planning and customer reminders) has its own
composition route. This preserves exact merchant metrics, owned offers,
customer details and cited digest facts rather than paraphrasing or inventing
them.

An optional OpenAI or Gemini refinement path can be enabled for novel context
injections. It is disabled by default: the bot remains fast, deterministic and
fully usable without any credentials.

## Safety and conversation quality

- Only active merchant offers are mentioned; category offers are never treated
  as merchant inventory.
- Customer messages always send as the merchant and use the supplied customer
  relationship context.
- Per-merchant suppression, recent-body deduplication, an eight-message daily
  ceiling and unanswered-nudge backoff prevent spam.
- The reply router handles opt-outs, Hindi/English WhatsApp auto-replies,
  repeated canned responses, commit intent and off-topic requests.
- New context versions replace older ones, allowing the judge to inject fresh
  performance, digest and customer data mid-run.

## Run locally

```bash
python -m pip install -r requirements.txt
python tools/generate_submission.py
uvicorn bot:app --host 0.0.0.0 --port 8080
```

The committed `submission.jsonl` contains all 30 required test pairs. If
Python is not installed yet, regenerate it with:

```bash
node tools/generate_offline_submission.mjs
```

Set `VERA_TEAM_NAME`, `VERA_TEAM_MEMBERS` and `VERA_CONTACT_EMAIL` before
deployment. To opt into model refinement, provide `OPENAI_API_KEY` (or
`GEMINI_API_KEY` with `LLM_PROVIDER=gemini`) and set `VERA_ENABLE_LLM=true`.

## Tradeoffs and next context to request

The deterministic path gives reliable specificity and sub-second operation,
at the cost of less stylistic flexibility than a model-only system. The most
valuable additional inputs would be merchant-level historical conversion by
trigger family, verified available booking slots, and an approved category
phrase library for compliance-sensitive customer outreach.
