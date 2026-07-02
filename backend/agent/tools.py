from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from db import queries
from db.pool import get_pool


async def get_fee(university_slug: str, course_slug: str | None = None, specialization_slug: str | None = None) -> dict:
    pool = await get_pool()
    row = await queries.get_fee(pool, university_slug, course_slug, specialization_slug)
    return row or {"not_found": True}


async def get_eligibility(university_slug: str, course_slug: str) -> dict:
    pool = await get_pool()
    row = await queries.get_eligibility(pool, university_slug, course_slug)
    return row or {"not_found": True}


async def list_courses(
    course_type: str | None = None,
    mode: str | None = None,
    max_fee: float | None = None,
    min_naac: str | None = None,
    sort_by: str | None = None,
    order: str = "asc",
    limit: int = 5,
) -> list[dict]:
    pool = await get_pool()
    return await queries.list_courses(pool, course_type, mode, max_fee, min_naac, sort_by, order, limit)


async def compare_entities(entity_type: str, slugs: list[str], fields: list[str]) -> list[dict]:
    pool = await get_pool()
    return await queries.compare_entities(pool, entity_type, slugs, fields)


async def get_faq(entity_type: str, entity_slug: str, query_text: str | None = None) -> list[dict]:
    pool = await get_pool()
    return await queries.get_faq(pool, entity_type, entity_slug, query_text)


async def capture_lead(
    session_id: str,
    name: str,
    phone: str,
    email: str | None,
    course_interest: str | None,
    trigger_reason: str,
) -> dict:
    pool = await get_pool()
    return await queries.insert_lead(pool, session_id, name, phone, email, course_interest, trigger_reason)


async def log_anonymous_signal(session_id: str, university_slug: str | None, course_slug: str | None, question_type: str) -> None:
    pool = await get_pool()
    await queries.log_signal(pool, session_id, university_slug, course_slug, question_type)


async def log_unanswered(session_id: str, question: str, university_slug: str | None, course_slug: str | None) -> None:
    pool = await get_pool()
    await queries.log_unanswered(pool, session_id, question, university_slug, course_slug)


@tool
async def get_fee_tool(university_slug: str, course_slug: str | None = None, specialization_slug: str | None = None) -> dict:
    """Return fee data for a university, course, or specialization."""
    return await get_fee(university_slug, course_slug, specialization_slug)


@tool
async def get_eligibility_tool(university_slug: str, course_slug: str) -> dict:
    """Return eligibility data for a course at a university."""
    return await get_eligibility(university_slug, course_slug)


@tool
async def list_courses_tool(
    course_type: str | None = None,
    mode: str | None = None,
    max_fee: float | None = None,
    min_naac: str | None = None,
    sort_by: str | None = None,
    order: str = "asc",
    limit: int = 5,
) -> list[dict]:
    """List matching courses with optional fee, mode, and sorting filters."""
    return await list_courses(course_type, mode, max_fee, min_naac, sort_by, order, limit)


@tool
async def compare_entities_tool(entity_type: str, slugs: list[str], fields: list[str]) -> list[dict]:
    """Compare approved fields for universities, courses, or specializations."""
    return await compare_entities(entity_type, slugs, fields)


@tool
async def get_faq_tool(entity_type: str, entity_slug: str, query_text: str | None = None) -> list[dict]:
    """Return FAQs for a university, course, or specialization."""
    return await get_faq(entity_type, entity_slug, query_text)


TOOLS = [get_fee_tool, get_eligibility_tool, list_courses_tool, compare_entities_tool, get_faq_tool]
