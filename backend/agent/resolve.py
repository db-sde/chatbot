from __future__ import annotations

import logging
import re
from typing import Any

from rapidfuzz import fuzz

from db import queries
from db.pool import get_pool

logger = logging.getLogger(__name__)

COURSE_HINTS = [
    "mba", "bca", "mca", "bba", "ma", "ba", "mcom", "bcom",
    "btech", "mtech", "masters", "masters in", "bachelors", "bachelors in",
]

# Keywords that indicate the user needs factual catalog data
_FACTUAL_KEYWORDS = {
    "fee", "fees", "cost", "price", "emi", "eligib", "admission",
    "placement", "ranking", "course", "program", "specializ", "duration",
    "compare", "comparison", "vs", "versus", "tell me about", "info",
    "details", "what is", "how much", "brochure",
}

# Common conversational and structural stop words to ignore
_STOP_WORDS = {
    "tell", "me", "about", "what", "is", "the", "for", "of", "and", "in", "to", 
    "a", "an", "i", "want", "know", "please", "can", "you", "get", "give", 
    "details", "info", "information", "much", "does", "cost", "fee", "fees",
    "university", "college", "institute", "program", "degree"
}


def _message_needs_entity(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _FACTUAL_KEYWORDS)


def _local_extract(message: str) -> dict[str, Any]:
    text = message.lower()
    result: dict[str, Any] = {}
    for course in COURSE_HINTS:
        if re.search(rf"\b{course}\b", text):
            result["course"] = course
            break
    fee_match = re.search(r"(?:under|below|less than|max(?:imum)?)\s*(?:rs\.?|₹)?\s*([\d,]+)", text)
    if fee_match:
        result["max_fee"] = float(fee_match.group(1).replace(",", ""))
    if "cheapest" in text or "lowest" in text:
        result["sort_by"] = "fee"
        result["order"] = "asc"
    if "online" in text:
        result["mode"] = "online"
    return result


def _extract_potential_name(message: str, local_hints: dict[str, Any]) -> str:
    """
    Strips away structural hints, factual keywords, and stop words.
    The remaining words are highly likely to be the entity name (e.g., 'nims').
    """
    text = message.lower()
    text = re.sub(r'[^\w\s]', '', text)  # remove punctuation
    words = text.split()
    
    ignore_words = set(_FACTUAL_KEYWORDS)
    ignore_words.update(COURSE_HINTS)
    ignore_words.update(_STOP_WORDS)
    
    # Also ignore any values already extracted by local hints (like "online", "mba")
    for v in local_hints.values():
        if isinstance(v, str):
            ignore_words.add(v.lower())
            
    remaining = [w for w in words if w not in ignore_words and len(w) > 1]
    return " ".join(remaining)


async def extract_entities(message: str, context: dict[str, Any]) -> dict[str, Any]:
    # 1. Get fast structural hints (mode, fee limits, course type)
    local = _local_extract(message)
    extracted = dict(local)
    
    # 2. Isolate the potential entity name by stripping keywords
    potential_name = _extract_potential_name(message, local)
    
    if potential_name:
        # Assign the isolated name to university, course, and specialization.
        # The downstream _snap() function will validate it against the actual DB rows 
        # using RapidFuzz and only keep the one that actually matches.
        if not extracted.get("university"):
            extracted["university"] = potential_name
        if not extracted.get("course"):
            extracted["course"] = potential_name
        if not extracted.get("specialization"):
            extracted["specialization"] = potential_name
            
    return extracted


async def _snap(entity_type: str, name: str | None) -> str | None:
    if not name: return None

    normalized_name = name.lower().strip()
    pool = await get_pool()
    rows = await queries.find_entity_search(pool, entity_type)
    if not rows: return None

    best_score = 0
    best_row = None

    for row in rows:
        search_text = row["search_text"].lower()
        score = max(
            fuzz.WRatio(normalized_name, search_text),
            fuzz.partial_ratio(normalized_name, search_text)
        )
        if score > best_score:
            best_score = score
            best_row = row

    # Short strings need more forgiveness for typos
    threshold = 75 if len(normalized_name) < 6 else 80
    if best_row and best_score >= threshold:
        return await queries.slug_for_entity_id(pool, entity_type, best_row["entity_id"])
    return None


async def resolve_entities(
    message: str,
    context: dict[str, Any],
    page_university_slug: str | None = None,
) -> dict[str, Any]:
    """
    Resolve named entities from the user's message.
    """
    extracted = await extract_entities(message, context)

    # Step 1: fuzzy snap on what we extracted
    university_slug = await _snap("university", extracted.get("university"))
    course_slug = await _snap("course", extracted.get("course"))
    specialization_slug = await _snap("specialization", extracted.get("specialization"))

    # Step 2: fall back to conversational context (established by prior turns)
    if not university_slug:
        university_slug = context.get("current_university_slug")
    if not course_slug:
        course_slug = context.get("current_course_slug")
    if not specialization_slug:
        specialization_slug = context.get("current_specialization_slug")

    # Step 3: page context hint — only when the message actually needs an entity
    if not university_slug and page_university_slug and _message_needs_entity(message):
        university_slug = page_university_slug
        logger.debug(
            "Using page_university_slug=%r as hint for message: %r",
            page_university_slug,
            message,
        )

    return {
        "raw": extracted,
        "university_slug": university_slug,
        "course_slug": course_slug,
        "specialization_slug": specialization_slug,
        "mode": extracted.get("mode"),
        "max_fee": extracted.get("max_fee"),
        "sort_by": extracted.get("sort_by"),
        "order": extracted.get("order") or "asc",
        "comparison_targets": extracted.get("comparison_targets") or [],
    }