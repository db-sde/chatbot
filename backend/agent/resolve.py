from __future__ import annotations

import json
import logging
import re
from typing import Any

from rapidfuzz import fuzz, process

from agent.llm_client import llm_client
from db import queries
from db.pool import get_pool
from settings import settings

logger = logging.getLogger(__name__)

COURSE_HINTS = ["mba", "bca", "mca", "bba", "ma", "ba", "mcom", "bcom", "btech", "mtech", "masters", "masters in", "bachelors", "bachelors in"]


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
Analyze the user message and extract search parameters for the DegreeBaba degree catalog.
Current conversation context: {json.dumps(context)}
User message: "{message}"

Return ONLY a JSON object with the following keys. Do not explain, do not add markdown:
{{
  "university": "Extracted university name or synonym, or null if none",
  "course": "Extracted course name/level (e.g. MBA, BCA, BBA), or null if none",
  "specialization": "Extracted specialization name, or null if none",
  "mode": "online | hybrid | offline | null",
  "max_fee": number or null,
  "sort_by": "fee | duration | null",
  "order": "asc | desc | null",
  "limit": number or null,
  "comparison_targets": ["list of other university or course names to compare", or empty list]
}}
"""
    extracted = await llm_client.generate_json(prompt)
    if not extracted:
        # Fall back to local regex extraction if the API keys/calls fail
        extracted = _local_extract(message)
    return extracted


async def _get_embedding(text: str) -> list[float] | None:
    if settings.gemini_api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            result = genai.embed_content(
                model="models/text-embedding-004",
                contents=text,
            )
            return result.get("embedding")
        except Exception as e:
            logger.warning("Failed to generate embedding: %s", e)
    return None


async def _snap(entity_type: str, name: str | None) -> str | None:
    if not name:
        return None
    pool = await get_pool()
    rows = await queries.find_entity_search(pool, entity_type)
    if not rows:
        return None
    
    best_score = 0
    best_row = None
    
    for row in rows:
        search_text = row["search_text"].lower()
        score = fuzz.WRatio(name.lower(), search_text)
        for word in search_text.split():
            score = max(score, fuzz.WRatio(name.lower(), word))
        if score > best_score:
            best_score = score
            best_row = row

    threshold = 85 if len(name) < 5 else 80
    if best_row and best_score >= threshold:
        return await queries.slug_for_entity_id(pool, entity_type, best_row["entity_id"])

    # Fallback: Embedding similarity
    embedding = await _get_embedding(name)
    if embedding:
        row = await pool.fetchrow(
            """
            SELECT entity_id, embedding <=> $2::vector AS distance
            FROM entity_search
            WHERE entity_type = $1 AND embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 1
            """,
            entity_type,
            embedding,
        )
        if row and row["distance"] < 0.4:
            return await queries.slug_for_entity_id(pool, entity_type, row["entity_id"])

    return None



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
