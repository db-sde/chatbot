from __future__ import annotations

import json
import ipaddress
from typing import Any

from settings import settings


class SessionSiteMismatchError(Exception):
    """Raised when a session UUID is reused from a different configured site."""


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
    result = await pool.execute(
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
        WHERE sessions.site_id = EXCLUDED.site_id
        """,
        session_id,
        site_id,
        page_university_slug,
        ip_address,
        user_agent,
    )
    if result == "INSERT 0 0":
        raise SessionSiteMismatchError("Session belongs to a different site")


async def get_session_context(pool, session_id: str) -> dict[str, Any]:
    row = await pool.fetchrow(
        """
        SELECT current_university_slug, current_course_slug, current_specialization_slug,
               comparison_context
        FROM session_context
        WHERE session_id = $1::uuid
        """,
        session_id,
    )
    return dict_row(row) or {}


async def get_session_history(
    pool,
    session_id: str,
    limit: int | None = None,
    before_id: int | None = None,
    site_id: str | None = None,
) -> dict[str, Any]:
    """
    Return previous messages for a session in ascending chronological order.
    Used by the widget to restore prior conversation on page load.
    Only user/assistant roles are returned — tool call JSON is omitted
    from this public endpoint (available in the admin /api/admin/conversations/{id}).
    Cursor-based pagination: pass before_id to load messages older than that id.
    """
    if limit is None:
        limit = settings.max_conversation_messages
    limit = max(1, min(limit, 50))  # reject negative/zero SQL LIMIT behavior by clamping
    rows = await pool.fetch(
        """
        SELECT m.id, m.role, m.content, m.created_at
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.session_id = $1::uuid
          AND ($2::int IS NULL OR m.id < $2)
          AND ($4::text IS NULL OR s.site_id = $4)
        ORDER BY m.id DESC
        LIMIT $3
        """,
        session_id,
        before_id,
        limit,
        site_id,
    )
    messages = list(reversed(dict_rows(rows)))  # ascending order for rendering
    has_more = len(rows) == limit
    oldest_id = messages[0]["id"] if messages else None
    return {"session_id": session_id, "messages": messages, "has_more": has_more, "oldest_id": oldest_id}



async def update_session_context(
    pool,
    session_id: str,
    university_slug: str | None,
    course_slug: str | None,
    specialization_slug: str | None,
    *,
    replace_dependents: bool = False,
) -> None:
    """
    Persist conversational entity context for the session.

    Default (replace_dependents=False): COALESCE — only overwrite non-null fields
    (legacy behaviour for partial updates).

    When replace_dependents=True (university newly resolved): write the university
    slug and set course/spec to the provided values (None clears previous course/spec
    so a switch NMIMS → Sharda does not leave a stale NMIMS course).
    """
    if replace_dependents and university_slug:
        await pool.execute(
            """
            INSERT INTO session_context(session_id, current_university_slug, current_course_slug, current_specialization_slug)
            VALUES($1::uuid, $2, $3, $4)
            ON CONFLICT (session_id) DO UPDATE SET
                current_university_slug = $2,
                current_course_slug = $3,
                current_specialization_slug = $4,
                last_updated = now()
            """,
            session_id,
            university_slug,
            course_slug,
            specialization_slug,
        )
        return

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


async def update_comparison_context(
    pool, session_id: str, comparison_context: dict[str, Any]
) -> None:
    """Persist canonical comparison targets separately from single-entity context."""
    await pool.execute(
        """
        INSERT INTO session_context(session_id, comparison_context)
        VALUES($1::uuid, $2::jsonb)
        ON CONFLICT (session_id) DO UPDATE SET
            comparison_context = EXCLUDED.comparison_context,
            last_updated = now()
        """,
        session_id,
        json.dumps(comparison_context),
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


async def existing_entity_slugs(pool, entity_type: str, slugs: list[str]) -> set[str]:
    """Return the existing slugs for one trusted catalog entity type."""
    tables = {
        "university": "universities",
        "course": "courses",
        "specialization": "specializations",
    }
    table = tables[entity_type]
    rows = await pool.fetch(
        f"SELECT slug FROM {table} WHERE slug = ANY($1::text[])",
        slugs,
    )
    return {str(row["slug"]) for row in rows}


async def find_entities_trgm(pool, message: str, limit: int = 3) -> list[dict]:
    query = """
        SELECT entity_type, entity_id, search_text, word_similarity($1, search_text) as sim
        FROM entity_search
        WHERE $1 <% search_text
        ORDER BY sim DESC
        LIMIT $2
    """
    return await pool.fetch(query, message, limit)


_ENTITY_TABLES = {"university": "universities", "course": "courses", "specialization": "specializations"}


def _entity_table(entity_type: str) -> str:
    if entity_type not in _ENTITY_TABLES:
        raise ValueError(f"Invalid entity_type: {entity_type}")
    return _ENTITY_TABLES[entity_type]


async def slug_for_entity_id(pool, entity_type: str, entity_id: int) -> str | None:
    table = _entity_table(entity_type)
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
    sort_columns = {
        "fee": "c.total_fee",
        "duration": "c.duration",
        "name": "c.program_name",
    }
    sort_expr = sort_columns.get(sort_by, "c.program_name")
    if sort_expr not in sort_columns.values():
        sort_expr = "c.program_name"
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
    table = _entity_table(entity_type)
    allowed = {
        "university": {"slug", "name", "full_name", "starting_fee", "naac_grade", "ugc_approved", "mode_of_learning", "placement_content"},
        "course": {"slug", "program_name", "duration", "mode", "total_fee", "starting_fee", "naac_grade", "ugc_status", "placement_content", "eligibility_summary"},
        "specialization": {"slug", "spec_name", "duration", "mode", "total_fee", "naac_grade", "ugc_status", "placement_content", "eligibility_summary"},
    }
    allowed_fields = allowed[entity_type]
    selected = ["slug"] + [field for field in fields if field in allowed_fields and field != "slug"]
    rows = await pool.fetch(f"SELECT {', '.join(selected)} FROM {table} WHERE slug = ANY($1::text[])", slugs)
    return dict_rows(rows)


async def get_faq(pool, entity_type: str, entity_slug: str, query_text: str | None) -> list[dict[str, Any]]:
    table = _entity_table(entity_type)
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
        SELECT s.id, s.site_id, s.page_university_slug, s.summary, s.started_at, s.last_active_at,
               s.message_count, s.ip_address,
               s.lead_intent_detected, s.lead_intent_type, s.lead_intent_confidence,
               s.lead_intent_reasoning, s.lead_ask_triggered_by,
               bool_or(l.id IS NOT NULL) AS has_lead,
               bool_or(uq.id IS NOT NULL) AS has_unanswered,
               max(l.name) AS lead_name,
               max(l.phone) AS lead_phone,
               max(l.email) AS lead_email
        FROM sessions s
        LEFT JOIN leads l ON l.session_id = s.id
        LEFT JOIN unanswered_questions uq ON uq.session_id = s.id
        WHERE ($1::text IS NULL OR s.page_university_slug = $1)
          AND ($2::timestamptz IS NULL OR s.started_at >= $2::timestamptz)
          AND ($3::timestamptz IS NULL OR s.started_at <= $3::timestamptz)
        GROUP BY s.id
        HAVING ($4::boolean IS NULL OR bool_or(l.id IS NOT NULL) = $4)
           AND ($5::boolean IS NULL OR bool_or(uq.id IS NOT NULL) = $5)
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
        SELECT t.item->>'name' AS name,
               count(*) AS executions,
               coalesce(avg((t.item->>'duration_ms')::int), 0.0) AS avg_duration,
               coalesce(max((t.item->>'duration_ms')::int), 0) AS max_duration,
               sum(case when t.item->>'status' = 'FAILURE' then 1 else 0 end) AS failure_count,
               round(100.0 * sum(case when t.item->>'status' = 'SUCCESS' then 1 else 0 end) / nullif(count(*), 0), 2) AS success_rate
        FROM messages m,
             lateral jsonb_array_elements(m.tool_calls) AS t(item)
        WHERE m.role = 'assistant' AND m.tool_calls IS NOT NULL
        GROUP BY t.item->>'name'
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


async def save_lead_intent_status(
    pool,
    session_id: str,
    lead_intent_detected: bool,
    lead_intent_type: str | None,
    lead_intent_confidence: float | None,
    lead_intent_reasoning: str | None,
    lead_ask_triggered_by: str | None,
) -> None:
    """Save semantic lead intent classification logs to the session."""
    await pool.execute(
        """
        UPDATE sessions
        SET lead_intent_detected = $2,
            lead_intent_type = $3,
            lead_intent_confidence = $4,
            lead_intent_reasoning = $5,
            lead_ask_triggered_by = COALESCE(lead_ask_triggered_by, $6)
        WHERE id = $1::uuid
        """,
        session_id,
        lead_intent_detected,
        lead_intent_type,
        lead_intent_confidence,
        lead_intent_reasoning,
        lead_ask_triggered_by,
    )


async def get_lead_intent_analytics(pool) -> dict[str, Any]:
    """Calculate lead capture source breakdown percentages and semantic classification distributions."""
    # 1. Source breakdown
    source_rows = await pool.fetch(
        """
        SELECT coalesce(trigger_reason, 'Score Engine') AS source, count(*) AS count
        FROM leads
        GROUP BY trigger_reason
        """
    )
    total_leads = sum(r["count"] for r in source_rows)
    source_breakdown = []
    for r in source_rows:
        source_name = "LLM Intent" if r["source"] == "LLM Intent" else "Score Engine"
        pct = round(100.0 * r["count"] / total_leads, 2) if total_leads > 0 else 0.0
        source_breakdown.append({"source": source_name, "count": r["count"], "percentage": pct})
        
    # 2. Intent categories breakdown
    intent_rows = await pool.fetch(
        """
        SELECT lead_intent_type AS category, count(*) AS count
        FROM sessions
        WHERE lead_intent_detected = TRUE AND lead_intent_type IS NOT NULL
        GROUP BY lead_intent_type
        ORDER BY count DESC
        """
    )
    total_intents = sum(r["count"] for r in intent_rows)

    intent_categories = []
    for r in intent_rows:
        pct = round(100.0 * r["count"] / total_intents, 2) if total_intents > 0 else 0.0
        friendly_names = {
            "human_advisor_request": "Human Advisor Request",
            "admission_guidance": "Admission Guidance",
            "career_counselling": "Career Counselling",
            "scholarship_support": "Scholarship Support",
            "application_support": "Application Support",
            "none": "General Inquiry"
        }
        category_name = friendly_names.get(r["category"], r["category"].replace("_", " ").title())
        intent_categories.append({"category": category_name, "count": r["count"], "percentage": pct})
        
    return {
        "source_breakdown": source_breakdown,
        "intent_categories": intent_categories
    }


# ---------------------------------------------------------------------------
# Widget settings
# ---------------------------------------------------------------------------

_WIDGET_SETTINGS_BOOL_COLUMNS = [
    "show_on_mobile",
    "show_on_desktop",
    "lead_capture_enabled",
    "capture_name",
    "capture_email",
    "capture_phone",
]

_WIDGET_SETTINGS_TEXT_COLUMNS = [
    "primary_color",
    "widget_title",
    "bot_name",
    "welcome_message",
    "logo_url",
    "lead_trigger",
    "lead_form_title",
    "lead_form_description",
]


async def get_widget_settings(pool, site_id: str = "default") -> dict[str, Any]:
    """Return the global widget settings, creating defaults if missing."""
    row = await pool.fetchrow(
        """
        SELECT *
        FROM widget_settings
        WHERE site_id = 'default'
        """
    )
    if row:
        return dict_row(row) or {}
    # Insert defaults and return them.
    await pool.execute(
        """
        INSERT INTO widget_settings (site_id)
        VALUES ('default')
        ON CONFLICT (site_id) DO NOTHING
        """
    )
    row = await pool.fetchrow(
        """
        SELECT *
        FROM widget_settings
        WHERE site_id = 'default'
        """
    )
    return dict_row(row) or {}


async def upsert_widget_settings(
    pool,
    site_id: str,
    settings: dict[str, Any],
    updated_by: str | None = None,
) -> dict[str, Any]:
    """Update global widget settings. Ignores site_id and writes only configured columns."""
    columns = []
    values = []
    
    # Process boolean settings
    for col in _WIDGET_SETTINGS_BOOL_COLUMNS:
        if col in settings:
            columns.append(col)
            values.append(bool(settings[col]))
            
    # Process text/string settings
    for col in _WIDGET_SETTINGS_TEXT_COLUMNS:
        if col in settings:
            columns.append(col)
            val = settings[col]
            values.append(str(val) if val is not None else None)

    if columns:
        set_clause = ", ".join(f"{col} = ${i + 2}" for i, col in enumerate(columns))
        await pool.execute(
            f"""
            INSERT INTO widget_settings (site_id, {", ".join(columns)}, updated_at, updated_by)
            VALUES ($1, {", ".join(f"${i + 2}" for i in range(len(columns)))}, now(), ${len(columns) + 2})
            ON CONFLICT (site_id) DO UPDATE SET
                {set_clause},
                updated_at = now(),
                updated_by = EXCLUDED.updated_by
            """,
            site_id,
            *values,
            updated_by,
        )

    return await get_widget_settings(pool)


async def list_widget_settings(pool) -> list[dict[str, Any]]:
    """Return the global widget settings as a list with a single element for compatibility."""
    row = await get_widget_settings(pool)
    return [row]


# ---------------------------------------------------------------------------
# Security Events — new persistent event log
# ---------------------------------------------------------------------------

# Auto-ban thresholds (configurable constants)
_AUTO_BAN_TEMP_THRESHOLD = 3    # violations within 1 hour → 24h temp ban
_AUTO_BAN_PERM_THRESHOLD = 10   # total violations → permanent ban
_AUTO_BAN_WINDOW_HOURS   = 1    # rolling window for temp-ban counter


async def get_ip_country(ip: str) -> str:
    if not ip or ip in ("127.0.0.1", "::1", "localhost", "testclient"):
        return "Local Network"
    # Check common private IP subnets
    if ip.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")):
        return "Private IP"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("country") or "India"
    except Exception:
        pass
    return "India"


async def insert_security_event(
    pool,
    *,
    ip_address: str | None,
    user_agent: str | None,
    session_id: str | None,
    event_type: str,
    severity: str = "medium",
    payload: str | None = None,
    source: str | None = None,
    action_taken: str | None = None,
    blocked: bool = False,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Persist a security event and trigger auto-ban logic if thresholds are hit."""
    country = "Local Network"
    if ip_address:
        country = await get_ip_country(ip_address)

    row = await pool.fetchrow(
        """
        INSERT INTO security_events
            (ip_address, user_agent, session_id, event_type, severity,
             payload, source, action_taken, blocked, metadata_json, country)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING *
        """,
        ip_address,
        user_agent,
        session_id,
        event_type,
        severity,
        (payload[:2000] if payload else None),
        source,
        action_taken,
        blocked,
        json.dumps(metadata) if metadata else None,
        country,
    )
    result = dict_row(row) or {}

    # Auto-ban logic — only for IPs we can identify
    if ip_address and blocked:
        await _maybe_auto_ban(pool, ip_address)

    return result


async def _maybe_auto_ban(pool, ip_address: str) -> None:
    """Check violation counts and issue automatic bans when thresholds are exceeded."""
    # Total all-time blocked events for this IP
    total = int(
        await pool.fetchval(
            "SELECT count(*) FROM security_events WHERE ip_address = $1 AND blocked = TRUE",
            ip_address,
        ) or 0
    )

    # Recent violations within rolling window
    recent = int(
        await pool.fetchval(
            """
            SELECT count(*) FROM security_events
            WHERE ip_address = $1 AND blocked = TRUE
              AND created_at >= now() - interval '1 hour'
            """,
            ip_address,
        ) or 0
    )

    # Check if already actively blocked
    already_blocked = await pool.fetchval(
        """
        SELECT id FROM blocked_ips
        WHERE ip_address = $1 AND is_active = TRUE
          AND (expires_at IS NULL OR expires_at > now())
        """,
        ip_address,
    )
    if already_blocked:
        return

    if total >= _AUTO_BAN_PERM_THRESHOLD:
        await upsert_blocked_ip(
            pool,
            ip_address=ip_address,
            reason=f"Auto-banned: {total} total violations",
            blocked_by="system",
            block_type="permanent",
            expires_at=None,
        )
    elif recent >= _AUTO_BAN_TEMP_THRESHOLD:
        from datetime import datetime, timezone, timedelta
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        await upsert_blocked_ip(
            pool,
            ip_address=ip_address,
            reason=f"Auto-banned: {recent} violations in 1 hour",
            blocked_by="system",
            block_type="temporary",
            expires_at=expires,
        )


async def get_security_events(
    pool,
    limit: int = 100,
    offset: int = 0,
    event_type: str | None = None,
    severity: str | None = None,
    ip_address: str | None = None,
) -> list[dict[str, Any]]:
    """Paginated security event history with optional filters."""
    conditions = []
    params: list[Any] = []

    if event_type:
        params.append(event_type)
        conditions.append(f"event_type = ${len(params)}")
    if severity:
        params.append(severity)
        conditions.append(f"severity = ${len(params)}")
    if ip_address:
        params.append(ip_address)
        conditions.append(f"ip_address = ${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])

    rows = await pool.fetch(
        f"""
        SELECT * FROM security_events
        {where}
        ORDER BY created_at DESC
        LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    return dict_rows(rows)


async def get_security_events_summary(pool) -> dict[str, Any]:
    """Extended security summary based entirely on the security_events and blocked_ips tables."""
    total_events = int(await pool.fetchval("SELECT count(*) FROM security_events") or 0)
    last_24h_events = int(await pool.fetchval(
        "SELECT count(*) FROM security_events WHERE created_at >= now() - interval '24 hours'"
    ) or 0)

    prompt_guard_detections = int(await pool.fetchval(
        "SELECT count(*) FROM security_events WHERE event_type = 'prompt_injection'"
    ) or 0)
    policy_violations = int(await pool.fetchval(
        "SELECT count(*) FROM security_events WHERE event_type = 'policy_violation'"
    ) or 0)

    by_type = await pool.fetch(
        "SELECT event_type, count(*) AS count FROM security_events GROUP BY event_type ORDER BY count DESC"
    )
    by_severity = await pool.fetch(
        "SELECT severity, count(*) AS count FROM security_events GROUP BY severity ORDER BY count DESC"
    )

    # Active bans count only records from blocked_ips table
    total_blocked_ips = int(await pool.fetchval(
        "SELECT count(*) FROM blocked_ips WHERE is_active = TRUE AND (expires_at IS NULL OR expires_at > now())"
    ) or 0)
    temp_bans = int(await pool.fetchval(
        "SELECT count(*) FROM blocked_ips WHERE is_active = TRUE AND block_type = 'temporary' AND (expires_at IS NULL OR expires_at > now())"
    ) or 0)
    perm_bans = int(await pool.fetchval(
        "SELECT count(*) FROM blocked_ips WHERE is_active = TRUE AND block_type = 'permanent'"
    ) or 0)

    return {
        # Keep old keys for safety, but point them to the correct metrics if needed
        "total_blocks": total_events,
        "last_24h_blocks": last_24h_events,
        "prompt_guard_blocks": prompt_guard_detections,
        "policy_blocks": policy_violations,
        "output_scan_blocks": 0,
        
        # New keys
        "total_events": total_events,
        "last_24h_events": last_24h_events,
        "prompt_guard_detections": prompt_guard_detections,
        "policy_violations": policy_violations,
        "events_by_type": dict_rows(by_type),
        "events_by_severity": dict_rows(by_severity),
        "total_blocked_ips": total_blocked_ips,
        "temp_bans": temp_bans,
        "perm_bans": perm_bans,
    }


async def get_top_attacking_ips(pool, limit: int = 20) -> list[dict[str, Any]]:
    """IPs with the most security events, including their block status."""
    rows = await pool.fetch(
        """
        SELECT
            se.ip_address,
            count(*) AS attack_count,
            count(*) FILTER (WHERE se.blocked = TRUE) AS blocked_count,
            max(se.created_at) AS last_seen,
            bool_or(bi.is_active AND (bi.expires_at IS NULL OR bi.expires_at > now())) AS is_blocked,
            max(bi.block_type) AS block_type
        FROM security_events se
        LEFT JOIN blocked_ips bi ON bi.ip_address = se.ip_address
        WHERE se.ip_address IS NOT NULL
        GROUP BY se.ip_address
        ORDER BY attack_count DESC
        LIMIT $1
        """,
        limit,
    )
    return dict_rows(rows)


# ---------------------------------------------------------------------------
# Blocked IPs
# ---------------------------------------------------------------------------

async def is_ip_blocked(pool, ip_address: str) -> bool:
    """Return True if the IP has an active block (temporary or permanent)."""
    if not ip_address:
        return False
    row = await pool.fetchrow(
        """
        SELECT id FROM blocked_ips
        WHERE ip_address = $1
          AND is_active = TRUE
          AND (expires_at IS NULL OR expires_at > now())
        """,
        ip_address,
    )
    return row is not None


async def upsert_blocked_ip(
    pool,
    *,
    ip_address: str,
    reason: str | None,
    blocked_by: str = "admin",
    block_type: str = "temporary",
    expires_at=None,
) -> dict[str, Any]:
    """Insert or update a blocked IP entry."""
    row = await pool.fetchrow(
        """
        INSERT INTO blocked_ips (ip_address, reason, blocked_by, block_type, expires_at, is_active)
        VALUES ($1, $2, $3, $4, $5, TRUE)
        ON CONFLICT (ip_address) DO UPDATE SET
            reason     = EXCLUDED.reason,
            blocked_by = EXCLUDED.blocked_by,
            block_type = EXCLUDED.block_type,
            expires_at = EXCLUDED.expires_at,
            is_active  = TRUE,
            created_at = now()
        RETURNING *
        """,
        ip_address,
        reason,
        blocked_by,
        block_type,
        expires_at,
    )
    return dict_row(row) or {}


async def unblock_ip(pool, ip_address: str) -> bool:
    """Deactivate a blocked IP. Returns True if an active block was found and cleared."""
    result = await pool.execute(
        """
        UPDATE blocked_ips
        SET is_active = FALSE
        WHERE ip_address = $1 AND is_active = TRUE
        """,
        ip_address,
    )
    return result != "UPDATE 0"


async def list_blocked_ips(pool, include_inactive: bool = False) -> list[dict[str, Any]]:
    """List all blocked IPs optionally including expired/inactive ones."""
    where = "" if include_inactive else "WHERE is_active = TRUE AND (expires_at IS NULL OR expires_at > now())"
    rows = await pool.fetch(
        f"SELECT * FROM blocked_ips {where} ORDER BY created_at DESC"
    )
    return dict_rows(rows)


async def get_security_timeline(pool, hours: int = 24) -> list[dict[str, Any]]:
    """Event counts per hour over the last N hours for chart display."""
    rows = await pool.fetch(
        """
        SELECT
            date_trunc('hour', created_at) AS hour,
            count(*) AS total,
            count(*) FILTER (WHERE blocked = TRUE) AS blocked_count
        FROM security_events
        WHERE created_at >= now() - ($1 || ' hours')::interval
        GROUP BY 1
        ORDER BY 1
        """,
        str(hours),
    )
    return dict_rows(rows)
