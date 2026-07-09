from __future__ import annotations

import re

from rapidfuzz import fuzz

from db import queries
from db.pool import get_pool

THRESHOLD = 3

# ---------------------------------------------------------------------------
# Fast lead / contact intent (request-time UI decision)
# ---------------------------------------------------------------------------

CONTACT_PHRASES: list[str] = [
    "talk to counsellor",
    "talk to counselor",
    "talk to an advisor",
    "talk to advisor",
    "speak to counsellor",
    "speak to counselor",
    "speak to advisor",
    "speak to someone",
    "speak with counsellor",
    "speak with counselor",
    "speak with advisor",
    "admission advisor",
    "admissions advisor",
    "call me",
    "contact me",
    "connect me",
    "connect me with admissions",
    "connect me with admission",
    "get in touch",
    "want counselling",
    "want counseling",
    "i want counselling",
    "i want counseling",
    "need counselling",
    "need counseling",
    "application help",
    "help me apply",
    "help applying",
    "need help applying",
    "want to get in touch",
    "i want to get in touch",
    "request a callback",
    "request callback",
    "book a counselling",
    "book counselling",
]

# Single tokens/phrases that are strong contact signals when present
_CONTACT_KEYWORDS: list[str] = [
    "counsellor",
    "counselor",
    "counselling",
    "counseling",
    "advisor",
    "callback",
]


def _normalize_contact_text(message: str) -> str:
    text = message.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_contact_intent(message: str) -> bool:
    """True when the user wants human outreach / contact / counselling help."""
    if not message or not message.strip():
        return False
    text = _normalize_contact_text(message)

    for phrase in CONTACT_PHRASES:
        if phrase in text:
            return True

    for kw in _CONTACT_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True

    # Fuzzy phrase match for mild typos / reordering
    for phrase in CONTACT_PHRASES:
        if len(phrase) < 8:
            continue
        if fuzz.partial_ratio(phrase, text) >= 88:
            return True

    return False


def detect_fast_lead_intent(message: str) -> bool:
    """Synchronous, zero-LLM lead popup decision for the current SSE turn."""
    return is_contact_intent(message)


# ---------------------------------------------------------------------------
# Score-event classification (analytics / background path)
# ---------------------------------------------------------------------------

def classify_score_events(message: str, message_count: int = 0) -> list[str]:
    text = message.lower()
    events: list[str] = []
    if any(term in text for term in ("fee", "fees", "eligibility", "eligible", "cost")):
        events.append("asked_fee_or_eligibility")
    if message_count >= 3:
        events.append("three_plus_turns")
    if any(term in text for term in ("thanks", "thank you", "bye", "ok")):
        events.append("session_ending_signal")
    if is_contact_intent(message):
        events.append("contact_intent")
    return events


async def log_score_events(session_id: str, events: list[str]) -> int:
    pool = await get_pool()
    for event in events:
        await queries.log_signal(pool, session_id, None, None, event)
    return await queries.total_lead_score(pool, session_id)


async def should_append_lead_ask(session_id: str, score: int) -> bool:
    if score < THRESHOLD:
        return False
    pool = await get_pool()
    if await queries.lead_ask_exists(pool, session_id):
        return False
    await queries.mark_lead_ask(pool, session_id)
    return True
