from __future__ import annotations

import logging
import re
from typing import Any

from rapidfuzz import fuzz

from db import queries
from db.pool import get_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Greeting / chitchat detection
# ---------------------------------------------------------------------------

_GREETINGS = {
    "hi", "hello", "hey", "hiya", "helo", "hii", "hiiii",
    "thanks", "thank", "thank you", "thankyou", "thx", "ty",
    "ok", "okay", "k", "kk", "sure",
    "bye", "goodbye", "cya", "see you",
    "good morning", "good evening", "good afternoon", "good night",
    "gm", "gn", "sup", "yo", "what's up", "whats up",
    "nice", "great", "awesome", "cool", "perfect",
    "yes", "no", "nope", "yep", "yup",
}

_GREETING_PATTERN = re.compile(
    r"^(?:hi+|hey+|hello+|helo+|hiya|"
    r"thanks?|thank\s+you|thankyou|thx|ty|"
    r"ok+|okay|sure|"
    r"bye|goodbye|cya|"
    r"good\s+(?:morning|evening|afternoon|night)|"
    r"gm|gn|sup|yo|"
    r"yes|no|nope|yep|yup|"
    r"nice|great|awesome|cool|perfect"
    r")[.!?]*$",
    re.IGNORECASE,
)


def is_greeting(message: str) -> bool:
    """Return True if the message is purely a greeting/chitchat with no factual content."""
    stripped = message.strip()
    if stripped.lower() in _GREETINGS:
        return True
    return bool(_GREETING_PATTERN.match(stripped))


# ---------------------------------------------------------------------------
# In-memory entity cache
# ---------------------------------------------------------------------------
# Each row in ENTITY_CACHE[etype] is:
#   {entity_id, search_text, university_id?, course_id?}
# The FK columns are loaded alongside entity_search so we can do hierarchical
# filtering entirely in RAM without extra DB queries at request time.

ENTITY_CACHE: dict[str, list[dict[str, Any]]] = {
    "university": [],
    "course": [],
    "specialization": [],
}


async def load_entity_cache() -> None:
    """Fetch entity_search rows plus FK columns from Postgres into RAM.

    Called once at lifespan startup and on-demand via admin cache-refresh endpoint.
    """
    pool = await get_pool()

    # Universities
    uni_rows = await pool.fetch(
        "SELECT es.entity_id, es.search_text "
        "FROM entity_search es WHERE es.entity_type = 'university'"
    )
    ENTITY_CACHE["university"] = [
        {"entity_id": r["entity_id"], "search_text": r["search_text"]}
        for r in uni_rows
    ]

    # Courses — include university_id for hierarchical filtering
    course_rows = await pool.fetch(
        "SELECT es.entity_id, es.search_text, c.university_id "
        "FROM entity_search es "
        "JOIN courses c ON c.id = es.entity_id "
        "WHERE es.entity_type = 'course'"
    )
    ENTITY_CACHE["course"] = [
        {"entity_id": r["entity_id"], "search_text": r["search_text"],
         "university_id": r["university_id"]}
        for r in course_rows
    ]

    # Specializations — include university_id and course_id
    spec_rows = await pool.fetch(
        "SELECT es.entity_id, es.search_text, s.university_id, s.course_id "
        "FROM entity_search es "
        "JOIN specializations s ON s.id = es.entity_id "
        "WHERE es.entity_type = 'specialization'"
    )
    ENTITY_CACHE["specialization"] = [
        {"entity_id": r["entity_id"], "search_text": r["search_text"],
         "university_id": r["university_id"], "course_id": r["course_id"]}
        for r in spec_rows
    ]

    total = sum(len(v) for v in ENTITY_CACHE.values())
    logger.info("Entity cache loaded: %d rows across %d types", total, len(ENTITY_CACHE))


# ---------------------------------------------------------------------------
# Structural hint extraction
# ---------------------------------------------------------------------------

COURSE_HINTS = [
    "mba", "bca", "mca", "bba", "ma", "ba", "mcom", "bcom",
    "btech", "mtech", "pgdm", "pgpm",
    "masters", "bachelors",
]

SPECIALIZATION_HINTS = [
    "marketing", "finance", "hr", "human resource", "human resources",
    "data science", "cloud", "cloud computing", "retail", "operations",
    "it", "information technology", "fintech", "logistics", "analytics",
    "business analytics", "supply chain", "banking", "insurance",
    "healthcare", "media", "digital marketing",
]

# Keywords that indicate the user needs factual catalog data
_FACTUAL_KEYWORDS = {
    "fee", "fees", "cost", "price", "emi", "eligib", "admission",
    "placement", "ranking", "course", "program", "specializ", "duration",
    "compare", "comparison", "vs", "versus", "tell me about", "info",
    "details", "what is", "how much", "brochure",
}

# Stop words — stripped before isolating the entity name
_STOP_WORDS = {
    "tell", "me", "about", "what", "is", "the", "for", "of", "and", "in", "to",
    "a", "an", "i", "want", "know", "please", "can", "you", "get", "give",
    "details", "info", "information", "much", "does", "cost", "fee", "fees",
    "university", "college", "institute", "program", "degree",
    "at", "from", "with", "by", "on", "under", "above", "below",
    "show", "list", "find", "search", "explore",
}


def _message_needs_entity(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _FACTUAL_KEYWORDS)


def _local_extract(message: str) -> dict[str, Any]:
    """Extract structured hints: course type, specialization, fee limits, mode."""
    text = message.lower()
    result: dict[str, Any] = {}

    # Course type hint (exact word boundary)
    for course in COURSE_HINTS:
        if re.search(rf"\b{re.escape(course)}\b", text):
            result["course"] = course
            break

    # Specialization hint (look for known specialization names)
    for spec in SPECIALIZATION_HINTS:
        if re.search(rf"\b{re.escape(spec)}\b", text):
            result["specialization_hint"] = spec
            break

    # Fee constraint
    fee_match = re.search(
        r"(?:under|below|less than|max(?:imum)?)\s*(?:rs\.?|₹)?\s*([\d,]+)", text
    )
    if fee_match:
        result["max_fee"] = float(fee_match.group(1).replace(",", ""))

    # Sort preference
    if "cheapest" in text or "lowest" in text:
        result["sort_by"] = "fee"
        result["order"] = "asc"

    # Mode
    if "online" in text:
        result["mode"] = "online"
    elif "distance" in text:
        result["mode"] = "distance"

    return result


def _extract_university_name(message: str, local_hints: dict[str, Any]) -> str | None:
    """
    Strip all known structural words and return whatever is left as the likely
    university/brand name.  Returns None if nothing meaningful remains.
    """
    text = message.lower()
    text = re.sub(r"[^\w\s]", "", text)  # remove punctuation
    words = text.split()

    ignore = set(_STOP_WORDS)
    ignore.update(COURSE_HINTS)
    ignore.update(SPECIALIZATION_HINTS)
    ignore.update(_FACTUAL_KEYWORDS)
    # Also drop whatever local_hints already captured as strings
    for v in local_hints.values():
        if isinstance(v, str):
            for tok in v.lower().split():
                ignore.add(tok)

    remaining = [w for w in words if w not in ignore and len(w) > 1]
    return " ".join(remaining) if remaining else None


# ---------------------------------------------------------------------------
# Intent-based entity extraction (no fan-out)
# ---------------------------------------------------------------------------

def extract_intent(message: str) -> dict[str, Any]:
    """
    Parse the message into typed entity hints WITHOUT assigning one token to
    all three categories.  Returns only keys for which evidence was found:
      university_query   – free-text that likely refers to a university brand
      course_query       – one of the COURSE_HINTS tokens
      specialization_query – one of the SPECIALIZATION_HINTS tokens
      mode, max_fee, sort_by, order
    """
    local = _local_extract(message)
    result: dict[str, Any] = {
        k: v for k, v in local.items()
        if k not in ("course", "specialization_hint")
    }

    # Course evidence — from the COURSE_HINTS regex match
    if "course" in local:
        result["course_query"] = local["course"]

    # Specialization evidence — from SPECIALIZATION_HINTS
    if "specialization_hint" in local:
        result["specialization_query"] = local["specialization_hint"]

    # University evidence — whatever is left after stripping everything else
    uni_name = _extract_university_name(message, local)
    if uni_name:
        result["university_query"] = uni_name

    return result


# ---------------------------------------------------------------------------
# Snapping: exact-match-first, then token_set_ratio fuzzy, NO partial_ratio
# ---------------------------------------------------------------------------

def _exact_match(normalized_name: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Check if normalized_name matches any whitespace-delimited token in any
    row's search_text exactly.  This catches "nmims", "lpu", "ignou", "mba"
    without any fuzzy risk.
    """
    for row in rows:
        tokens = row["search_text"].lower().split()
        if normalized_name in tokens:
            return row
    return None


def token_aware_similarity(query: str, target: str) -> float:
    """
    Computes a token-aware similarity score between query and target.
    For each query token, finds the maximum ratio score against any target token.
    For short tokens (<= 2 chars), requires very high similarity to avoid false positives.
    """
    q_tokens = query.lower().split()
    t_tokens = target.lower().split()
    if not q_tokens or not t_tokens:
        return 0.0

    total_score = 0.0
    for q_tok in q_tokens:
        best_tok_score = 0.0
        for t_tok in t_tokens:
            score = fuzz.ratio(q_tok, t_tok)
            # For short tokens (<= 2 chars), require a very high similarity
            if len(q_tok) <= 2 and score < 95:
                score = 0.0
            if score > best_tok_score:
                best_tok_score = score
        total_score += best_tok_score

    return total_score / len(q_tokens)


def _fuzzy_snap(
    normalized_name: str, rows: list[dict[str, Any]], threshold: int
) -> dict[str, Any] | None:
    """
    Fuzzy match against a list of rows using token_aware_similarity.
    """
    best_score = 0.0
    best_row = None
    for row in rows:
        score = token_aware_similarity(normalized_name, row["search_text"].lower())
        if score > best_score:
            best_score = score
            best_row = row

    logger.debug(
        "FUZZY | name=%r best=%r score=%.1f threshold=%d -> %s",
        normalized_name,
        best_row["search_text"] if best_row else None,
        best_score, threshold,
        "HIT" if (best_row and best_score >= threshold) else "MISS",
    )
    return best_row if (best_row and best_score >= threshold) else None



async def _to_slug(entity_type: str, row: dict[str, Any]) -> str | None:
    pool = await get_pool()
    return await queries.slug_for_entity_id(pool, entity_type, row["entity_id"])


async def snap_university(name: str | None) -> tuple[str | None, int | None]:
    """Returns (slug, entity_id) or (None, None)."""
    if not name:
        return None, None

    normalized = name.lower().strip()
    rows = ENTITY_CACHE["university"]
    if not rows:
        logger.warning("University cache empty — falling back to DB")
        pool = await get_pool()
        rows = await queries.find_entity_search(pool, "university")

    # 1. Exact token match (handles "nmims", "ignou", "lpu" with zero false-positive risk)
    row = _exact_match(normalized, rows)
    if row:
        logger.info("SNAP university | exact | %r -> id=%d", normalized, row["entity_id"])
        return await _to_slug("university", row), row["entity_id"]

    # 2. Fuzzy fallback — threshold 82 (university names are fairly unique)
    row = _fuzzy_snap(normalized, rows, threshold=82)
    if row:
        logger.info("SNAP university | fuzzy | %r -> id=%d", normalized, row["entity_id"])
        return await _to_slug("university", row), row["entity_id"]

    logger.info("SNAP university | MISS | %r", normalized)
    return None, None


async def snap_course(
    name: str | None,
    university_entity_id: int | None = None,
) -> tuple[str | None, int | None]:
    """Returns (slug, entity_id) or (None, None).
    Searches university-scoped courses first; falls back to global."""
    if not name:
        return None, None

    normalized = name.lower().strip()
    all_rows = ENTITY_CACHE["course"]
    if not all_rows:
        logger.warning("Course cache empty — falling back to DB")
        pool = await get_pool()
        all_rows = await queries.find_entity_search(pool, "course")

    scoped = (
        [r for r in all_rows if r.get("university_id") == university_entity_id]
        if university_entity_id is not None
        else list(all_rows)
    )

    for candidate_rows, label in [(scoped, "scoped"), (all_rows, "global")]:
        if not candidate_rows:
            continue
        row = _exact_match(normalized, candidate_rows)
        if not row:
            row = _fuzzy_snap(normalized, candidate_rows, threshold=80)
        if row:
            logger.info("SNAP course | %s | %r -> id=%d", label, normalized, row["entity_id"])
            return await _to_slug("course", row), row["entity_id"]
        if label == "scoped" and candidate_rows is all_rows:
            break  # scoped == global, no point repeating

    logger.info("SNAP course | MISS | %r", normalized)
    return None, None


async def snap_specialization(
    name: str | None,
    university_entity_id: int | None = None,
    course_entity_id: int | None = None,
) -> str | None:
    """Hierarchically scoped specialization snap.
    Tries: course-scoped → university-scoped → global (in that order)."""
    if not name:
        return None

    normalized = name.lower().strip()
    all_rows = ENTITY_CACHE["specialization"]
    if not all_rows:
        logger.warning("Specialization cache empty — falling back to DB")
        pool = await get_pool()
        all_rows = await queries.find_entity_search(pool, "specialization")

    candidate_sets: list[tuple[list[dict[str, Any]], str]] = []
    if course_entity_id is not None:
        candidate_sets.append(
            ([r for r in all_rows if r.get("course_id") == course_entity_id], "course-scoped")
        )
    if university_entity_id is not None:
        candidate_sets.append(
            ([r for r in all_rows if r.get("university_id") == university_entity_id], "uni-scoped")
        )
    candidate_sets.append((all_rows, "global"))

    for scope_rows, label in candidate_sets:
        if not scope_rows:
            continue
        row = _exact_match(normalized, scope_rows)
        if not row:
            row = _fuzzy_snap(normalized, scope_rows, threshold=80)
        if row:
            logger.info(
                "SNAP spec | %s | %r course_id=%s uni_id=%s -> id=%d",
                label, normalized, course_entity_id, university_entity_id, row["entity_id"],
            )
            return await _to_slug("specialization", row)
        # Only fall through to wider scope if this scope didn't match
        if scope_rows is all_rows:
            break

    logger.info("SNAP spec | MISS | %r", normalized)
    return None


# ---------------------------------------------------------------------------
# Public entry point: hierarchical entity resolution
# ---------------------------------------------------------------------------

async def resolve_entities(
    message: str,
    context: dict[str, Any],
    page_university_slug: str | None = None,
) -> dict[str, Any]:
    """
    Resolve named entities from the user's message using a strict hierarchy:
      0. Short-circuit immediately for greetings (no entity needed)
      1. Extract typed intent signals (no fan-out)
      2. Snap university → get entity_id for downstream scoping
      3. Snap course ONLY if course evidence exists, scoped to university
      4. Snap specialization ONLY if spec evidence exists, scoped to course+uni
      5. Fall back to session context for missing slots
      6. Apply page-context hint for university when message needs factual data
    """
    # ── Step 0: Greeting short-circuit ─────────────────────────────────
    if is_greeting(message):
        logger.info("RESOLVE | greeting detected, skipping entity resolution: %r", message[:60])
        return {
            "raw": {},
            "university_slug": None,
            "course_slug": None,
            "specialization_slug": None,
            "mode": None,
            "max_fee": None,
            "sort_by": None,
            "order": "asc",
            "comparison_targets": [],
        }

    intent = extract_intent(message)
    logger.info("INTENT | msg=%r -> %r", message[:80], intent)

    # ── Step 1: University ──────────────────────────────────────────────────
    university_slug, university_entity_id = await snap_university(
        intent.get("university_query")
    )

    # ── Step 2: Course (scoped to university) ───────────────────────────────
    course_slug: str | None = None
    course_entity_id: int | None = None
    if "course_query" in intent:
        course_slug, course_entity_id = await snap_course(
            intent["course_query"],
            university_entity_id=university_entity_id,
        )

    # ── Step 3: Specialization (scoped to course + university) ───────────────
    specialization_slug: str | None = None
    if "specialization_query" in intent:
        specialization_slug = await snap_specialization(
            intent["specialization_query"],
            university_entity_id=university_entity_id,
            course_entity_id=course_entity_id,
        )

    # ── Step 4: Session context fallback ────────────────────────────────────
    if not university_slug:
        university_slug = context.get("current_university_slug")
    if not course_slug:
        course_slug = context.get("current_course_slug")
    if not specialization_slug:
        specialization_slug = context.get("current_specialization_slug")

    # ── Step 5: Page context hint ────────────────────────────────────────────
    if not university_slug and page_university_slug and _message_needs_entity(message):
        university_slug = page_university_slug
        logger.info(
            "ENTITY FALLBACK | page_university_slug=%r applied for: %r",
            page_university_slug, message[:80],
        )

    logger.info(
        "RESOLVED | uni=%s course=%s spec=%s",
        university_slug, course_slug, specialization_slug,
    )

    return {
        "raw": intent,
        "university_slug": university_slug,
        "course_slug": course_slug,
        "specialization_slug": specialization_slug,
        "mode": intent.get("mode"),
        "max_fee": intent.get("max_fee"),
        "sort_by": intent.get("sort_by"),
        "order": intent.get("order", "asc"),
        "comparison_targets": intent.get("comparison_targets") or [],
    }