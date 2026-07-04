from __future__ import annotations

import json
import ipaddress
from typing import Any


def _clean_row(d: dict[str, Any]) -> dict[str, Any]:
    for k, v in d.items():
        if isinstance(v, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            d[k] = str(v)
    return d


def dict_row(row: Any) -> dict[str, Any] | None:
    return _clean_row(dict(row)) if row else None


def dict_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [_clean_row(dict(row)) for row in rows]


async def ensure_session(
    pool,
    session_id: str,
    site_id: str,
    page_university_slug: str | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO sessions(id, site_id, page_university_slug, ip_address, user_agent)
        VALUES($1::uuid, $2, $3, $4::inet, $5)
        ON CONFLICT (id) DO UPDATE SET
            last_active_at = now(),
            page_university_slug = COALESCE(EXCLUDED.page_university_slug, sessions.page_university_slug),
            -- Only write ip/ua on first insert; do not overwrite with later values
            -- so the stored metadata reflects where the session was originally opened.
            ip_address = COALESCE(sessions.ip_address, EXCLUDED.ip_address),
            user_agent = COALESCE(sessions.user_agent, EXCLUDED.user_agent)
        """,
        session_id,
        site_id,
        page_university_slug,
        ip_address,
        user_agent,
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


async def get_session_history(
    pool,
    session_id: str,
    limit: int = 20,
    before_id: int | None = None,
) -> dict[str, Any]:
    """
    Return previous messages for a session in ascending chronological order.
    Used by the widget to restore prior conversation on page load.
    Only user/assistant roles are returned — tool call JSON is omitted
    from this public endpoint (available in the admin /api/admin/conversations/{id}).
    Cursor-based pagination: pass before_id to load messages older than that id.
    """
    limit = min(limit, 50)  # cap at 50 regardless of caller
    rows = await pool.fetch(
        """
        SELECT id, role, content, created_at
        FROM messages
        WHERE session_id = $1::uuid
          AND ($2::int IS NULL OR id < $2)
        ORDER BY id DESC
        LIMIT $3
        """,
        session_id,
        before_id,
        limit,
    )
    messages = list(reversed(dict_rows(rows)))  # ascending order for rendering
    has_more = len(rows) == limit
    oldest_id = messages[0]["id"] if messages else None
    return {"session_id": session_id, "messages": messages, "has_more": has_more, "oldest_id": oldest_id}



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


async def insert_message(
    pool,
    session_id: str,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
    response_time_ms: int | None = None,
    ttft_ms: int | None = None,
    model_name: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
    tool_execution_time_ms: int | None = None,
    started_at: Any | None = None,
    completed_at: Any | None = None,
) -> int | None:
    row = await pool.fetchrow(
        """
        INSERT INTO messages(
            session_id, role, content, tool_calls,
            response_time_ms, ttft_ms, model_name,
            input_tokens, output_tokens, total_tokens,
            estimated_cost_usd, tool_execution_time_ms,
            started_at, completed_at
        )
        VALUES(
            $1::uuid, $2, $3, $4::jsonb,
            $5, $6, $7,
            $8, $9, $10,
            $11, $12,
            $13, $14
        )
        RETURNING id
        """,
        session_id,
        role,
        content,
        json.dumps(tool_calls) if tool_calls is not None else None,
        response_time_ms,
        ttft_ms,
        model_name,
        input_tokens,
        output_tokens,
        total_tokens,
        estimated_cost_usd,
        tool_execution_time_ms,
        started_at,
        completed_at,
    )
    await pool.execute("UPDATE sessions SET message_count = message_count + 1, last_active_at = now() WHERE id = $1::uuid", session_id)
    return row["id"] if row else None


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
    """Broad university profile for 'tell me about X' questions.

    num_programs is computed from the actual courses table rather than the
    static seeded universities.num_programs text column, which is populated
    verbatim from Micro App JSON at ingestion time and can drift out of sync
    with what's actually in the database (e.g. a course removed later still
    left the old count in place). The stale column is left in the schema
    (still used by ingestion) but is no longer what this read path returns.
    """
    return dict_row(
        await pool.fetchrow(
            """
            SELECT u.slug, u.name, u.full_name, u.established_year, u.naac_grade, u.ugc_approved,
                   u.mode_of_learning, u.starting_fee,
                   (SELECT count(*) FROM courses c WHERE c.university_id = u.id) AS num_programs,
                   u.about_content, u.why_choose_content, u.placement_content, u.faculty_intro
            FROM universities u
            WHERE u.slug = $1
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
    # num_specializations is computed from the actual specializations table —
    # see get_university_overview's docstring above for why the seeded text
    # column isn't trustworthy for a read path shown to users.
    return dict_row(
        await pool.fetchrow(
            """
            SELECT c.slug, c.program_name, c.duration, c.mode, c.total_fee, c.starting_fee,
                   c.naac_grade, c.ugc_status,
                   (SELECT count(*) FROM specializations s WHERE s.course_id = c.id) AS num_specializations,
                   c.about_content, c.eligibility_summary, c.eligibility_content, c.admission_steps,
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
        SELECT s.id, s.site_id, s.page_university_slug, s.summary, s.started_at, s.last_active_at, s.message_count, s.ip_address,
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
    messages = dict_rows(
        await pool.fetch(
            """
            SELECT id, role, content, tool_calls, created_at,
                   response_time_ms, ttft_ms, model_name,
                   input_tokens, output_tokens, total_tokens,
                   estimated_cost_usd
            FROM messages
            WHERE session_id = $1::uuid
            ORDER BY id
            """,
            session_id,
        )
    )
    for msg in messages:
        if isinstance(msg.get("tool_calls"), str):
            try:
                msg["tool_calls"] = json.loads(msg["tool_calls"])
            except Exception:
                msg["tool_calls"] = []
    leads = dict_rows(await pool.fetch("SELECT * FROM leads WHERE session_id = $1::uuid ORDER BY id", session_id))
    return {"session": session, "messages": messages, "leads": leads}


async def list_leads(pool, limit: int, offset: int) -> list[dict[str, Any]]:
    return dict_rows(await pool.fetch("SELECT * FROM leads ORDER BY created_at DESC LIMIT $1 OFFSET $2", limit, offset))


async def group_unanswered(pool) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT university_slug, course_slug, count(*) AS count, (array_agg(question ORDER BY created_at DESC))[1:10] AS examples
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


# ---------------------------------------------------------------------------
# Next-Generation AI Observability & Cost Analytics Queries
# ---------------------------------------------------------------------------

async def get_analytics_overview(pool) -> dict[str, Any]:
    """Retrieve high-level overview metrics for the AI Advisor performance dashboard."""
    avg_response = await pool.fetchval("SELECT coalesce(avg(response_time_ms), 0.0) FROM messages WHERE role = 'assistant'")
    avg_ttft = await pool.fetchval("SELECT coalesce(avg(ttft_ms), 0.0) FROM messages WHERE role = 'assistant'")
    total_tokens_today = await pool.fetchval("SELECT coalesce(sum(total_tokens), 0) FROM messages WHERE role = 'assistant' AND created_at >= date_trunc('day', now())")
    total_cost_today = await pool.fetchval("SELECT coalesce(sum(estimated_cost_usd), 0.0) FROM messages WHERE role = 'assistant' AND created_at >= date_trunc('day', now())")
    
    total_leads = await pool.fetchval("SELECT count(*) FROM leads")
    total_cost = await pool.fetchval("SELECT coalesce(sum(estimated_cost_usd), 0.0) FROM messages WHERE role = 'assistant'")
    cost_per_lead = (float(total_cost) / total_leads) if total_leads > 0 else 0.0
    
    return {
        "avg_response_time_ms": float(avg_response or 0.0),
        "avg_ttft_ms": float(avg_ttft or 0.0),
        "total_tokens_today": int(total_tokens_today or 0),
        "total_cost_today": float(total_cost_today or 0.0),
        "total_leads": int(total_leads or 0),
        "cost_per_lead": float(cost_per_lead),
    }


async def get_analytics_models(pool) -> list[dict[str, Any]]:
    """Return token count, cost, and latency averages grouped by LLM model."""
    rows = await pool.fetch(
        """
        SELECT model_name,
               count(*) AS messages,
               coalesce(sum(input_tokens), 0) AS input_tokens,
               coalesce(sum(output_tokens), 0) AS output_tokens,
               coalesce(sum(total_tokens), 0) AS total_tokens,
               coalesce(sum(estimated_cost_usd), 0.0) AS total_cost,
               coalesce(avg(response_time_ms), 0.0) AS avg_response_time,
               coalesce(avg(ttft_ms), 0.0) AS avg_ttft
        FROM messages
        WHERE role = 'assistant' AND model_name IS NOT NULL
        GROUP BY model_name
        ORDER BY total_cost DESC
        """
    )
    return dict_rows(rows)


async def get_analytics_tools(pool) -> list[dict[str, Any]]:
    """Flatten and aggregate tool call duration and success statistics from JSONB records."""
    rows = await pool.fetch(
        """
        SELECT t.name,
               count(*) AS executions,
               coalesce(avg((t.item->>'duration_ms')::int), 0.0) AS avg_duration,
               coalesce(max((t.item->>'duration_ms')::int), 0) AS max_duration,
               sum(case when t.item->>'status' = 'FAILURE' then 1 else 0 end) AS failure_count,
               round(100.0 * sum(case when t.item->>'status' = 'SUCCESS' then 1 else 0 end) / nullif(count(*), 0), 2) AS success_rate
        FROM messages m,
             lateral jsonb_array_elements(m.tool_calls) AS t(item)
        WHERE m.role = 'assistant' AND m.tool_calls IS NOT NULL
        GROUP BY t.name
        ORDER BY executions DESC
        """
    )
    return dict_rows(rows)


async def get_analytics_universities(pool) -> list[dict[str, Any]]:
    """Group analytics and costs by university page-hint context."""
    rows = await pool.fetch(
        """
        SELECT coalesce(s.page_university_slug, 'general') AS university,
               count(distinct s.id) AS chats,
               count(distinct m.id) AS messages,
               count(distinct l.id) AS leads,
               round(100.0 * count(distinct l.id) / nullif(count(distinct s.id), 0), 2) AS conversion_rate,
               coalesce(sum(m.total_tokens), 0) AS total_tokens,
               coalesce(sum(m.estimated_cost_usd), 0.0) AS total_cost,
               coalesce(avg(m.response_time_ms), 0.0) AS avg_response_time
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id
        LEFT JOIN leads l ON l.session_id = s.id
        GROUP BY s.page_university_slug
        ORDER BY chats DESC
        """
    )
    return dict_rows(rows)


async def get_analytics_costs(pool) -> dict[str, Any]:
    """Retrieve detailed platform running costs (daily, weekly, monthly) and list most expensive chats."""
    cost_today = await pool.fetchval("SELECT coalesce(sum(estimated_cost_usd), 0.0) FROM messages WHERE role = 'assistant' AND created_at >= date_trunc('day', now())")
    cost_week = await pool.fetchval("SELECT coalesce(sum(estimated_cost_usd), 0.0) FROM messages WHERE role = 'assistant' AND created_at >= now() - interval '7 days'")
    cost_month = await pool.fetchval("SELECT coalesce(sum(estimated_cost_usd), 0.0) FROM messages WHERE role = 'assistant' AND created_at >= now() - interval '30 days'")
    total_cost = await pool.fetchval("SELECT coalesce(sum(estimated_cost_usd), 0.0) FROM messages WHERE role = 'assistant'")
    
    expensive_chats_rows = await pool.fetch(
        """
        SELECT s.id AS session_id,
               count(m.id) AS message_count,
               coalesce(sum(m.total_tokens), 0) AS total_tokens,
               coalesce(sum(m.estimated_cost_usd), 0.0) AS total_cost,
               s.started_at
        FROM sessions s
        JOIN messages m ON m.session_id = s.id
        GROUP BY s.id, s.started_at
        ORDER BY total_cost DESC
        LIMIT 10
        """
    )
    
    return {
        "cost_today": float(cost_today or 0.0),
        "cost_week": float(cost_week or 0.0),
        "cost_month": float(cost_month or 0.0),
        "total_cost": float(total_cost or 0.0),
        "expensive_conversations": dict_rows(expensive_chats_rows)
    }


async def get_analytics_funnel(pool) -> dict[str, Any]:
    """Return qualified funnel metrics stage counts and overall conversions."""
    row = await pool.fetchrow(
        """
        WITH stats AS (
            SELECT count(distinct s.id) AS total_sessions,
                   count(distinct case when s.message_count > 0 then s.id end) AS conversations,
                   count(distinct case when s.message_count >= 3 then s.id end) AS qualified_conversations,
                   count(distinct l.id) AS leads,
                   coalesce(sum(m.estimated_cost_usd), 0.0) AS total_cost
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            LEFT JOIN leads l ON l.session_id = s.id
        )
        SELECT total_sessions AS visitors,
               conversations,
               qualified_conversations,
               leads,
               total_cost,
               round(total_cost / nullif(leads, 0), 4) AS cost_per_lead,
               round(total_cost / nullif(conversations, 0), 4) AS cost_per_conversation
        FROM stats
        """
    )
    return dict(row) if row else {
        "visitors": 0, "conversations": 0, "qualified_conversations": 0,
        "leads": 0, "total_cost": 0.0, "cost_per_lead": 0.0, "cost_per_conversation": 0.0
    }