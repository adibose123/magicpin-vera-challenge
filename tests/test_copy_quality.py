import json
import re
from pathlib import Path

from vera_bot.composer import compose

ROOT = Path(__file__).resolve().parents[1]
EXPANDED = ROOT / "expanded"


def load(scope: str, context_id: str) -> dict:
    folder = {"category": "categories", "merchant": "merchants", "trigger": "triggers", "customer": "customers"}[scope]
    return json.loads((EXPANDED / folder / f"{context_id}.json").read_text(encoding="utf-8"))


def compose_pair(test_id: str) -> dict:
    pairs = json.loads((EXPANDED / "test_pairs.json").read_text(encoding="utf-8"))["pairs"]
    pair = next(p for p in pairs if p["test_id"] == test_id)
    merchant = load("merchant", pair["merchant_id"])
    category = load("category", merchant["category_slug"])
    trigger = load("trigger", pair["trigger_id"])
    customer = load("customer", pair["customer_id"]) if pair.get("customer_id") else None
    return compose(category, merchant, trigger, customer)


def test_customer_refill_formats_date_and_honors_hindi_pref():
    body = compose_pair("T07")["body"]
    assert "2026-04-28" not in body
    assert "28 Apr" in body
    assert "ka refill" in body


def test_placeholder_event_does_not_leak_trigger_kind():
    body = compose_pair("T19")["body"]
    assert "festival_upcoming" not in body
    assert "event name" in body


def test_placeholder_milestone_does_not_claim_unknown_number():
    body = compose_pair("T23")["body"]
    assert "new milestone" not in body.lower()
    assert "missing the number" in body.lower()


def test_placeholder_performance_uses_available_signal():
    body = compose_pair("T27")["body"]
    assert "5%" in body
    assert "performance is up in the latest window" not in body.lower()


def test_compliance_message_contains_human_dates_only():
    body = compose_pair("T30")["body"]
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}(?:T[^\s,.)]+)?", body)
    assert "15 Dec" in body
    assert "1.0 mSv" in body or "1.0" in body


def test_competitor_uses_positive_review_proof():
    body = compose_pair("T09")["body"]
    assert "5 reviews mention how clearly you explain treatment" in body
    assert "wait time" not in body.lower()


def test_category_customer_voice_differs_for_hindi_salon():
    body = compose_pair("T04")["body"]
    assert "Aapka appointment kal hai" in body
    assert "Beauty Lounge by Renu" in body


def test_all_submission_bodies_stay_well_below_truncation_limit():
    rows = [json.loads(line) for line in (ROOT / "submission.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 30
    assert all(len(row["body"]) <= 300 for row in rows)
    assert all(not row["body"].endswith("Want.") for row in rows)
    assert all(("YES/STOP" not in row["body"] or row["body"].endswith("YES/STOP")) for row in rows)
