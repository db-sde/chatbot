from __future__ import annotations

import re
from typing import Any

from rapidfuzz import fuzz, process

from agent.llm_client import llm_client
from db import queries
from db.pool import get_pool


COURSE_HINTS = ["mba", "bca", "mca", "bba", "ma", "ba", "mcom", "bcom",'btech','mtech','masters','masters in','bachelors','bachelors in']


def _local_extract(message: str) -> dict[str, Any]:
    text = message.lower()
    result: dict[str, Any] = {}
    if "nmims" in text or "nims" in text:
        result["university"] = "nmims"
    if "amity" in text:
        result["university"] = "amity"
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


async def extract_entities(message: str, context: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
Return only JSON with keys university, course, specialization, mode, max_fee, sort_by, order, comparison_targets.
Current context: {context}
User message: {message}
"""
    extracted = await llm_client.generate_json(prompt)
    fallback = _local_extract(message)
    return {**fallback, **{k: v for k, v in extracted.items() if v}}


async def _snap(entity_type: str, name: str | None) -> str | None:
    if not name:
        return None
    pool = await get_pool()
    rows = await queries.find_entity_search(pool, entity_type)
    if not rows:
        return None
    choices = {row["search_text"]: row for row in rows}
    match = process.extractOne(name.lower(), choices.keys(), scorer=fuzz.WRatio)
    if not match or match[1] < 60:
        return None
    return await queries.slug_for_entity_id(pool, entity_type, choices[match[0]]["entity_id"])


async def resolve_entities(message: str, context: dict[str, Any]) -> dict[str, Any]:
    extracted = await extract_entities(message, context)
    university_slug = await _snap("university", extracted.get("university")) or context.get("current_university_slug")
    course_slug = await _snap("course", extracted.get("course")) or context.get("current_course_slug")
    specialization_slug = await _snap("specialization", extracted.get("specialization")) or context.get("current_specialization_slug")
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
