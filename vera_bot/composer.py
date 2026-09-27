"""Dual-path composition: deterministic + LLM run in parallel, LLM selector picks the best.

Architecture:
    Input ──┬── Path A: deterministic (BM25 template + name swap) ──┐
            │                    parallel                            ├── LLM Selector ── winner
            └── Path B: LLM compose (from scratch with template ref)┘
                                                                   (timeout → Path A)

This gets the best of both worlds:
- Known triggers: deterministic wins on specificity, selector confirms it
- Novel triggers: LLM compose wins, selector picks it
- Timeout/failure: always falls back to deterministic (zero-risk)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from pydantic import BaseModel

from vera_bot import config
from vera_bot.deterministic import compose_deterministic
from vera_bot.fact_extractor import extract_all_facts
from vera_bot.llm_client import ComposedMessage, compose_message, classify_reply
from vera_bot.prompts import build_compose_system, build_compose_user
from vera_bot.retrieval import index as retrieval_index
from vera_bot.validators import finalize_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path A: deterministic
# ---------------------------------------------------------------------------

def _build_deterministic(
    template: dict[str, Any],
    facts: dict[str, Any],
    fallback_key: str,
) -> dict[str, str]:
    """Build a safe message using only the supplied live facts."""
    return compose_deterministic(facts, fallback_key, template)


# ---------------------------------------------------------------------------
# Path B: LLM compose
# ---------------------------------------------------------------------------

def _detect_language_from_facts(facts: dict[str, Any]) -> str:
    """Derive language preference from merchant/customer facts."""
    # Customer language pref takes priority
    cust = facts.get("customer")
    if cust and cust.get("language_pref"):
        pref = cust["language_pref"].lower()
        if "hi" in pref:
            return "hi-en"
    # Fall back to merchant languages
    langs = facts.get("merchant", {}).get("languages", [])
    if "hi" in langs:
        return "hi-en"
    return "en"


async def _build_llm(
    category: dict[str, Any],
    facts: dict[str, Any],
    trigger: dict[str, Any],
    matches: list[tuple[dict[str, Any], float]],
    customer: dict[str, Any] | None,
    detected_language: str = "en",
) -> dict[str, str] | None:
    """LLM composes from scratch using the template as structural reference.
    Returns None on failure."""
    if not config.ENABLE_LLM:
        return None
    try:
        system_prompt = build_compose_system(category, detected_language)
        user_prompt = build_compose_user(
            facts, trigger, matches, customer, mode="compose",
        )
        result: ComposedMessage = await compose_message(system_prompt, user_prompt)
        return result.model_dump()
    except Exception:
        logger.warning("LLM compose path failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Selector: pick the better message
# ---------------------------------------------------------------------------

_SELECTOR_SYSTEM = """\
You are picking the BETTER WhatsApp message for a merchant engagement bot.

Consider:
1. Specificity (concrete numbers/dates from merchant data)
2. Merchant fit (uses business name, locality, owner name — not just generic)
3. NO hallucination (if a message cites an offer/price not in the merchant's active offers, that is WORSE)
4. Trigger relevance (why NOW)
5. Engagement (compulsion levers, clear CTA)

IMPORTANT: A message that invents an offer the merchant doesn't have is WORSE than one that doesn't mention offers.

Return ONLY: {"pick": "A" or "B", "reason": "one sentence"}\
"""


def _build_selector_prompt(
    msg_a: str, msg_b: str, trigger_kind: str, category_slug: str,
    merchant_name: str, merchant_offers: list[str] | None = None,
    merchant_location: str = "",
) -> str:
    offers_str = ", ".join(merchant_offers) if merchant_offers else "NONE (no active offers)"
    return f"""Trigger: {trigger_kind} | Category: {category_slug}
Merchant: {merchant_name} | Location: {merchant_location}
Merchant active offers: {offers_str}

Message A:
"{msg_a}"

Message B:
"{msg_b}"

Which is better? If a message cites an offer not in the active offers list, penalize it. Return JSON: {{"pick": "A" or "B", "reason": "..."}}"""


class _Selection(BaseModel):
    pick: Literal["A", "B"]
    reason: str


async def _select_best(
    msg_a: dict[str, str],
    msg_b: dict[str, str],
    trigger: dict[str, Any],
    category: dict[str, Any],
    merchant_name: str,
    merchant_offers: list[str] | None = None,
    merchant_location: str = "",
) -> str:
    """Ask LLM to pick A or B. Returns 'A' or 'B'. Defaults to 'A' on failure."""
    try:
        from vera_bot.llm_client import _parse

        prompt = _build_selector_prompt(
            msg_a["body"], msg_b["body"],
            trigger.get("kind", ""), category.get("slug", ""),
            merchant_name, merchant_offers, merchant_location,
        )
        result = await _parse(
            model=config.CLASSIFY_MODEL,
            schema=_Selection,
            messages=[
                {"role": "system", "content": _SELECTOR_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=80,
            timeout=config.CLASSIFY_TIMEOUT,
        )
        logger.info("Selector picked %s: %s", result.pick, result.reason)
        return result.pick
    except Exception:
        logger.warning("Selector failed, defaulting to A (deterministic)", exc_info=True)
    return "A"


# ---------------------------------------------------------------------------
# Main compose entry point
# ---------------------------------------------------------------------------

async def compose_async(
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Dual-path compose: deterministic + LLM in parallel, selector picks winner."""

    # 1. Extract facts
    facts = extract_all_facts(category, merchant, trigger, customer)

    # 2. Retrieve best template + score
    matches = retrieval_index.query(trigger, category, top_n=2)
    top_template, top_score = matches[0] if matches else ({}, 0.0)

    # 3. Build suppression key
    fallback_key = str(
        trigger.get("suppression_key")
        or f"{trigger.get('kind', 'unknown')}:{trigger.get('id', '')}"
    )

    # 4 & 5. Path A (deterministic) and Path B (LLM) actually run concurrently:
    # Path A is CPU-only, so it is dispatched to a worker thread and awaited
    # alongside Path B's network call via asyncio.gather rather than being
    # built synchronously before Path B starts.
    lang = _detect_language_from_facts(facts)

    def _fallback_msg_a() -> dict[str, str]:
        return {
            "body": f"{facts['merchant']['name']}, Vera has an update for you. Reply YES to hear more.",
            "cta": "binary_yes_no",
            "send_as": "vera",
            "suppression_key": fallback_key,
            "rationale": "No template match; generic fallback.",
        }

    if top_template:
        det_task = asyncio.to_thread(_build_deterministic, top_template, facts, fallback_key)
    else:
        det_task = asyncio.to_thread(_fallback_msg_a)

    llm_task = _build_llm(category, facts, trigger, matches, customer, lang)

    msg_a, msg_b = await asyncio.gather(det_task, llm_task)

    # 6. Select the best + log the routing decision
    trigger_kind = trigger.get("kind", "unknown")
    merchant_name = facts["merchant"]["name"]
    template_id = top_template.get("id", "none") if top_template else "none"

    if msg_b is None:
        raw = msg_a
        route = "deterministic"
        reason = "LLM failed"
    elif top_score < config.BM25_CONFIDENCE_THRESHOLD:
        raw = msg_b
        route = "llm_compose"
        reason = f"novel trigger (BM25={top_score:.1f} < {config.BM25_CONFIDENCE_THRESHOLD})"
    else:
        pick = await _select_best(
            msg_a, msg_b, trigger, category,
            merchant_name,
            merchant_offers=facts["merchant"].get("active_offers"),
            merchant_location=facts["merchant"].get("location", ""),
        )
        raw = msg_b if pick == "B" else msg_a
        route = "llm_compose" if pick == "B" else "deterministic"
        reason = f"selector picked {pick} (BM25={top_score:.1f})"

    logger.info(
        "[COMPOSE] %s | trigger=%s | merchant=%s | route=%s | reason=%s | template=%s | model=%s | body=%s",
        trigger_kind, trigger.get("id", ""), merchant_name,
        route, reason, template_id, config.COMPOSE_MODEL,
        raw.get("body", "")[:80],
    )

    # 7. Enforce send_as for customer-scoped triggers
    trigger_scope = trigger.get("scope", "merchant")
    if trigger_scope == "customer" or customer is not None:
        raw["send_as"] = "merchant_on_behalf"

    # 8. Validate
    return finalize_message(raw, fallback_key=fallback_key)


def compose(
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Sync wrapper for compose_async(). Used by tools/generate_submission.py
    and the bot.py public contract. Do NOT call from inside FastAPI routes
    (use compose_async there)."""
    import asyncio
    return asyncio.run(compose_async(category, merchant, trigger, customer))
