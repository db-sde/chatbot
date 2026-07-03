from __future__ import annotations

IN_SCOPE_TERMS = {
    "degree", "mba", "bca", "mca", "ma", "ba", "bba", "university", "college", "course",
    "fee", "fees", "eligibility", "duration", "admission", "online", "distance", "emi",
    "placement", "syllabus", "naac", "ugc", "specialization", "specialisation", "nmims",
    "amity", "manipal", "program", "counsellor", "counselor",
}
INJECTION_TERMS = {
    "ignore previous instructions", "ignore all instructions", "system prompt", "developer message",
    "write sql", "drop table", "jailbreak", "act as", "forget your rules",
}
SMALL_TALK = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay"}


def guardrail_check(message: str) -> bool:
    """Returns True when the message is safe and plausibly in DegreeBaba scope."""
    normalized = " ".join(message.lower().split())
    if any(term in normalized for term in INJECTION_TERMS):
        return False
    if normalized in SMALL_TALK:
        return True
    return any(term in normalized for term in IN_SCOPE_TERMS)


def get_guardrail_reason(message: str) -> str:
    """Classifies the matched block reason for database logging."""
    normalized = " ".join(message.lower().split())
    if any(term in normalized for term in INJECTION_TERMS):
        return "injection_pattern"
    return "off_topic_keyword"


OFF_TOPIC_REDIRECT = (
    "I can help with DegreeBaba university, course, fee, eligibility, admission, and comparison questions. "
    "Ask me about a program like online MBA, BCA, or MCA and I will use DegreeBaba's data."
)

