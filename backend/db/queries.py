from __future__ import annotations

import json
from typing import Any


def dict_row(row: Any) -> dict[str, Any] | None:
    return dict(row) if row else None


def dict_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


async def ensure_session(pool, session_id: str, site_id: str, page_university_slug: str | None) -> None:
    await pool.execute(
        """
        INSERT INTO sessions(id, site_id, page_university_slug)
        VALUES($1::uuid, $2, $3)
        ON CONFLICT (id) DO UPDATE SET last_active_at = now(),
            page_university_slug = COALESCE(EXCLUDED.page_university_slug, sessions.page_university_slug)
        """,
        session_id,
        site_id,
        page_university_slug,
    )
    # Insert a blank session_context row — conversational slugs start as NULL.
    # The page_university_slug is intentionally NOT written here; it is a
    # passive page hint, not evidence of user intent.
    await pool.execute(
        """
        INSERT INTO session_context(session_id)
        VALUES($1::uuid)
        ON CONFLICT (session_id) DO NOTHING
        """,
        session_id,
    )


async def get_session_context(pool, session_id: str) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        SELECT current_university_slug, current_course_slug, current_specialization_slug
        FROM session_context
        WHERE session_id = $1::uuid
        """,
        session_id,
    )
    return dict_row(row) or {}



async def update_session_context(pool, session_id: str, university_slug: str | None, course_slug: str | None, specialization_slug: str | None) -> None:
    await pool.execute(
        """
        INSERT INTO session_context(session_id, current_university_slug, current_course_slug, current_specialization_slug)
        VALUES($1::uuid, $2, $3, $4)
        ON CONFLICT (session_id) DO UPDATE SET
            current_university_slug = COALESCE($2, session_context.current_university_slug),
            current_course_slug = COALESCE($3, session_context.current_course_slug),
            current_specialization_slug = COALESCE($4, session_context.current_specialization_slug),
            last_updated = now()
        """,
        session_id,
        university_slug,
        course_slug,
        specialization_slug,
    )


async def insert_message(pool, session_id: str, role: str, content: str, tool_calls: list[dict] | None = None) -> None:
    await pool.execute(
        """
        INSERT INTO messages(session_id, role, content, tool_calls)
        VALUES($1::uuid, $2, $3, $4::jsonb)
        """,
        session_id,
        role,
        content,
        json.dumps(tool_calls) if tool_calls is not None else None,
    )
    await pool.execute("UPDATE sessions SET message_count = message_count + 1, last_active_at = now() WHERE id = $1::uuid", session_id)


async def recent_messages(pool, session_id: str, limit: int = 8) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT role, content, tool_calls, created_at
        FROM messages
        WHERE session_id = $1::uuid
        ORDER BY id DESC
        LIMIT $2
        """,
        session_id,
        limit,
    )
    return list(reversed(dict_rows(rows)))


async def count_site_messages_today(pool, site_id: str) -> int:
    value = await pool.fetchval(
        """
        SELECT count(*)
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.site_id = $1 AND m.created_at >= date_trunc('day', now())
        """,
        site_id,
    )
    return int(value or 0)


async def find_entity_search(pool, entity_type: str) -> list[dict[str, Any]]:
    rows = await pool.fetch("SELECT entity_type, entity_id, search_text FROM entity_search WHERE entity_type = $1", entity_type)
    return dict_rows(rows)


async def slug_for_entity_id(pool, entity_type: str, entity_id: int) -> str | None:
    table = {"university": "universities", "course": "courses", "specialization": "specializations"}[entity_type]
    return await pool.fetchval(f"SELECT slug FROM {table} WHERE id = $1", entity_id)


async def get_fee(pool, university_slug: str, course_slug: str | None = None, specialization_slug: str | None = None) -> dict[str, Any] | None:
    if specialization_slug:
        return dict_row(
            await pool.fetchrow(
                """
                SELECT s.slug, s.spec_name AS name, s.total_fee, s.emi_amount, u.name AS university_name, c.program_name
                FROM specializations s
                JOIN universities u ON u.id = s.university_id
                LEFT JOIN courses c ON c.id = s.course_id
                WHERE u.slug = $1 AND s.slug = $2
                """,
                university_slug,
                specialization_slug,
            )
        )
    if course_slug:
        return dict_row(
            await pool.fetchrow(
                """
                SELECT c.slug, c.program_name AS name, c.total_fee, c.starting_fee, c.emi_amount, u.name AS university_name
                FROM courses c
                JOIN universities u ON u.id = c.university_id
                WHERE u.slug = $1 AND c.slug = $2
                """,
                university_slug,
                course_slug,
            )
        )
    return dict_row(await pool.fetchrow("SELECT slug, name, starting_fee, admission_fee_note, emi_content FROM universities WHERE slug = $1", university_slug))


async def get_eligibility(pool, university_slug: str, course_slug: str) -> dict[str, Any] | None:
    return dict_row(
        await pool.fetchrow(
            """
            SELECT c.slug, c.program_name, c.eligibility_summary, c.eligibility_content, u.name AS university_name
            FROM courses c
            JOIN universities u ON u.id = c.university_id
            WHERE u.slug = $1 AND c.slug = $2
            """,
            university_slug,
            course_slug,
        )
    )


async def list_courses(pool, course_type: str | None, mode: str | None, max_fee: float | None, min_naac: str | None, sort_by: str | None, order: str, limit: int) -> list[dict[str, Any]]:
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    sort_expr = "c.total_fee" if sort_by == "fee" else "c.duration" if sort_by == "duration" else "c.program_name"
    rows = await pool.fetch(
        f"""
        SELECT c.slug, c.program_name, c.duration, c.mode, c.total_fee, c.starting_fee, c.naac_grade, u.slug AS university_slug, u.name AS university_name
        FROM courses c
        JOIN universities u ON u.id = c.university_id
        WHERE ($1::text IS NULL OR c.program_name ILIKE '%' || $1 || '%')
          AND ($2::text IS NULL OR c.mode ILIKE '%' || $2 || '%')
          AND ($3::numeric IS NULL OR c.total_fee <= $3)
          AND ($4::text IS NULL OR c.naac_grade >= $4)
        ORDER BY {sort_expr} {order_dir} NULLS LAST
        LIMIT $5
        """,
        course_type,
        mode,
        max_fee,
        min_naac,
        max(1, min(limit, 20)),
    )
    return dict_rows(rows)


async def compare_entities(pool, entity_type: str, slugs: list[str], fields: list[str]) -> list[dict[str, Any]]:
    allowed = {
        "university": ("universities", {"slug", "name", "full_name", "starting_fee", "naac_grade", "ugc_approved", "mode_of_learning", "placement_content"}),
        "course": ("courses", {"slug", "program_name", "duration", "mode", "total_fee", "starting_fee", "naac_grade", "ugc_status", "placement_content", "eligibility_summary"}),
        "specialization": ("specializations", {"slug", "spec_name", "duration", "mode", "total_fee", "naac_grade", "ugc_status", "placement_content", "eligibility_summary"}),
    }
    table, allowed_fields = allowed[entity_type]
    selected = ["slug"] + [field for field in fields if field in allowed_fields and field != "slug"]
    rows = await pool.fetch(f"SELECT {', '.join(selected)} FROM {table} WHERE slug = ANY($1::text[])", slugs)
    return dict_rows(rows)


async def get_faq(pool, entity_type: str, entity_slug: str, query_text: str | None) -> list[dict[str, Any]]:
    table = {"university": "universities", "course": "courses", "specialization": "specializations"}[entity_type]
    entity_id = await pool.fetchval(f"SELECT id FROM {table} WHERE slug = $1", entity_slug)
    if not entity_id:
        return []
    rows = await pool.fetch(
        """
        SELECT question, answer
        FROM faqs
        WHERE entity_type = $1 AND entity_id = $2
          AND ($3::text IS NULL OR question ILIKE '%' || $3 || '%' OR answer ILIKE '%' || $3 || '%')
        LIMIT 5
        """,
        entity_type,
        entity_id,
        query_text,
    )
    return dict_rows(rows)


# ---------------------------------------------------------------------------
# Catalog discovery & comparison queries
# (backing get_university_overview_tool / get_university_programs_tool /
#  get_program_details_tool / get_specializations_tool / search_catalog_tool /
#  compare_programs_tool in agent/tools.py)
# ---------------------------------------------------------------------------

async def get_university_overview(pool, university_slug: str) -> dict[str, Any] | None:
    """Broad university profile for 'tell me about X' questions."""
    return dict_row(
        await pool.fetchrow(
            """
            SELECT slug, name, full_name, established_year, naac_grade, ugc_approved,
                   mode_of_learning, starting_fee, num_programs, about_content,
                   why_choose_content, placement_content, faculty_intro
            FROM universities
            WHERE slug = $1
            """,
            university_slug,
        )
    )


async def get_university_programs(pool, university_slug: str, limit: int = 20) -> list[dict[str, Any]]:
    """All courses offered by one specific, already-known university."""
    rows = await pool.fetch(
        """
        SELECT c.slug, c.program_name, c.duration, c.mode, c.total_fee, c.starting_fee, c.naac_grade
        FROM courses c
        JOIN universities u ON u.id = c.university_id
        WHERE u.slug = $1
        ORDER BY c.program_name
        LIMIT $2
        """,
        university_slug,
        max(1, min(limit, 20)),
    )
    return dict_rows(rows)


async def get_program_details(pool, course_slug: str, university_slug: str | None = None) -> dict[str, Any] | None:
    """Full detail record for one specific, already-known course.

    university_slug is optional — course slugs are already globally unique —
    but when provided it acts as an extra scoping/safety check, consistent
    with how get_fee/get_eligibility always scope by university.
    """
    return dict_row(
        await pool.fetchrow(
            """
            SELECT c.slug, c.program_name, c.duration, c.mode, c.total_fee, c.starting_fee,
                   c.naac_grade, c.ugc_status, c.num_specializations, c.about_content,
                   c.eligibility_summary, c.eligibility_content, c.admission_steps,
                   c.admission_fee_note, c.syllabus_content, c.placement_content,
                   c.certificate_description, c.validity, c.emi_amount,
                   u.slug AS university_slug, u.name AS university_name
            FROM courses c
            JOIN universities u ON u.id = c.university_id
            WHERE c.slug = $1
              AND ($2::text IS NULL OR u.slug = $2)
            """,
            course_slug,
            university_slug,
        )
    )


async def get_specializations(pool, course_slug: str, university_slug: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """All specializations available under one specific, already-known course."""
    rows = await pool.fetch(
        """
        SELECT s.slug, s.spec_name, s.duration, s.mode, s.total_fee, s.naac_grade, s.ugc_status
        FROM specializations s
        JOIN courses c ON c.id = s.course_id
        JOIN universities u ON u.id = s.university_id
        WHERE c.slug = $1
          AND ($2::text IS NULL OR u.slug = $2)
        ORDER BY s.spec_name
        LIMIT $3
        """,
        course_slug,
        university_slug,
        max(1, min(limit, 20)),
    )
    return dict_rows(rows)


async def search_catalog(pool, query_text: str, entity_type: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
    """Broad catalog search for questions that don't map to a specific entity.

    Matches against entity_search.search_text (ILIKE) and resolves each hit
    back to its display row across whichever of the three catalog tables it
    belongs to. This is a text-match implementation for now — entity_search
    already carries an `embedding` column, so a vector-similarity pass can be
    layered in later (e.g. ORDER BY embedding <=> $query_embedding) without
    changing this function's signature, once a query embedding is produced
    upstream by the agent/LLM layer.
    """
    rows = await pool.fetch(
        """
        SELECT es.entity_type,
               COALESCE(u.slug, c.slug, s.slug) AS slug,
               COALESCE(u.name, c.program_name, s.spec_name) AS name,
               COALESCE(u.starting_fee, c.total_fee, s.total_fee) AS fee_hint
        FROM entity_search es
        LEFT JOIN universities u ON es.entity_type = 'university' AND u.id = es.entity_id
        LEFT JOIN courses c ON es.entity_type = 'course' AND c.id = es.entity_id
        LEFT JOIN specializations s ON es.entity_type = 'specialization' AND s.id = es.entity_id
        WHERE es.search_text ILIKE '%' || $1 || '%'
          AND ($2::text IS NULL OR es.entity_type = $2)
        LIMIT $3
        """,
        query_text,
        entity_type,
        max(1, min(limit, 20)),
    )
    return dict_rows(rows)


async def compare_programs(pool, course_slugs: list[str], fields: list[str]) -> list[dict[str, Any]]:
    """Course-vs-course comparison with a fixed, comparison-friendly column
    whitelist (deliberately narrower than compare_entities' whitelist —
    fields like raw_json or long wysiwyg blobs are excluded on purpose).
    Falls back to a sensible default set if `fields` filters down to nothing.
    """
    allowed_fields = {
        "program_name", "total_fee", "starting_fee", "duration", "mode",
        "naac_grade", "ugc_status", "eligibility_summary",
    }
    default_fields = ["program_name", "total_fee", "duration", "naac_grade", "ugc_status", "eligibility_summary"]

    selected = [f for f in fields if f in allowed_fields and f != "slug"] or default_fields
    columns = ["c.slug"] + [f"c.{f}" for f in selected]

    rows = await pool.fetch(
        f"""
        SELECT {', '.join(columns)}, u.slug AS university_slug, u.name AS university_name
        FROM courses c
        JOIN universities u ON u.id = c.university_id
        WHERE c.slug = ANY($1::text[])
        """,
        course_slugs,
    )
    return dict_rows(rows)


async def insert_lead(pool, session_id: str, name: str, phone: str, email: str | None, course_interest: str | None, trigger_reason: str) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        INSERT INTO leads(session_id, name, phone, email, course_interest, trigger_reason)
        VALUES($1::uuid, $2, $3, $4, $5, $6)
        RETURNING id, session_id, name, phone, email, course_interest, trigger_reason, created_at
        """,
        session_id,
        name,
        phone,
        email,
        course_interest,
        trigger_reason,
    )
    return dict(row)


async def log_signal(pool, session_id: str, university_slug: str | None, course_slug: str | None, question_type: str) -> None:
    points = 2 if question_type in {"fee", "eligibility", "asked_fee_or_eligibility"} else 1
    await pool.execute("INSERT INTO lead_score_events(session_id, event_type, points) VALUES($1::uuid, $2, $3)", session_id, question_type, points)


async def log_unanswered(pool, session_id: str, question: str, university_slug: str | None, course_slug: str | None) -> None:
    await pool.execute(
        "INSERT INTO unanswered_questions(session_id, question, university_slug, course_slug) VALUES($1::uuid, $2, $3, $4)",
        session_id,
        question,
        university_slug,
        course_slug,
    )


async def total_lead_score(pool, session_id: str) -> int:
    return int(await pool.fetchval("SELECT COALESCE(sum(points), 0) FROM lead_score_events WHERE session_id = $1::uuid", session_id) or 0)


async def lead_ask_exists(pool, session_id: str) -> bool:
    return bool(await pool.fetchval("SELECT 1 FROM lead_asks WHERE session_id = $1::uuid", session_id))


async def mark_lead_ask(pool, session_id: str) -> None:
    await pool.execute("INSERT INTO lead_asks(session_id) VALUES($1::uuid) ON CONFLICT DO NOTHING", session_id)


async def list_conversations(pool, university: str | None, date_from: str | None, date_to: str | None, has_lead: bool | None, has_unanswered: bool | None, limit: int, offset: int) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT s.id, s.site_id, s.page_university_slug, s.summary, s.started_at, s.last_active_at, s.message_count,
               EXISTS(SELECT 1 FROM leads l WHERE l.session_id = s.id) AS has_lead,
               EXISTS(SELECT 1 FROM unanswered_questions uq WHERE uq.session_id = s.id) AS has_unanswered
        FROM sessions s
        WHERE ($1::text IS NULL OR s.page_university_slug = $1)
          AND ($2::timestamptz IS NULL OR s.started_at >= $2::timestamptz)
          AND ($3::timestamptz IS NULL OR s.started_at <= $3::timestamptz)
          AND ($4::boolean IS NULL OR EXISTS(SELECT 1 FROM leads l WHERE l.session_id = s.id) = $4)
          AND ($5::boolean IS NULL OR EXISTS(SELECT 1 FROM unanswered_questions uq WHERE uq.session_id = s.id) = $5)
        ORDER BY s.last_active_at DESC
        LIMIT $6 OFFSET $7
        """,
        university,
        date_from,
        date_to,
        has_lead,
        has_unanswered,
        limit,
        offset,
    )
    return dict_rows(rows)


async def get_conversation(pool, session_id: str) -> dict[str, Any]:
    session = dict_row(await pool.fetchrow("SELECT * FROM sessions WHERE id = $1::uuid", session_id)) or {}
    messages = dict_rows(await pool.fetch("SELECT role, content, tool_calls, created_at FROM messages WHERE session_id = $1::uuid ORDER BY id", session_id))
    leads = dict_rows(await pool.fetch("SELECT * FROM leads WHERE session_id = $1::uuid ORDER BY id", session_id))
    return {"session": session, "messages": messages, "leads": leads}


async def list_leads(pool, limit: int, offset: int) -> list[dict[str, Any]]:
    return dict_rows(await pool.fetch("SELECT * FROM leads ORDER BY created_at DESC LIMIT $1 OFFSET $2", limit, offset))


async def group_unanswered(pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT university_slug, course_slug, count(*) AS count, array_agg(question ORDER BY created_at DESC)[:10] AS examples
        FROM unanswered_questions
        GROUP BY university_slug, course_slug
        ORDER BY count(*) DESC
        """
    )
    return dict_rows(rows)


async def analytics(pool) -> dict[str, Any]:
    return {
        "conversation_count": int(await pool.fetchval("SELECT count(*) FROM sessions") or 0),
        "message_count": int(await pool.fetchval("SELECT count(*) FROM messages") or 0),
        "lead_count": int(await pool.fetchval("SELECT count(*) FROM leads") or 0),
        "unanswered_count": int(await pool.fetchval("SELECT count(*) FROM unanswered_questions") or 0),
        "top_universities": dict_rows(await pool.fetch("SELECT page_university_slug, count(*) FROM sessions GROUP BY page_university_slug ORDER BY count(*) DESC LIMIT 10")),
    }


async def insert_flagged_message(
    pool,
    session_id: str,
    message: str,
    layer: str = "unknown",
    risk_score: float = 0.0,
    reason: str = "unknown",
) -> None:
    await pool.execute(
        """
        INSERT INTO flagged_messages(session_id, message, layer, risk_score, reason)
        VALUES($1::uuid, $2, $3, $4, $5)
        """,
        session_id,
        message,
        layer,
        risk_score,
        reason,
    )


async def list_flagged_messages(pool, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT id, session_id, message, layer, risk_score, reason, created_at
        FROM flagged_messages
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return dict_rows(rows)


# ---------------------------------------------------------------------------
# Security dashboard helpers (Phase 7)
# ---------------------------------------------------------------------------

async def get_security_summary(pool) -> dict[str, Any]:
    """
    Returns aggregate security metrics for the admin dashboard.

    Fields:
      total_blocks         — all-time flagged_messages count
      blocks_by_layer      — breakdown by layer (prompt_guard, policy, output_scan)
      blocks_by_reason     — breakdown by reason
      last_24h_blocks      — blocks in the last 24 hours
    """
    total_blocks = int(
        await pool.fetchval("SELECT count(*) FROM flagged_messages") or 0
    )

    layer_rows = await pool.fetch(
        """
        SELECT layer, count(*) AS count
        FROM flagged_messages
        GROUP BY layer
        ORDER BY count DESC
        """
    )

    reason_rows = await pool.fetch(
        """
        SELECT reason, count(*) AS count
        FROM flagged_messages
        GROUP BY reason
        ORDER BY count DESC
        """
    )

    last_24h = int(
        await pool.fetchval(
            "SELECT count(*) FROM flagged_messages WHERE created_at >= now() - interval '24 hours'"
        ) or 0
    )

    return {
        "total_blocks": total_blocks,
        "blocks_by_layer": dict_rows(layer_rows),
        "blocks_by_reason": dict_rows(reason_rows),
        "last_24h_blocks": last_24h,
    }


async def get_top_attack_patterns(pool, limit: int = 20) -> list[dict[str, Any]]:
    """
    Returns the most commonly blocked message prefixes grouped by reason.
    Useful for identifying repeat attackers and evolving attack patterns.
    """
    rows = await pool.fetch(
        """
        SELECT reason, layer, message, count(*) AS occurrences, max(created_at) AS last_seen
        FROM flagged_messages
        GROUP BY reason, layer, message
        ORDER BY occurrences DESC, last_seen DESC
        LIMIT $1
        """,
        limit,
    )
    return dict_rows(rows)