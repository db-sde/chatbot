"""
security/tool_validator.py — validate LLM tool arguments before DB execution.

Never trust the LLM's tool arguments.  Each validator:
  1. Checks argument format (non-empty, safe characters, sane length).
  2. Normalizes university aliases to the canonical catalog slug.
  3. Confirms the entity actually exists in the database.
  4. Returns a ToolValidationResult — caller rejects on is_valid=False.

This prevents:
  - SQL-injection attempts via slug arguments
  - Hallucinated entity slugs causing misleading "not found" answers
  - Alias/canonical mismatches (e.g. nmims vs nmims-online)
  - Excessively long arguments crashing queries
"""
from __future__ import annotations

import logging
import re
from typing import TypedDict

from db.pool import get_pool

logger = logging.getLogger(__name__)

# Slugs are lowercase alphanumeric + hyphens only.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")
_MAX_SLUG_LEN = 80


class ToolValidationResult(TypedDict):
    is_valid: bool
    error: str | None   # None when valid
    canonical_slug: str | None  # normalized slug when valid (or best-effort)


def _check_slug_format(slug: str, label: str) -> ToolValidationResult | None:
    """Returns an error result if the slug is malformed; None otherwise."""
    if not slug or not isinstance(slug, str):
        return ToolValidationResult(is_valid=False, error=f"{label} is required", canonical_slug=None)
    if len(slug) > _MAX_SLUG_LEN:
        return ToolValidationResult(is_valid=False, error=f"{label} is too long", canonical_slug=None)
    if not _SLUG_RE.match(slug):
        return ToolValidationResult(
            is_valid=False,
            error=f"{label} contains invalid characters",
            canonical_slug=None,
        )
    return None


async def normalize_university_slug(slug: str) -> str:
    """
    Map alias / brand / alternate slug to the catalog canonical slug.
    Falls back to the original slug if no alias is known.
    """
    if not slug:
        return slug
    try:
        from agent.resolve import resolve_university_alias, UNIVERSITY_ALIAS_INDEX

        canonical = resolve_university_alias(slug)
        if canonical and canonical != slug:
            logger.info("CANONICAL SLUG | tool alias %r -> %s", slug, canonical)
            return canonical

        # Direct DB existence of original is fine; also try head of hyphenated
        pool = await get_pool()
        exists = await pool.fetchval("SELECT 1 FROM universities WHERE slug = $1", slug)
        if exists:
            return slug

        # If alias index empty (cache not loaded), try fuzzy brand head
        head = slug.split("-")[0]
        if head and head != slug:
            alt = resolve_university_alias(head)
            if alt:
                logger.info("CANONICAL SLUG | tool head %r -> %s", slug, alt)
                return alt

        # Last resort: scan alias index for partial brand match
        for alias, meta in UNIVERSITY_ALIAS_INDEX.items():
            if alias == slug or alias == head:
                return meta["canonical_slug"]
    except Exception as exc:  # noqa: BLE001
        logger.debug("normalize_university_slug fallback for %r: %s", slug, exc)
    return slug


async def validate_university_slug(slug: str) -> ToolValidationResult:
    fmt = _check_slug_format(slug, "university_slug")
    if fmt:
        return fmt

    canonical = await normalize_university_slug(slug)
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM universities WHERE slug = $1", canonical)
    if not exists:
        # One more attempt: original slug as-is (cache cold)
        if canonical != slug:
            exists = await pool.fetchval("SELECT 1 FROM universities WHERE slug = $1", slug)
            if exists:
                return ToolValidationResult(is_valid=True, error=None, canonical_slug=slug)
        return ToolValidationResult(
            is_valid=False,
            error=f"University '{slug}' not found in catalog",
            canonical_slug=None,
        )
    if canonical != slug:
        logger.info("CANONICAL SLUG | validated %r as %s", slug, canonical)
    return ToolValidationResult(is_valid=True, error=None, canonical_slug=canonical)


async def validate_course_slug(slug: str) -> ToolValidationResult:
    fmt = _check_slug_format(slug, "course_slug")
    if fmt:
        return fmt
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM courses WHERE slug = $1", slug)
    if not exists:
        return ToolValidationResult(
            is_valid=False,
            error=f"Course '{slug}' not found in catalog",
            canonical_slug=None,
        )
    return ToolValidationResult(is_valid=True, error=None, canonical_slug=slug)


async def validate_specialization_slug(slug: str) -> ToolValidationResult:
    fmt = _check_slug_format(slug, "specialization_slug")
    if fmt:
        return fmt
    pool = await get_pool()
    exists = await pool.fetchval("SELECT 1 FROM specializations WHERE slug = $1", slug)
    if not exists:
        return ToolValidationResult(
            is_valid=False,
            error=f"Specialization '{slug}' not found in catalog",
            canonical_slug=None,
        )
    return ToolValidationResult(is_valid=True, error=None, canonical_slug=slug)


async def validate_entity_type(entity_type: str) -> ToolValidationResult:
    """entity_type must be one of the three known values."""
    if entity_type not in {"university", "course", "specialization"}:
        return ToolValidationResult(
            is_valid=False,
            error=f"entity_type must be university, course, or specialization — got '{entity_type}'",
            canonical_slug=None,
        )
    return ToolValidationResult(is_valid=True, error=None, canonical_slug=None)
