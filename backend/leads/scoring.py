from __future__ import annotations

from db import queries
from db.pool import get_pool

THRESHOLD = 3


def classify_score_events(message: str, message_count: int = 0) -> list[str]:
    text = message.lower()
    events: list[str] = []
    if any(term in text for term in ("fee", "fees", "eligibility", "eligible", "cost")):
        events.append("asked_fee_or_eligibility")
    if message_count >= 3:
        events.append("three_plus_turns")
    if any(term in text for term in ("thanks", "thank you", "bye", "ok")):
        events.append("session_ending_signal")
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
