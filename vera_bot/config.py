from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Team
TEAM_NAME = os.environ.get("VERA_TEAM_NAME", "Vera Sentinel")
TEAM_MEMBERS: list[str] = [name.strip() for name in os.environ.get("VERA_TEAM_MEMBERS", "Candidate").split(",") if name.strip()]
CONTACT_EMAIL = os.environ.get("VERA_CONTACT_EMAIL", "")
APPROACH = "hybrid-bm25-retrieval-plus-llm-composer"

# LLM Provider: "openai" or "gemini"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()

# Gemini
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# OpenAI (fallback / selector)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

# Resolved model names based on provider
if LLM_PROVIDER == "gemini":
    COMPOSE_MODEL = GEMINI_MODEL
    CLASSIFY_MODEL = GEMINI_MODEL
    MODEL_NAME = f"{GEMINI_MODEL} (compose + classify)"
else:
    COMPOSE_MODEL = OPENAI_MODEL
    CLASSIFY_MODEL = OPENAI_MODEL
    MODEL_NAME = f"{OPENAI_MODEL} (compose + classify)"

# Offline mode is the safe default. It makes every endpoint fully usable without
# credentials and avoids a network timeout during the judge warm-up. Set
# VERA_ENABLE_LLM=true and provide the selected provider's API key to enable
# the optional refinement and reply-classification path.
_provider_key = GEMINI_API_KEY if LLM_PROVIDER == "gemini" else OPENAI_API_KEY
ENABLE_LLM = os.environ.get("VERA_ENABLE_LLM", "false").lower() in {"1", "true", "yes"} and bool(_provider_key)

COMPOSE_TEMPERATURE = 0.3
CLASSIFY_TEMPERATURE = 0.0
COMPOSE_TIMEOUT = 15.0 if LLM_PROVIDER == "gemini" else 8.0
CLASSIFY_TIMEOUT = 15.0 if LLM_PROVIDER == "gemini" else 5.0
COMPOSE_MAX_TOKENS = 500
CLASSIFY_MAX_TOKENS = 100

# Retrieval
BM25_CONFIDENCE_THRESHOLD = 3.5

# Message constraints
MAX_BODY_CHARS = 320
MAX_ACTIONS_PER_TICK = 20
ANTI_REPEAT_WINDOW = 5
ALLOWED_SEND_AS = {"vera", "merchant_on_behalf"}
