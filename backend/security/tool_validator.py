"""
security/tool_validator.py — validate LLM tool arguments before DB execution.

Never trust the LLM's tool arguments.  Each validator:
  1. Checks argument format (non-empty, safe characters, sane length).
  2. Confirms the entity actually exists in the database.
  3. Returns a ToolValidationResult — caller rejects on is_valid=False.

This prevents:
  - SQL-injection attempts via slug arguments
  - Hallucinated entity slugs causing misleading "not found" answers
  - Excessively long arguments crashing queries
"""
from __future__ import annotations

import re
from typing import TypedDict

from db import queries
from db.pool import get_pool

# Slugs are lowercase alphanumeric + hyphens only.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")
_MAX_SLUG_LEN = 80


class ToolValidationResult(TypedDict):
    is_valid: bool
    error: str | None   # None when valid


def _check_slug_format(slug: str, label: str) -> ToolValidationResult | None:
    """Returns an error result if the slug is malformed; None otherwise."""
    if not slug or not isinstance(slug, str):
        return ToolValidationResult(is_valid=False, error=f"{label} is required")
    if len(slug) > _MAX_SLUG_LEN:
        return ToolValidationResult(is_valid=False, error=f"{label} is too long")
    if not _SLUG_RE.match(slug):
        return ToolValidationResult(is_valid=False, error=f"{label} contains invalid characters")
    return None


async def validate_university_slug(slug: str) -> ToolValidationResult:
    fmt = _check_slug_format(slug, "university_slug")
    if fmt:
        return fmt
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM universities WHERE slug = $1", slug)
    if not exists:
        return ToolValidationResult(is_valid=False, error=f"University '{slug}' not found in catalog")
    return ToolValidationResult(is_valid=True, error=None)


async def validate_course_slug(slug: str) -> ToolValidationResult:
    fmt = _check_slug_format(slug, "course_slug")
    if fmt:
        return fmt
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM courses WHERE slug = $1", slug)
    if not exists:
        return ToolValidationResult(is_valid=False, error=f"Course '{slug}' not found in catalog")
    return ToolValidationResult(is_valid=True, error=None)


async def validate_specialization_slug(slug: str) -> ToolValidationResult:
    fmt = _check_slug_format(slug, "specialization_slug")
    if fmt:
        return fmt
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM specializations WHERE slug = $1", slug)
    if not exists:
        return ToolValidationResult(is_valid=False, error=f"Specialization '{slug}' not found in catalog")
    return ToolValidationResult(is_valid=True, error=None)


async def validate_entity_type(entity_type: str) -> ToolValidationResult:
    """entity_type must be one of the three known values."""
    if entity_type not in {"university", "course", "specialization"}:
        return ToolValidationResult(
            is_valid=False,
            error=f"entity_type must be university, course, or specialization — got '{entity_type}'"
        )
    return ToolValidationResult(is_valid=True, error=None)
