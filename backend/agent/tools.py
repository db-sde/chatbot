"""LangGraph-facing tool layer for the DegreeBaba AI advisor.

Design contract
----------------
- Every tool validates its slug / entity_type arguments via
  `security.tool_validator` BEFORE touching the database.
- Every failure path (validation error, empty result, or unexpected
  exception) returns the SAME envelope shape:
      {"not_found": True, "reason": "<short_code>", ...context}
  This uniform contract is what lets the graph's planner apply a single,
  simple stop-condition ("if not_found, don't blindly retry the same
  call") instead of needing bespoke handling per tool.
- No tool ever raises. Unexpected exceptions are logged server-side and
  converted to a safe `_fail("internal_error")` result, so a DB hiccup
  can never break the SSE stream or crash an agent turn.
- Tool docstrings are deliberately written to disambiguate from sibling
  tools (e.g. "use X for fee questions, not Y"), because the agent's
  tool choice is driven almost entirely by these descriptions. Most of
  the historical tool-loop problems traced back to missing or ambiguous
  coverage here, not to the planner itself.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from db import queries
from db.pool import get_pool
from security.tool_validator import (
    validate_course_slug,
    validate_entity_type,
    validate_specialization_slug,
    validate_university_slug,
)
from observability import timed_tool_execution

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 5
MAX_LIMIT = 20
MAX_COMPARE_ITEMS = 5

# Whitelist of columns that may be requested via a `fields` argument.
# Anything outside this set is silently dropped before it ever reaches
# the query layer — defense in depth even if queries.py already
# parameterizes safely.
ALLOWED_COMPARISON_FIELDS = {
    "program_name", "spec_name", "name", "full_name",
    "total_fee", "starting_fee", "duration", "mode",
    "naac_grade", "ugc_status", "ugc_approved",
    "eligibility_summary", "established_year",
}

DEFAULT_COMPARISON_FIELDS = [
    "program_name", "total_fee", "duration", "mode",
    "naac_grade", "ugc_status", "eligibility_summary",
]


# ---------------------------------------------------------------------------
# Small internal helpers
# ---------------------------------------------------------------------------

def _fail(reason: str | None, **extra: Any) -> dict[str, Any]:
    """Uniform failure envelope. See module docstring for why this matters."""
    payload: dict[str, Any] = {"not_found": True, "reason": reason or "unknown_error"}
    payload.update(extra)
    return payload


def _clamp_limit(limit: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    if limit is None:
        return default
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, maximum))


def _normalize_str_list(value: list[str] | str | None) -> list[str]:
    """Agents occasionally pass a bare string where a list is expected — normalize defensively."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [v for v in value if v]
    except TypeError:
        return [str(value)]


def _filter_fields(fields: list[str] | str | None, default: list[str]) -> list[str]:
    normalized = _normalize_str_list(fields)
    filtered = [f for f in normalized if f in ALLOWED_COMPARISON_FIELDS]
    return filtered or default


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


# ---------------------------------------------------------------------------
# Internal helpers (called by graph.py directly, not via LangChain tools)
# ---------------------------------------------------------------------------

async def get_fee(university_slug: str, course_slug: str | None = None, specialization_slug: str | None = None) -> dict:
    try:
        pool = await get_pool()
        row = await queries.get_fee(pool, university_slug, course_slug, specialization_slug)
    except Exception:
        logger.exception("get_fee failed (university=%s course=%s spec=%s)", university_slug, course_slug, specialization_slug)
        return _fail("internal_error")
    if row:
        logger.info("get_fee | uni=%s course=%s spec=%s -> total_fee=%s starting_fee=%s",
                    university_slug, course_slug, specialization_slug,
                    row.get("total_fee"), row.get("starting_fee"))
        return row
    logger.info("get_fee | NOT FOUND uni=%s course=%s spec=%s", university_slug, course_slug, specialization_slug)
    return _fail(
        "fee_not_found",
        university_slug=university_slug,
        course_slug=course_slug,
        specialization_slug=specialization_slug,
    )


async def get_eligibility(university_slug: str, course_slug: str) -> dict:
    try:
        pool = await get_pool()
        row = await queries.get_eligibility(pool, university_slug, course_slug)
    except Exception:
        logger.exception("get_eligibility failed (university=%s course=%s)", university_slug, course_slug)
        return _fail("internal_error")
    if row:
        logger.info("get_eligibility | uni=%s course=%s -> found", university_slug, course_slug)
        return row
    logger.info("get_eligibility | NOT FOUND uni=%s course=%s", university_slug, course_slug)
    return _fail("eligibility_not_found", university_slug=university_slug, course_slug=course_slug)


async def list_courses(
    course_type: str | None = None,
    mode: str | None = None,
    max_fee: float | None = None,
    min_naac: str | None = None,
    sort_by: str | None = None,
    order: str = "asc",
    limit: int = DEFAULT_LIMIT,
) -> list[dict] | dict:
    try:
        pool = await get_pool()
        rows = await queries.list_courses(pool, course_type, mode, max_fee, min_naac, sort_by, order, _clamp_limit(limit))
    except Exception:
        logger.exception("list_courses failed (type=%s mode=%s max_fee=%s)", course_type, mode, max_fee)
        return _fail("internal_error")
    if not rows:
        return _fail("no_matching_courses", course_type=course_type, mode=mode, max_fee=max_fee)
    return rows


async def compare_entities(entity_type: str, slugs: list[str], fields: list[str]) -> list[dict] | dict:
    try:
        pool = await get_pool()
        rows = await queries.compare_entities(pool, entity_type, slugs, fields)
    except Exception:
        logger.exception("compare_entities failed (type=%s slugs=%s)", entity_type, slugs)
        return _fail("internal_error")
    if not rows:
        return _fail("comparison_unavailable", entity_type=entity_type, slugs=slugs)
    return rows


async def get_faq(entity_type: str, entity_slug: str, query_text: str | None = None) -> list[dict] | dict:
    try:
        pool = await get_pool()
        rows = await queries.get_faq(pool, entity_type, entity_slug, query_text)
    except Exception:
        logger.exception("get_faq failed (type=%s slug=%s)", entity_type, entity_slug)
        return _fail("internal_error")
    if not rows:
        return _fail("no_faqs_found", entity_type=entity_type, entity_slug=entity_slug)
    return rows


async def capture_lead(
    session_id: str,
    name: str,
    phone: str,
    email: str | None,
    course_interest: str | None,
    trigger_reason: str,
) -> dict:
    try:
        pool = await get_pool()
        # Ensure session exists in DB before inserting lead to avoid foreign key constraint issues (e.g. after truncation)
        session_exists = await pool.fetchval("SELECT 1 FROM sessions WHERE id = $1::uuid", session_id)
        if not session_exists:
            await pool.execute(
                "INSERT INTO sessions (id, site_id, page_university_slug) VALUES ($1::uuid, $2, $3) ON CONFLICT DO NOTHING",
                session_id,
                "degreebaba_dev",
                None
            )
        if trigger_reason == "widget_form":
            sess_trigger = await pool.fetchval("SELECT lead_ask_triggered_by FROM sessions WHERE id = $1::uuid", session_id)
            if sess_trigger:
                trigger_reason = sess_trigger
            else:
                trigger_reason = "Score Engine"
        return await queries.insert_lead(pool, session_id, name, phone, email, course_interest, trigger_reason)
    except Exception:
        logger.exception("capture_lead failed (session=%s)", session_id)
        return _fail("lead_capture_failed", session_id=session_id)


async def log_anonymous_signal(session_id: str, university_slug: str | None, course_slug: str | None, question_type: str) -> None:
    try:
        pool = await get_pool()
        await queries.log_signal(pool, session_id, university_slug, course_slug, question_type)
    except Exception:
        # Analytics/logging must never break the main chat flow.
        logger.exception("log_anonymous_signal failed (session=%s)", session_id)


async def log_unanswered(session_id: str, question: str, university_slug: str | None, course_slug: str | None) -> None:
    try:
        pool = await get_pool()
        await queries.log_unanswered(pool, session_id, question, university_slug, course_slug)
    except Exception:
        logger.exception("log_unanswered failed (session=%s)", session_id)


async def get_university_overview(university_slug: str) -> dict:
    try:
        pool = await get_pool()
        row = await queries.get_university_overview(pool, university_slug)
    except Exception:
        logger.exception("get_university_overview failed (university=%s)", university_slug)
        return _fail("internal_error")
    if row:
        logger.info("get_university_overview | uni=%s -> name=%s naac=%s",
                    university_slug, row.get("name"), row.get("naac_grade"))
        return row
    logger.info("get_university_overview | NOT FOUND uni=%s", university_slug)
    return _fail("university_not_found", university_slug=university_slug)


async def get_university_programs(university_slug: str, limit: int = DEFAULT_LIMIT) -> list[dict] | dict:
    try:
        pool = await get_pool()
        rows = await queries.get_university_programs(pool, university_slug, limit=_clamp_limit(limit))
    except Exception:
        logger.exception("get_university_programs failed (university=%s)", university_slug)
        return _fail("internal_error")
    if not rows:
        return _fail("no_programs_found", university_slug=university_slug)
    return rows


async def get_program_details(course_slug: str, university_slug: str | None = None) -> dict:
    try:
        pool = await get_pool()
        row = await queries.get_program_details(pool, course_slug, university_slug)
    except Exception:
        logger.exception("get_program_details failed (course=%s university=%s)", course_slug, university_slug)
        return _fail("internal_error")
    return row or _fail("course_not_found", course_slug=course_slug, university_slug=university_slug)


async def get_specializations(course_slug: str, university_slug: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict] | dict:
    try:
        pool = await get_pool()
        rows = await queries.get_specializations(pool, course_slug, university_slug, limit=_clamp_limit(limit))
    except Exception:
        logger.exception("get_specializations failed (course=%s university=%s)", course_slug, university_slug)
        return _fail("internal_error")
    if not rows:
        return _fail("no_specializations_found", course_slug=course_slug, university_slug=university_slug)
    return rows


async def search_catalog(query_text: str, entity_type: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict] | dict:
    try:
        pool = await get_pool()
        rows = await queries.search_catalog(pool, query_text, entity_type=entity_type, limit=_clamp_limit(limit))
    except Exception:
        logger.exception("search_catalog failed (query=%r type=%s)", query_text, entity_type)
        return _fail("internal_error")
    if not rows:
        return _fail("no_matches_found", query_text=query_text, entity_type=entity_type)
    return rows


async def compare_programs(course_slugs: list[str], fields: list[str] | None = None) -> list[dict] | dict:
    fields = _filter_fields(fields, DEFAULT_COMPARISON_FIELDS)
    try:
        pool = await get_pool()
        rows = await queries.compare_programs(pool, course_slugs, fields)
    except Exception:
        logger.exception("compare_programs failed (slugs=%s)", course_slugs)
        return _fail("internal_error")
    if not rows:
        return _fail("comparison_unavailable", course_slugs=course_slugs)
    return rows


# ---------------------------------------------------------------------------
# LangChain @tool wrappers — validated, agent-facing
# ---------------------------------------------------------------------------

@tool
@timed_tool_execution
async def get_fee_tool(university_slug: str, course_slug: str | None = None, specialization_slug: str | None = None) -> dict:
    """Return fee data (total fee, starting fee, EMI/fee-plan breakdown) for a university,
    and optionally a specific course or specialization within it.
    Use ONLY for cost/fee/price questions.
    Do NOT use this to list programs (use get_university_programs_tool) or to check
    eligibility (use get_eligibility_tool)."""
    v = await validate_university_slug(university_slug)
    if not v["is_valid"]:
        return _fail(v["error"], university_slug=university_slug)

    if course_slug:
        vc = await validate_course_slug(course_slug)
        if not vc["is_valid"]:
            return _fail(vc["error"], course_slug=course_slug)

    if specialization_slug:
        vs = await validate_specialization_slug(specialization_slug)
        if not vs["is_valid"]:
            return _fail(vs["error"], specialization_slug=specialization_slug)

    return await get_fee(university_slug, course_slug, specialization_slug)


@tool
@timed_tool_execution
async def get_eligibility_tool(university_slug: str, course_slug: str) -> dict:
    """Return eligibility criteria for a specific course at a specific university.
    Use ONLY for eligibility / admission-criteria questions.
    Do NOT use this for fee questions — use get_fee_tool instead."""
    v = await validate_university_slug(university_slug)
    if not v["is_valid"]:
        return _fail(v["error"], university_slug=university_slug)

    vc = await validate_course_slug(course_slug)
    if not vc["is_valid"]:
        return _fail(vc["error"], course_slug=course_slug)

    return await get_eligibility(university_slug, course_slug)


@tool
@timed_tool_execution
async def get_university_overview_tool(university_slug: str) -> dict:
    """Return a university's general profile: about content, NAAC grade, UGC approval
    status, why-choose content, and placement summary.
    Use for broad 'tell me about X university' questions, INCLUDING when the user
    refers to 'this university' / 'this page' — the resolver fills in the correct
    slug from page context before this tool is called.
    Do NOT use this for a specific course's details — use get_program_details_tool."""
    v = await validate_university_slug(university_slug)
    if not v["is_valid"]:
        return _fail(v["error"], university_slug=university_slug)
    return await get_university_overview(university_slug)


@tool
@timed_tool_execution
async def get_university_programs_tool(university_slug: str, limit: int = DEFAULT_LIMIT) -> list[dict] | dict:
    """List all courses/programs offered by ONE specific, already-known university.
    Use for 'what programs/courses does X offer' questions.
    Do NOT use this for filtering or ranking across MANY universities —
    use list_courses_tool for that instead."""
    v = await validate_university_slug(university_slug)
    if not v["is_valid"]:
        return _fail(v["error"], university_slug=university_slug)
    return await get_university_programs(university_slug, limit=limit)


@tool
@timed_tool_execution
async def get_program_details_tool(course_slug: str, university_slug: str | None = None) -> dict:
    """Return full details (duration, fee, eligibility, placement, certificate info)
    for ONE specific, already-known course.
    Use for 'tell me about X's Y program' questions.
    Do NOT use this for fee-only questions — use get_fee_tool for a faster, focused answer."""
    vc = await validate_course_slug(course_slug)
    if not vc["is_valid"]:
        return _fail(vc["error"], course_slug=course_slug)

    if university_slug:
        vu = await validate_university_slug(university_slug)
        if not vu["is_valid"]:
            return _fail(vu["error"], university_slug=university_slug)

    return await get_program_details(course_slug, university_slug)


@tool
@timed_tool_execution
async def get_specializations_tool(course_slug: str, university_slug: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict] | dict:
    """List all specializations available under ONE specific, already-known course
    (e.g. all MBA specializations at NMIMS).
    Use for 'what specializations does X offer' questions."""
    vc = await validate_course_slug(course_slug)
    if not vc["is_valid"]:
        return _fail(vc["error"], course_slug=course_slug)

    if university_slug:
        vu = await validate_university_slug(university_slug)
        if not vu["is_valid"]:
            return _fail(vu["error"], university_slug=university_slug)

    return await get_specializations(course_slug, university_slug, limit=limit)


@tool
@timed_tool_execution
async def list_courses_tool(
    course_type: str | None = None,
    mode: str | None = None,
    max_fee: float | None = None,
    min_naac: str | None = None,
    sort_by: str | None = None,
    order: str = "asc",
    limit: int = DEFAULT_LIMIT,
) -> list[dict] | dict:
    """Search and filter courses ACROSS THE WHOLE CATALOG — e.g. 'top 5 cheapest
    online MBAs', 'MBA programs under 2 lakh with NAAC A+'.
    Use for filtered / ranked / aggregate questions spanning multiple universities.
    Do NOT use this to list one already-known university's programs —
    use get_university_programs_tool for that instead."""
    return await list_courses(course_type, mode, max_fee, min_naac, sort_by, order, limit)


@tool
@timed_tool_execution
async def search_catalog_tool(query_text: str, entity_type: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict] | dict:
    """Broad semantic/keyword search across the ENTIRE catalog for questions that don't
    map cleanly to a specific university/course lookup — e.g. 'show me finance-related
    courses', 'programs good for working professionals'.
    Use this as a FALLBACK DISCOVERY step when no other tool fits, INSTEAD OF repeating
    a failed specific lookup with different guesses."""
    query_text = (query_text or "").strip()
    if not query_text:
        return _fail("empty_query")

    if entity_type:
        vt = await validate_entity_type(entity_type)
        if not vt["is_valid"]:
            return _fail(vt["error"], entity_type=entity_type)

    return await search_catalog(query_text, entity_type=entity_type, limit=limit)


@tool
@timed_tool_execution
async def compare_entities_tool(entity_type: str, slugs: list[str], fields: list[str]) -> list[dict] | dict:
    """Low-level comparison of explicit fields across explicit entities of ONE type
    (university, course, or specialization) — e.g. comparing two universities directly.
    Prefer compare_programs_tool for course-vs-course comparisons; it provides
    sensible default fields automatically instead of requiring them to be specified."""
    vt = await validate_entity_type(entity_type)
    if not vt["is_valid"]:
        return _fail(vt["error"], entity_type=entity_type)

    slugs = _dedupe_preserve_order(_normalize_str_list(slugs))[:MAX_COMPARE_ITEMS]
    if len(slugs) < 2:
        return _fail("need_at_least_two_entities", entity_type=entity_type, slugs=slugs)

    validator = {
        "university": validate_university_slug,
        "course": validate_course_slug,
        "specialization": validate_specialization_slug,
    }[entity_type]

    valid_slugs: list[str] = []
    for slug in slugs:
        v = await validator(slug)
        if v["is_valid"]:
            valid_slugs.append(slug)

    if len(valid_slugs) < 2:
        return _fail(
            "insufficient_valid_entities",
            entity_type=entity_type,
            slugs=slugs,
            valid_slugs=valid_slugs,
        )

    fields = _filter_fields(fields, DEFAULT_COMPARISON_FIELDS)
    return await compare_entities(entity_type, valid_slugs, fields)


@tool
@timed_tool_execution
async def compare_programs_tool(course_slugs: list[str], fields: list[str] | None = None) -> list[dict] | dict:
    """Compare two or more specific, already-known COURSES side by side
    (e.g. 'compare NMIMS Online MBA with Amity Online MBA') across a sensible
    default set of fields (fee, duration, eligibility, NAAC grade, UGC status).
    Provide exact course slugs. This is the preferred tool for course-vs-course
    comparisons — use compare_entities_tool only for university-vs-university
    or specialization-vs-specialization comparisons."""
    slugs = _dedupe_preserve_order(_normalize_str_list(course_slugs))[:MAX_COMPARE_ITEMS]
    if len(slugs) < 2:
        return _fail("need_at_least_two_courses", course_slugs=slugs)

    valid_slugs: list[str] = []
    for slug in slugs:
        vc = await validate_course_slug(slug)
        if vc["is_valid"]:
            valid_slugs.append(slug)

    if len(valid_slugs) < 2:
        return _fail("insufficient_valid_courses", course_slugs=slugs, valid_slugs=valid_slugs)

    return await compare_programs(valid_slugs, fields)


@tool
@timed_tool_execution
async def get_faq_tool(entity_type: str, entity_slug: str, query_text: str | None = None) -> list[dict] | dict:
    """Return FAQs for a university, course, or specialization.
    Use for policy / definition / general-knowledge-style questions about a specific
    entity (e.g. 'is this valid for government jobs?')."""
    vt = await validate_entity_type(entity_type)
    if not vt["is_valid"]:
        return _fail(vt["error"], entity_type=entity_type)

    validator = {
        "university": validate_university_slug,
        "course": validate_course_slug,
        "specialization": validate_specialization_slug,
    }[entity_type]
    v = await validator(entity_slug)
    if not v["is_valid"]:
        return _fail(v["error"], entity_type=entity_type, entity_slug=entity_slug)

    return await get_faq(entity_type, entity_slug, query_text)


# ---------------------------------------------------------------------------
# Agent-exposed tool list
# ---------------------------------------------------------------------------

TOOLS = [
    get_fee_tool,
    get_eligibility_tool,
    get_university_overview_tool,
    get_university_programs_tool,
    get_program_details_tool,
    get_specializations_tool,
    list_courses_tool,
    search_catalog_tool,
    compare_entities_tool,
    compare_programs_tool,
    get_faq_tool,
]