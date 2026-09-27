"""Credential-free, fact-anchored message composer.

The deterministic path is intentionally conservative: it only renders facts that
exist in the supplied category, merchant, trigger and customer contexts. It is
also the zero-network fallback used when the optional LLM path is disabled or
fails.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "label" in value:
            return _text(value["label"])
        return ", ".join(f"{k}: {_text(v)}" for k, v in value.items() if _text(v))
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value if _text(item))
    return str(value).strip()


def _humanize(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    text = text.replace("_", " ")
    text = re.sub(r"\b(\d+)\s+month\b", r"\1-month", text, flags=re.I)
    text = re.sub(r"\b30day\b", "30-day", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return _sanitize_dates(text)


def _first(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        rendered = _humanize(value)
        if rendered:
            return rendered
    return ""


def _short_date(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    raw = text.split("T", 1)[0]
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if not match:
        return _humanize(text)
    _, month, day = match.groups()
    return f"{int(day)} {_MONTHS[int(month) - 1]}"


def _sanitize_dates(text: str) -> str:
    pattern = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[^\s,.)]+)?")
    return pattern.sub(lambda match: _short_date(match.group(0)), text)


def _short_datetime(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        hour = dt.hour % 12 or 12
        minute = dt.minute
        clock = f"{hour}:{minute:02d}pm" if dt.hour >= 12 else f"{hour}:{minute:02d}am"
        if minute == 0:
            clock = f"{hour}pm" if dt.hour >= 12 else f"{hour}am"
        return f"{dt.day} {_MONTHS[dt.month - 1]}, {clock}"
    except ValueError:
        return _short_date(text) or _humanize(text)


def _pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        n = value * 100 if abs(value) <= 1 else value
        sign = "+" if n > 0 else ""
        return f"{sign}{n:.0f}%"
    text = _text(value)
    if not text:
        return ""
    if text.endswith("%"):
        return text
    try:
        number = float(text)
    except ValueError:
        return text
    n = number * 100 if abs(number) <= 1 else number
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.0f}%"


def _delta_phrase(value: Any) -> str:
    text = _pct(value)
    if not text:
        return ""
    if text.startswith("-"):
        return f"down {text[1:]}"
    if text.startswith("+"):
        return f"up {text[1:]}"
    return text


def _metric_verb(metric: str) -> str:
    return "are" if metric.lower() in {"calls", "views", "directions", "leads", "reviews"} else "is"


def _number(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    return _text(value)


def _money(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"₹{value}"


def _merchant_intro(merchant: dict[str, Any]) -> str:
    name = merchant.get("name") or "Merchant"
    location = merchant.get("location") or ""
    return f"{name} ({location})" if location else str(name)


def _review_sentence(review: dict[str, Any]) -> str:
    if not review:
        return ""
    theme = _humanize(review.get("theme"))
    count = review.get("occurrences")
    if not theme:
        return ""
    natural = _review_natural(theme)
    if count:
        return f"{_number(count)} reviews call out {natural}"
    return f"Customers are calling out {natural}"


def _review_proof_sentence(review: dict[str, Any]) -> str:
    if not review:
        return ""
    theme = _humanize(review.get("theme"))
    count = review.get("occurrences")
    if not theme:
        return ""
    natural = _review_natural(theme)
    return f"{_number(count)} reviews mention {natural}" if count else f"Customers are mentioning {natural}"


def _review_natural(theme: str) -> str:
    mapping = {
        "thali_quality": "thali quality",
        "thali quality": "thali quality",
        "stylist_skill": "stylist skill",
        "stylist skill": "stylist skill",
        "doctor_manner": "how clearly you explain treatment",
        "doctor manner": "how clearly you explain treatment",
        "equipment_quality": "equipment quality",
        "equipment quality": "equipment quality",
        "instructor_quality": "instructor quality",
        "instructor quality": "instructor quality",
        "small_classes": "small classes",
        "small classes": "small classes",
        "delivery_speed": "delivery speed",
        "delivery speed": "delivery speed",
        "medicine_availability": "medicine availability",
        "medicine availability": "medicine availability",
        "pizza_quality": "pizza quality",
        "pizza quality": "pizza quality",
        "wait_time": "wait time",
        "wait time": "wait time",
        "morning_crowd": "morning crowd",
        "morning crowd": "morning crowd",
    }
    return mapping.get(theme, _humanize(theme))


def _event_name(payload: dict[str, Any]) -> str:
    return _first(payload, "festival", "event_name", "match", "occasion", "event", "season")


def _safe_event_label(kind: str, payload: dict[str, Any]) -> str:
    event = _event_name(payload)
    if event:
        return event
    if payload.get("placeholder"):
        return ""
    # Do not leak raw trigger identifiers such as festival_upcoming.
    if kind == "category_seasonal":
        return _first(payload, "season")
    return ""


def _render_trends(trends: list[Any]) -> str:
    rendered: list[str] = []
    for item in trends[:4]:
        text = _text(item)
        if not text:
            continue
        match = re.match(r"(.+?)[_ ]demand_([+-]?\d+)$", text, flags=re.I)
        if match:
            product = _humanize(match.group(1)).replace("cold cough", "cold/cough")
            change = match.group(2)
            rendered.append(f"{product} demand {change}%")
            continue
        match = re.match(r"(.+?)[_ ]([+-]?\d+)$", text, flags=re.I)
        if match:
            rendered.append(f"{_humanize(match.group(1))} {match.group(2)}%")
        else:
            rendered.append(_humanize(text))
    return ", ".join(rendered)


def _active_offer(merchant: dict[str, Any]) -> str:
    return merchant.get("best_offer") or ""


def _category_action(category: str) -> str:
    return {
        "dentists": "clinical Google post",
        "salons": "service-led Google post",
        "gyms": "class-focused Google post",
        "pharmacies": "availability-led Google post",
        "restaurants": "menu-led Google post",
    }.get(category, "focused Google post")


def _customer_greeting(name: str) -> str:
    return f"Hi {name or 'there'}"


def _customer_message(
    facts: dict[str, Any], fallback_key: str, kind: str, payload: dict[str, Any]
) -> dict[str, str]:
    merchant = facts["merchant"]
    customer = facts.get("customer") or {}
    category = facts.get("category_slug", "")
    name = customer.get("name") or "there"
    merchant_name = merchant.get("full_name") or merchant.get("name") or "your local business"
    preferences = customer.get("preferences") or {}
    language = str(customer.get("language_pref") or "").lower()
    hi = language.startswith("hi") or "hi-en" in language
    offer = _active_offer(merchant)

    # Appointment reminders: the trigger may intentionally omit service/slot
    # details. Never invent those details.
    if "appointment" in kind:
        service = _first(payload, "service_due", "service", "service_name")
        slot = _first(payload, "scheduled_for", "appointment_date")
        if hi and category == "salons":
            body = (
                f"{_customer_greeting(name)}, {merchant_name} here. "
                "Aapka appointment kal hai. Time confirm kar dein? "
                "Reply YES, ya convenient time bhej dein."
            )
        elif hi:
            body = f"{_customer_greeting(name)}, {merchant_name} se. Aapka appointment kal hai. "
            if service:
                body += f"Service: {service}. "
            if slot:
                body += f"Time: {_short_datetime(slot)}. "
            elif payload.get("placeholder"):
                body += "Is alert mein exact slot/service detail nahi hai, isliye main guess nahi karunga. "
            body += "Confirm karne ke liye YES reply karein, ya suitable time bhej dein."
        else:
            body = f"{_customer_greeting(name)}, {merchant_name} here. Quick reminder: your appointment is tomorrow. "
            if service:
                body += f"It is for {service}. "
            if slot:
                body += f"The scheduled time is {_short_datetime(slot)}. "
            elif payload.get("placeholder"):
                body += "The alert does not include the service or slot, so I won't guess. "
            body += "Reply YES to confirm or share a better time."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "merchant_on_behalf",
            "suppression_key": fallback_key,
            "rationale": "Customer appointment reminder uses only the supplied appointment signal and avoids inventing missing service or slot details.",
        }

    # Refill reminders: include drug names and the stock-out date when they
    # exist; otherwise clearly ask for confirmation rather than guessing.
    if "refill" in kind:
        medicines = payload.get("molecule_list") or payload.get("medicines")
        date = payload.get("stock_runs_out_iso") or payload.get("due_date")
        if medicines:
            med_text = ", ".join(_humanize(item) for item in medicines[:4])
            if hi:
                body = f"{_customer_greeting(name)}, {merchant_name} se. {med_text} ka refill"
                if date:
                    body += f" {_short_date(date)} se pehle due hai"
                else:
                    body += " due hai"
                body += "."
                if preferences.get("preferred_slots"):
                    body += f" Aapki {_humanize(preferences['preferred_slots'])} preference saved hai."
                body += " Refill arrange karne ke liye YES reply karein, ya suitable time bhej dein."
            else:
                body = f"{_customer_greeting(name)}, {merchant_name} here. Your regular medicines — {med_text} — are due for refill"
                if date:
                    body += f" before {_short_date(date)}"
                body += "."
                if preferences.get("preferred_slots"):
                    body += f" We have your {_humanize(preferences['preferred_slots'])} preference saved."
                body += " Reply YES to arrange the refill, or reply with a suitable time."
        else:
            body = (
                f"{_customer_greeting(name)}, {merchant_name} here. "
                "We received a refill reminder, but the medicine and due date are not in this alert. "
                "Reply here so we can confirm the prescription details before arranging anything."
            )
        return {
            "body": body,
            "cta": "binary_yes_no" if medicines else "open_ended",
            "send_as": "merchant_on_behalf",
            "suppression_key": fallback_key,
            "rationale": "Customer refill message names only supplied prescription facts and asks for confirmation when key details are missing.",
        }

    if kind == "trial_followup":
        trial_date = _short_date(payload.get("trial_date"))
        options = payload.get("next_session_options") or []
        slot = options[0].get("label", "") if options and isinstance(options[0], dict) else ""
        if category == "gyms":
            body = f"{_customer_greeting(name)}, {merchant_name} here. Thanks for trying the session"
            if trial_date:
                body += f" on {trial_date}"
            body += "."
            body += f" I can hold the next spot on {slot}." if slot else " I can help you pick the next suitable class."
            body += " Reply YES to continue, or share another time."
        else:
            body = f"{_customer_greeting(name)}, {merchant_name} here. Thanks for trying us."
            body += f" I can hold the next slot on {slot}." if slot else " I can help you choose the next slot."
            body += " Reply YES to continue, or share another time."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "merchant_on_behalf",
            "suppression_key": fallback_key,
            "rationale": "Trial follow-up references the available trial/next-slot facts and uses a low-friction continuation CTA.",
        }

    if "customer_lapsed_hard" in kind or "winback" in kind:
        days = payload.get("days_since_last_visit")
        pref_slot = preferences.get("preferred_slots")
        if category == "gyms":
            body = f"{_customer_greeting(name)}, {merchant_name} here. It has been {days} days since your last visit." if days else f"{_customer_greeting(name)}, {merchant_name} here. We haven't seen you in a while."
            if pref_slot:
                body += f" Your saved preference is {_humanize(pref_slot)}."
            if offer:
                body += f" We still have {offer} available."
            body += " Reply YES and we’ll help you choose the next slot."
        elif category == "salons":
            body = f"{_customer_greeting(name)}, {merchant_name} here. It has been {days} days since your last visit." if days else f"{_customer_greeting(name)}, {merchant_name} here. It has been a little while since your last visit."
            body += " Want us to help you pick the next service or slot?"
        elif category == "pharmacies":
            body = f"{_customer_greeting(name)}, {merchant_name} here. It has been {days} days since your last visit." if days else f"{_customer_greeting(name)}, {merchant_name} here. It has been a little while since your last visit."
            body += " If you need a refill or regular OTC item checked, reply here and we’ll confirm what you need."
        else:
            body = f"{_customer_greeting(name)}, {merchant_name} here. It has been {days} days since your last visit." if days else f"{_customer_greeting(name)}, {merchant_name} here. It has been a little while since your last visit."
            body += " Reply here if you’d like help planning the next visit."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "merchant_on_behalf",
            "suppression_key": fallback_key,
            "rationale": "Customer win-back message uses relationship timing and category-appropriate next steps without inventing a service.",
        }

    if kind in {"customer_lapsed_soft"}:
        if category == "dentists":
            body = (
                f"{_customer_greeting(name)}, {merchant_name} here. "
                "It has been a little while since your last visit. "
                "This alert does not name a specific service due, so I won’t guess. "
                "Reply here and we can check the right follow-up for you."
            )
        elif category == "pharmacies":
            if hi:
                body = (
                    f"{_customer_greeting(name)}, {merchant_name} se. "
                    "Kaafi time ho gaya hai. Refill ya regular OTC item chahiye ho to reply karein; "
                    "hum medicine aur timing confirm kar denge."
                )
            else:
                body = (
                    f"{_customer_greeting(name)}, {merchant_name} here. "
                    "It has been a little while since your last visit. "
                    "If you need a refill or regular OTC item checked, reply here and we’ll confirm the details."
                )
        else:
            body = (
                f"{_customer_greeting(name)}, {merchant_name} here. "
                "It has been a little while since your last visit. "
                "Reply here if you’d like help choosing the next step."
            )
        return {
            "body": body,
            "cta": "open_ended",
            "send_as": "merchant_on_behalf",
            "suppression_key": fallback_key,
            "rationale": "Customer lapse message is conservative when the alert omits the underlying service detail.",
        }

    if kind == "recall_due":
        if category == "dentists":
            service = _humanize(payload.get("service_due")) or "cleaning recall"
            slots = payload.get("available_slots") or []
            labels = [slot.get("label") for slot in slots[:2] if isinstance(slot, dict) and slot.get("label")]
            body = f"{_customer_greeting(name)}, {merchant_name} here. Your {service} is due."
            if labels:
                body += f" We have two weekday-evening options: {labels[0]} or {labels[1]}."
            offer_text = offer
            if offer_text:
                body += f" {offer_text} is active."
            if hi:
                body = body.replace(" here. ", " se. ")
                body = body.replace(f"Your {service} is due.", f"Aapka {service} due hai.")
                body = body.replace(" We have two weekday-evening options:", " Weekday-evening ke liye 2 slots hain:")
                body = body.replace(" is active.", " active hai.")
                body += " Reply YES to hold a slot, ya koi aur evening bata dein."
            else:
                body += " Reply YES to hold a slot, or share another evening that works."
        elif category == "gyms":
            last_visit = customer.get("relationship", {}).get("last_visit")
            body = f"{_customer_greeting(name)}, {merchant_name} here."
            if last_visit:
                body += f" Your last visit was {_short_date(last_visit)}."
            if offer:
                body += f" We currently have {offer}."
            body += " Reply YES and we’ll share the next suitable class."
        else:
            body = f"{_customer_greeting(name)}, {merchant_name} here. Your follow-up is due."
            if offer:
                body += f" {offer} is active."
            body += " Reply YES and we’ll help with the next step."
        return {
            "body": body,
            "cta": "binary_yes_no",
            "send_as": "merchant_on_behalf",
            "suppression_key": fallback_key,
            "rationale": "Customer recall message uses supplied service, slots, relationship and active-offer facts without medical overclaim.",
        }

    # Last-resort customer message: honest about missing specifics instead of
    # turning an internal trigger kind into customer-facing copy.
    body = (
        f"{_customer_greeting(name)}, {merchant_name} here. "
        "We have an update for you, but this alert does not include enough detail to name the service safely. "
        "Reply here and we’ll confirm the right next step."
    )
    return {
        "body": body,
        "cta": "open_ended",
        "send_as": "merchant_on_behalf",
        "suppression_key": fallback_key,
        "rationale": "Customer-facing fallback deliberately avoids exposing internal trigger labels or inventing missing details.",
    }


def compose_deterministic(
    facts: dict[str, Any], fallback_key: str, template: dict[str, Any] | None = None
) -> dict[str, str]:
    """Compose one concise, safe message from extracted live facts."""
    merchant = facts["merchant"]
    trigger = facts["trigger"]
    payload = trigger.get("payload") or {}
    kind = str(trigger.get("kind") or "update")
    category = facts.get("category_slug") or merchant.get("category_slug") or ""

    if trigger.get("scope") == "customer" or facts.get("customer"):
        return _customer_message(facts, fallback_key, kind, payload)

    intro = _merchant_intro(merchant)
    offer = _active_offer(merchant)
    performance = merchant.get("performance") or {}
    peer = merchant.get("peer_comparison") or {}
    review = merchant.get("review_theme") or {}
    digest = trigger.get("digest_item") or {}
    action = _category_action(category)
    cta = "open_ended"

    if kind == "active_planning_intent":
        topic = _humanize(payload.get("intent_topic")) or "the plan"
        last_message = _text(payload.get("merchant_last_message"))
        review_line = _review_sentence(review)
        if category == "restaurants":
            body = f"{intro}, for the {topic}, I'd shape this as a clear office-meal offer"
            if offer:
                body += f": {offer}"
            body += ", with one order cutoff and one enquiry reply."
        elif category == "gyms":
            body = f"{intro}, you asked about the {topic}. I'd make the draft concrete on age band, class cadence and the trial-to-booking step."
            if review_line:
                body += f" {review_line.capitalize()}—useful parent proof."
        elif category == "salons":
            body = f"{intro}, for the {topic}, I'd make the first message booking-led: service, date window and one simple enquiry reply."
            if offer:
                body += f" {offer} can stay as the price anchor."
        elif category == "pharmacies":
            body = f"{intro}, for the {topic}, I'd keep the message availability-led: what is stocked, when orders close and how customers enquire."
            if offer:
                body += f" {offer} can be the delivery hook."
        else:
            body = f"{intro}, for the {topic}, I'd keep the proposition specific"
            if offer:
                body += f" around {offer}"
            body += "."
        if last_message and category == "restaurants":
            body += " You asked what the structure would look like, so I can draft it now."
        elif last_message and category == "gyms":
            body += " I can draft the outline now."
        else:
            body += " I can move straight to the draft."
        body += " Shall I prepare it?"

    elif "perf_dip" in kind:
        metric = _humanize(payload.get("metric"))
        delta = _pct(payload.get("delta_pct") or payload.get("change_pct"))
        baseline = payload.get("vs_baseline")
        current_ctr = performance.get("ctr")
        peer_ctr = peer.get("peer_ctr")
        if metric and delta:
            verb = "down" if delta.startswith("-") else "up" if delta.startswith("+") else "changed by"
            first_line = f"{intro}, {metric} {_metric_verb(metric)} {verb} {delta.lstrip('+-')}" if verb != "changed by" else f"{intro}, {metric} {verb} {delta}"
            if baseline:
                baseline_text = _number(baseline)
                if metric.lower() == "calls":
                    first_line += f" against the {baseline_text}-call trigger baseline"
                else:
                    first_line += f" against the {baseline_text} trigger baseline"
            first_line += "."
        elif current_ctr and peer_ctr:
            first_line = f"{intro}, the alert flags a dip but doesn't identify the metric. Your 30-day CTR is {current_ctr} versus a {category} peer average of {peer_ctr}, so I won't guess that CTR fell."
        else:
            first_line = f"{intro}, the performance alert flags a dip, but it does not identify the metric. I won't guess which number fell."
        body = first_line
        if category == "dentists":
            body += " I can draft a treatment-led Google post without inventing a price."
        elif category == "salons":
            body += " I can draft a service-led post once the affected metric is confirmed."
        elif category == "pharmacies":
            body += " I can draft an availability-led update from the confirmed signal."
        elif category == "restaurants":
            body += f" I can refresh a menu-led post{f' around {offer}' if offer else ''}."
        else:
            body += f" I can draft a focused {action}."
        body += " Want the draft? YES/STOP"
        cta = "binary_yes_no"

    elif "perf_spike" in kind:
        metric = _humanize(payload.get("metric"))
        delta = _pct(payload.get("delta_pct") or payload.get("change_pct"))
        baseline = payload.get("vs_baseline")
        likely_driver = _humanize(payload.get("likely_driver"))
        if metric and delta:
            body = f"{intro}, {metric} are up {delta.lstrip('+')}"
            if baseline:
                baseline_phrase = f"the {_number(baseline)}-call baseline" if metric == "calls" else f"the {_number(baseline)} baseline"
                body += f" versus {baseline_phrase}"
            body += "."
        else:
            current_deltas = performance.get("delta_7d") or {}
            fallback_delta = current_deltas.get("calls_pct") or current_deltas.get("views_pct")
            if fallback_delta:
                label = "calls" if "calls_pct" in current_deltas else "views"
                body = f"{intro}, the alert is positive but does not name the metric. Your latest 7-day {label} trend is {fallback_delta}."
            else:
                body = f"{intro}, the alert is positive but does not include the affected metric. I won't guess which number improved."
        if likely_driver:
            driver = likely_driver.replace("kids yoga post", "your kids-yoga post")
            body += f" The signal points to {driver} as the likely driver, so I'd build the next post around that momentum."
        elif category == "gyms":
            review_line = _review_sentence(review)
            if review_line:
                body += f" {review_line.capitalize()}, which gives us a clean proof angle."
        if category == "gyms":
            body += " I can turn the lift into a class-focused follow-up."
        elif category == "pharmacies":
            body += " I can turn the lift into an availability-focused update rather than a generic promotion."
        elif category == "restaurants":
            body += f" I can turn the momentum into a menu-led post{f' around {offer}' if offer else ''}."
        elif category == "salons":
            body += " I can turn the lift into a service-led Google post."
        else:
            body += " I can turn the lift into a focused follow-up post."
        body += " Want me to draft it? YES/STOP"
        cta = "binary_yes_no"

    elif kind in {"research_digest", "regulation_change", "cde_opportunity", "category_research_digest_release"} or "compliance" in kind:
        title = _humanize(digest.get("title")) or _first(payload, "title", "headline", "topic")
        if not title:
            body = f"{intro}, this alert does not include a usable digest item, so I won't invent a headline."
        else:
            if kind == "regulation_change" and digest.get("summary"):
                summary = _humanize(digest.get("summary")).rstrip(".")
                body = f"{intro}, {title}."
                if "Maximum dose per IOPA exposure drops from" in summary:
                    body = f"{intro}, DCI revised IOPA dose limit takes effect 15 Dec: 1.5 mSv drops to 1.0 mSv."
                    body += " E-speed passes; D-speed does not; digital RVG is unaffected."
                else:
                    body = f"{intro}, {title}. {summary}."
            elif category == "dentists":
                body = f"{intro}, {title}."
            elif category == "pharmacies":
                body = f"{intro}, pharmacy update: {title}."
            elif category == "salons":
                body = f"{intro}, a beauty-industry update worth a look: {title}."
            elif category == "gyms":
                body = f"{intro}, fitness update worth a look: {title}."
            else:
                body = f"{intro}, {title}."
            if digest.get("trial_n") and kind != "regulation_change":
                body += f" Evidence base: {_number(digest['trial_n'])} participants."
            if digest.get("credits"):
                body += f" {digest['credits']} credits."
            date = digest.get("date")
            if date:
                body += f" {_short_datetime(date)}."
            if digest.get("actionable"):
                if kind == "cde_opportunity" and digest.get("credits"):
                    action_text = _humanize(digest["actionable"]).rstrip(".")
                    body += f" Fee: {action_text}."
                elif kind != "regulation_change":
                    body += f" Action: {_humanize(digest['actionable']).rstrip('.')}."
                elif "Audit your X-ray setup" in str(digest["actionable"]):
                    body += " Action: audit your X-ray setup and update SOPs before 15 Dec."
                else:
                    body += f" Action: {_humanize(digest['actionable']).rstrip('.')}."
            if digest.get("source"):
                source = _humanize(digest["source"]).rstrip(".")
                if kind == "regulation_change":
                    source = source.replace("Dental Council of India", "DCI")
                body += f" Source: {source}."
        body += " Want the checklist?"

    elif "competitor" in kind:
        competitor = _first(payload, "competitor_name", "competitor")
        distance = _first(payload, "distance_km", "distance")
        their_offer = _first(payload, "their_offer", "competitor_offer")
        review_line = _review_proof_sentence(review)
        if not competitor:
            body = f"{intro}, the competitor alert is missing the rival name and distance, so I won't invent them."
            if performance.get("calls") and performance.get("views"):
                body += f" Your listing has {_number(performance['calls'])} calls from {_number(performance['views'])} views in 30 days"
            if offer:
                body += f", and {offer} is active."
            body += " I'll build around your own proof instead."
        else:
            body = f"{intro}, {competitor} has opened"
            body += f" {distance} km away" if distance else " nearby"
            if their_offer:
                body += f" and lists {their_offer}"
            body += "."
            if review_line:
                body += f" {review_line.capitalize()}."
            if offer:
                body += f" With {offer} active, I'd lead on your own value rather than price."
        body += " Want a comparison-safe draft? YES/STOP"
        cta = "binary_yes_no"

    elif "milestone" in kind:
        value = _first(payload, "value_now", "current_value", "metric_value")
        metric = _humanize(payload.get("metric"))
        target = _first(payload, "milestone_value", "target")
        if value and metric:
            body = f"{intro}, you reached {value} {metric}"
            body += f"; only {max(int(target) - int(value), 0)} to go to {target}" if target and str(target).isdigit() and str(value).isdigit() else f"; next marker is {target}" if target else ""
            body += "."
            if metric == "review count":
                body += " I can turn the milestone into a focused review request."
            else:
                body += " I can turn the milestone into a focused customer-proof post."
        elif value:
            body = f"{intro}, the milestone alert has {value} recorded."
            body += " I can draft a customer-proof follow-up from that number."
        else:
            body = f"{intro}, the milestone alert is missing the number, so I won't invent it."
            body += " Share the confirmed value and I can draft the review request around it."

    elif "review_theme" in kind or "curious_ask" in kind:
        theme = _humanize(review.get("theme")) or _first(payload, "theme", "review_theme")
        count = review.get("occurrences") or _first(payload, "review_count", "occurrences")
        natural_theme = _review_natural(theme) if theme else "customer feedback"
        if not theme and payload.get("placeholder"):
            if category == "salons":
                body = f"{intro}, the alert doesn't name this week's demand driver. Your latest proof point is {_number(count)} reviews calling out stylist skill." if count else f"{intro}, the alert doesn't name this week's demand driver. I won't invent a service trend."
            else:
                body = f"{intro}, the alert doesn't identify the underlying demand signal, so I won't invent one."
        else:
            body = f"{intro}, {_number(count) if count else 'Customers'} reviews call out {natural_theme}." if count else f"{intro}, customers are calling out {natural_theme}."
        if category == "salons" and natural_theme == "stylist skill":
            body += " Is that the service strength you want to lead with this week?"
        elif category == "restaurants" and natural_theme == "thali quality":
            body += f" Your {offer or 'thali offering'} is a concrete hook; want me to turn that proof into this week's lunch post?"
        else:
            body += " Is that the strength you want to lead with this week? Reply with one service and I’ll turn it into a post."

    elif "festival" in kind or "seasonal" in kind or "ipl" in kind or "event" in kind or "weather" in kind:
        event = _safe_event_label(kind, payload)
        if kind == "category_seasonal" and payload.get("trends"):
            trend_text = _render_trends(payload["trends"])
            body = f"{intro}, summer demand is shifting: {trend_text}."
            if payload.get("shelf_action_recommended"):
                body += " That makes availability-led shelf and GBP messaging timely."
        elif event:
            body = f"{intro}, {event} is the timely window"
            if payload.get("date"):
                body += f" ({_short_date(payload['date'])})"
            body += "."
            if kind == "festival_upcoming" and payload.get("days_until"):
                body += f" That's {payload['days_until']} days to plan."
            if kind == "ipl_match_today":
                if payload.get("match_time_iso"):
                    body += f" Match time: {_short_datetime(payload['match_time_iso'])}"
                if payload.get("venue"):
                    body += f" at {_humanize(payload['venue'])}"
                body += "." if not body.endswith(".") else ""
            if offer:
                if kind == "ipl_match_today" and payload.get("is_weeknight") is False:
                    body += " Your active offer is Tue-Thu only, so the current offer doesn't fit tonight."
                elif kind == "category_seasonal":
                    body += f" Your active offer is {offer}."
                else:
                    body += f" {offer} is already active."
        else:
            trend = (performance.get("delta_7d") or {}).get("calls_pct") or (performance.get("delta_7d") or {}).get("views_pct")
            body = f"{intro}, the event alert is missing the event name, so I won't guess."
            if trend:
                trend_label = "calls" if (performance.get("delta_7d") or {}).get("calls_pct") else "views"
                body += f" Your latest 7-day {trend_label} trend is {trend}."
            body += " Once the event is confirmed, I can tailor the campaign."
        if offer and kind == "category_seasonal" and "active offer is" not in body:
            body += f" Your active offer is {offer}."
        body += " Want the draft? YES/STOP"
        cta = "binary_yes_no"

    elif "renewal" in kind:
        days = _first(payload, "days_remaining", "days_to_renewal") or _humanize(merchant.get("subscription", {}).get("days_remaining"))
        body = f"{intro}, your plan renews"
        body += f" in {days} days" if days else " soon"
        body += ". I can run a quick account check before you decide. Want that?"

    elif "dormant" in kind or "winback" in kind:
        days = _first(payload, "days_since_last_merchant_message", "days_since_expiry")
        delta_calls = (performance.get("delta_7d") or {}).get("calls_pct")
        delta_views = (performance.get("delta_7d") or {}).get("views_pct")
        body = f"{intro}, it has been {days} days since our last useful update." if days else f"{intro}, a quick restart looks timely."
        if category == "salons" and days:
            body += f" Your Pro plan is also expired, so I’d keep the restart focused."
        if delta_calls:
            body += f" Calls are {_delta_phrase(delta_calls)} in the latest 7-day window."
        elif delta_views:
            body += f" Views are {_delta_phrase(delta_views)} in the latest 7-day window."
        if offer:
            body += f" I can prepare one recovery post around {offer}."
        elif category == "restaurants":
            body += " Tell me the dish you want to push and I’ll shape the recovery post around it."
        else:
            body += " I can prepare one recovery post from the confirmed listing facts."
        body += " Want the two-line draft? YES/STOP"
        cta = "binary_yes_no"

    elif "unverified" in kind or "gbp" in kind:
        path = _humanize(payload.get("verification_path"))
        uplift = _pct(payload.get("estimated_uplift_pct"))
        body = f"{intro}, your Google Business Profile is still unverified."
        if uplift:
            body += f" This alert estimates {uplift} uplift after verification."
        if path:
            body += f" The available verification path is {path}."
        body += " I can give you the exact next steps. Want that?"

    else:
        detail = _first(payload, "headline", "summary", "intent_topic", "reason", "topic", "metric")
        body = f"{intro}, Vera flagged a new account signal"
        body += f": {detail}." if detail else "."
        if offer:
            body += f" I can turn it into a customer-ready update around {offer}."
        body += " Want the draft?"

    return {
        "body": body,
        "cta": cta,
        "send_as": "vera",
        "suppression_key": fallback_key,
        "rationale": f"{kind.replace('_', ' ').capitalize()} message grounded in supplied context and category voice.",
    }
