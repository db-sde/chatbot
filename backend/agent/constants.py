from __future__ import annotations

QUICK_REPLY_TOPICS: tuple[str, ...] = (
    "Check fees",
    "Eligibility",
    "Accreditations",
    "Ratings & reviews",
    "Specializations",
    "Talk to a counsellor",
)


def quick_replies_for(message: str, *, limit: int = 3) -> list[str]:
    """Return a relevant subset without repeating the topic just answered."""
    text = message.lower()
    if any(term in text for term in ("fee", "fees", "cost", "price", "emi")):
        preferred = ("Eligibility", "Accreditations", "Talk to a counsellor")
    elif any(term in text for term in ("eligible", "eligibility", "criteria")):
        preferred = ("Accreditations", "Ratings & reviews", "Talk to a counsellor")
    elif any(term in text for term in ("accredit", "ugc", "naac", "recognised", "recognized")):
        preferred = ("Check fees", "Ratings & reviews", "Specializations")
    elif any(term in text for term in ("rating", "ratings", "review", "reviews")):
        preferred = ("Check fees", "Eligibility", "Specializations")
    elif any(term in text for term in ("specialization", "specialisation")):
        preferred = ("Check fees", "Eligibility", "Talk to a counsellor")
    elif any(term in text for term in ("counsellor", "counselor", "advisor", "callback")):
        preferred = ("Check fees", "Eligibility", "Accreditations")
    else:
        preferred = QUICK_REPLY_TOPICS
    return list(preferred[:limit])
