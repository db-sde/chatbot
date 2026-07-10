from __future__ import annotations

import re


ROUTE_FEE = "fee"
ROUTE_ELIGIBILITY = "eligibility"
ROUTE_SPECIALIZATIONS = "specializations"
ROUTE_ACCREDITATION = "accreditation"
ROUTE_REVIEWS = "reviews"
ROUTE_RATINGS = "ratings"
ROUTE_PROGRAMS = "programs"
ROUTE_RECOMMENDATION = "recommendation"
ROUTE_COMPARISON = "comparison"
ROUTE_GENERAL = "general"

DETERMINISTIC_ROUTES = {
    ROUTE_FEE,
    ROUTE_ELIGIBILITY,
    ROUTE_SPECIALIZATIONS,
    ROUTE_ACCREDITATION,
    ROUTE_REVIEWS,
    ROUTE_RATINGS,
    ROUTE_PROGRAMS,
}

_RECOMMENDATION = re.compile(
    r"\b(?:best|right|ideal|recommend|suggest|suitable)\b[^.?!]{0,60}"
    r"\b(?:for\s+me|should\s+i|suits?\s+me|choose|pick)\b"
    r"|\bhelp\s+me\s+(?:choose|pick|find)\b"
    r"|\b(?:recommend|suggest)\b[^.?!]{0,45}\b"
    r"(?:mba|bba|bca|mca|pgdm|courses?|programs?|universit(?:y|ies))\b"
    r"|\bwhich\b[^.?!]{0,40}\b(?:mba|course|program|university)\b"
    r"[^.?!]{0,25}\b(?:is\s+(?:the\s+)?best|should\s+i\s+choose)\b",
    re.IGNORECASE,
)
_COMPARISON = re.compile(
    r"\b(?:compare|comparison|vs\.?|versus|difference\s+between|which\s+is\s+better)\b",
    re.IGNORECASE,
)


def detect_route(message: str) -> str:
    """Classify common education intents without invoking a planner model."""
    text = message.lower().strip()
    if _RECOMMENDATION.search(text):
        return ROUTE_RECOMMENDATION
    if _COMPARISON.search(text):
        return ROUTE_COMPARISON
    matches: list[str] = []
    patterns = (
        (ROUTE_FEE, r"\b(?:fee|fees|cost|price|pricing|emi|payment\s+plan|fee\s+structure)\b"),
        (ROUTE_ELIGIBILITY, r"\b(?:eligibility|eligible|criteria|admission\s+eligibility)\b"),
        (ROUTE_SPECIALIZATIONS, r"\b(?:speciali[sz]ations?|streams?)\b"),
        (ROUTE_ACCREDITATION, r"\b(?:naac|ugc|accredit(?:ation|ed)?|approv(?:al|ed)|recogni[sz](?:ed|ation))\b"),
        (ROUTE_REVIEWS, r"\b(?:student\s+reviews?|reviews?|testimonials?)\b"),
        (ROUTE_RATINGS, r"\b(?:student\s+ratings?|ratings?|rated)\b"),
        (ROUTE_PROGRAMS, r"\b(?:courses|programs|programmes|available\s+programs?|online\s+universit(?:y|ies))\b"),
    )
    for route, pattern in patterns:
        if re.search(pattern, text):
            matches.append(route)
    if set(matches) == {ROUTE_RATINGS, ROUTE_REVIEWS}:
        return ROUTE_REVIEWS
    if len(matches) == 1:
        return matches[0]
    return ROUTE_GENERAL


def context_class_for(message: str) -> str:
    """Choose the smallest safe conversation context for this request."""
    route = detect_route(message)
    if route in DETERMINISTIC_ROUTES:
        return "A"
    if route == ROUTE_COMPARISON:
        return "B"
    if route == ROUTE_RECOMMENDATION:
        return "C"
    return "B"
