"""page_context.py — resolve URL pathname into DB-backed page context.

Parses DegreeBaba page URLs of the form:
    /colleges/{uni_slug}
    /colleges/{uni_slug}/{course_slug}
    /colleges/{uni_slug}/{course_slug}/{spec_slug}

Each resolved slug is verified against the DB so callers always receive
real entity names — slugs are never guessed or split.
"""
from __future__ import annotations

import logging
import re

from settings import settings

logger = logging.getLogger(__name__)

# Matches /colleges/{uni}  or  /colleges/{uni}/{course}  or  /colleges/{uni}/{course}/{spec}
_PATTERN = re.compile(
    r"^/colleges/(?P<uni>[^/]+)"
    r"(?:/(?P<course>[^/]+))?"
    r"(?:/(?P<spec>[^/]+))?$"
)


async def resolve_page_context(pathname: str | None, pool) -> dict:
    """Return page context extracted from *pathname*.

    Return keys (all may be None if the pathname does not match):
        page_university_slug  / page_university_name
        page_course_slug      / page_course_name
        page_spec_slug        / page_spec_name
    """
    empty: dict = {
        "page_university_slug": None,
        "page_university_name": None,
        "page_course_slug": None,
        "page_course_name": None,
        "page_spec_slug": None,
        "page_spec_name": None,
    }

    if not pathname:
        return empty

    # WordPress paths need not match chatbot's internal, globally unique slugs.
    # Only enabled deployments pay for this single indexed lookup.
    if len((settings.catalog_webhook_secret or "").strip()) >= 32:
        try:
            linked = await pool.fetchrow(
                """SELECT u.slug AS page_university_slug,u.name AS page_university_name,
                    c.slug AS page_course_slug,c.program_name AS page_course_name,
                    s.slug AS page_spec_slug,s.spec_name AS page_spec_name
                FROM catalog_sources cs
                LEFT JOIN specializations s ON cs.entity_type='specialization' AND s.id=cs.entity_id
                LEFT JOIN courses c ON (cs.entity_type='course' AND c.id=cs.entity_id) OR (cs.entity_type='specialization' AND c.id=s.course_id)
                JOIN universities u ON (cs.entity_type='university' AND u.id=cs.entity_id) OR (cs.entity_type='course' AND u.id=c.university_id) OR (cs.entity_type='specialization' AND u.id=s.university_id AND c.university_id=u.id)
                WHERE cs.source_path=$1 AND cs.source='degreebaba-parser' LIMIT 1""",
                pathname.rstrip("/") or "/",
            )
            if linked:
                return dict(linked)
        except Exception:
            logger.exception("Parser page context lookup failed; using existing URL resolver")

    m = _PATTERN.match(pathname.rstrip("/"))
    if not m:
        return empty

    uni_slug = m.group("uni")
    course_slug = m.group("course")
    spec_slug = m.group("spec")

    result = dict(empty)

    try:
        # ── University ────────────────────────────────────────────────────
        if uni_slug:
            row = await pool.fetchrow(
                "SELECT slug, name FROM universities WHERE slug = $1",
                uni_slug,
            )
            if row:
                result["page_university_slug"] = row["slug"]
                result["page_university_name"] = row["name"]
            else:
                # Slug not in DB — return nothing so the agent is not misled
                logger.debug("page_context: unknown university slug %r", uni_slug)
                return empty

        # ── Course ────────────────────────────────────────────────────────
        if course_slug and result["page_university_slug"]:
            row = await pool.fetchrow(
                """
                SELECT c.slug, c.program_name
                FROM courses c
                JOIN universities u ON u.id = c.university_id
                WHERE c.slug = $1 AND u.slug = $2
                """,
                course_slug,
                result["page_university_slug"],
            )
            if row:
                result["page_course_slug"] = row["slug"]
                result["page_course_name"] = row["program_name"]

        # ── Specialization ────────────────────────────────────────────────
        if spec_slug and result["page_course_slug"]:
            row = await pool.fetchrow(
                """
                SELECT s.slug, s.spec_name
                FROM specializations s
                JOIN courses c ON c.id = s.course_id
                WHERE s.slug = $1 AND c.slug = $2
                """,
                spec_slug,
                result["page_course_slug"],
            )
            if row:
                result["page_spec_slug"] = row["slug"]
                result["page_spec_name"] = row["spec_name"]

    except Exception:
        logger.exception("resolve_page_context failed for pathname=%r", pathname)
        return empty

    return result
