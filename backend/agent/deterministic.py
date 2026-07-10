from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessage

from agent.constants import quick_replies_for
from agent.v2_routes import (
    DETERMINISTIC_ROUTES,
    ROUTE_ACCREDITATION,
    ROUTE_ELIGIBILITY,
    ROUTE_FEE,
    ROUTE_PROGRAMS,
    ROUTE_RATINGS,
    ROUTE_REVIEWS,
    ROUTE_SPECIALIZATIONS,
    detect_route,
)
from db import queries


def _money(value: Any) -> str:
    if value is None:
        return "Not listed"
    try:
        amount = f"{float(value):.0f}"
        sign = "-" if amount.startswith("-") else ""
        digits = amount.removeprefix("-")
        if len(digits) > 3:
            tail = digits[-3:]
            head = digits[:-3]
            groups: list[str] = []
            while head:
                groups.append(head[-2:])
                head = head[:-2]
            digits = ",".join(reversed(groups)) + "," + tail
        return f"{sign}₹{digits}"
    except (TypeError, ValueError, ArithmeticError):
        return str(value)


def _text(value: Any, fallback: str = "Not listed") -> str:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    return text if text else fallback


def _actions_card(message: str, title: str = "What would you like to check next?") -> dict[str, Any]:
    return {
        "type": "actions",
        "eyebrow": "Continue your journey",
        "title": title,
        "actions": [
            {"label": label, "message": label}
            for label in quick_replies_for(message, limit=3)
        ],
    }


def _result(
    *,
    route: str,
    reply: str,
    started: float,
    cards: list[dict[str, Any]] | None = None,
    progressive_lead_field: str | None = None,
) -> dict[str, Any]:
    duration_ms = (time.perf_counter() - started) * 1000
    result: dict[str, Any] = {
        "messages": [AIMessage(content=reply)],
        "reply": reply,
        "deterministic_route": route,
        "deterministic_metric": {
            "name": f"deterministic_{route}_lookup",
            "duration_ms": duration_ms,
            "status": "SUCCESS",
        },
        "tool_ms_total": duration_ms,
        "ui_cards": cards or [_actions_card(route)],
    }
    if progressive_lead_field:
        result["progressive_lead_field"] = progressive_lead_field
    return result


async def run_deterministic_route(
    state: dict[str, Any],
    pool_provider: Callable[[], Awaitable[Any]],
) -> dict[str, Any] | None:
    message = state.get("raw_message", "")
    route = detect_route(message)
    if route not in DETERMINISTIC_ROUTES:
        return None

    resolved = state.get("resolved") or {}
    if resolved.get("resolution_status") in {"entity_not_found", "partial_match"}:
        return None

    university_slug = resolved.get("university_slug")
    course_slug = resolved.get("course_slug")
    specialization_slug = resolved.get("specialization_slug")
    raw_intent = resolved.get("raw") or {}
    mode = resolved.get("mode")
    started = time.perf_counter()

    if route == ROUTE_FEE:
        pool = await pool_provider()
        if university_slug:
            row = await queries.get_fee(pool, university_slug, course_slug, specialization_slug)
            if not row:
                reply = "Fees:\n- **Status:** Verified fee information is not listed for this selection yet."
            else:
                name = row.get("name") or row.get("program_name") or row.get("university_name") or university_slug
                points = [
                    f"- **Selection:** {_text(name)}",
                    f"- **Total fee:** {_money(row.get('total_fee'))}",
                    f"- **Starting fee:** {_money(row.get('starting_fee'))}",
                    f"- **EMI:** {_text(row.get('emi_amount') or row.get('emi_content'), 'Not listed in the catalog')}",
                ]
                requested_course = raw_intent.get("course_query")
                if (
                    requested_course
                    and str(name).casefold() not in message.casefold()
                ):
                    points.insert(
                        1,
                        f"- **Catalog note:** This is the verified match for your {_text(requested_course).upper()} request.",
                    )
                reply = "Fees:\n" + "\n".join(points)
            return _result(
                route=route,
                reply=reply,
                started=started,
                progressive_lead_field="name",
            )

        rows = await queries.list_courses(
            pool,
            raw_intent.get("course_query"),
            mode,
            resolved.get("max_fee"),
            None,
            "fee",
            "asc",
            5,
        )
        reply = "Fee options across the catalog:\n" + "\n".join(
            f"- **{row.get('program_name')}:** {_money(row.get('total_fee'))} at {row.get('university_name')}"
            for row in rows
        ) if rows else "Fees:\n- **Status:** No matching catalog fee options were found."
        return _result(
            route=route,
            reply=reply,
            started=started,
            progressive_lead_field="name",
        )

    if route == ROUTE_ELIGIBILITY:
        if university_slug and course_slug:
            pool = await pool_provider()
            row = await queries.get_eligibility(pool, university_slug, course_slug)
            if row:
                reply = "Eligibility:\n" + "\n".join([
                    f"- **Program:** {_text(row.get('program_name'))}",
                    f"- **University:** {_text(row.get('university_name'))}",
                    f"- **Criteria:** {_text(row.get('eligibility_summary') or row.get('eligibility_content'))}",
                ])
            else:
                reply = "Eligibility:\n- **Status:** Verified eligibility is not listed for this program yet."
            return _result(route=route, reply=reply, started=started)

        cards = [_actions_card(message, "Choose a program first, then I can check its eligibility.")]
        if university_slug:
            pool = await pool_provider()
            programs = await queries.get_university_programs(pool, university_slug, limit=5)
            if programs:
                cards.insert(0, {
                    "type": "choices",
                    "eyebrow": "Choose a program",
                    "title": "Which program's eligibility should I check?",
                    "actions": [
                        {"label": row.get("program_name"), "message": f"Eligibility for {row.get('program_name')}"}
                        for row in programs
                    ],
                })
        return _result(
            route=route,
            reply="Eligibility:\n- **Next step:** Select a specific program so I can use its verified criteria.",
            started=started,
            cards=cards,
        )

    if route == ROUTE_PROGRAMS:
        pool = await pool_provider()
        if university_slug:
            rows = await queries.get_university_programs(pool, university_slug, limit=5)
            heading = "Available programs"
        else:
            rows = await queries.list_courses(
                pool,
                raw_intent.get("course_query"),
                mode,
                resolved.get("max_fee"),
                None,
                "fee" if resolved.get("sort_by") == "fee" else None,
                resolved.get("order") or "asc",
                5,
            )
            heading = "Programs across the catalog"
        reply = heading + ":\n" + "\n".join(
            f"- **{row.get('program_name')}:** {row.get('university_name') or university_slug or ''} · {_text(row.get('duration'))} · {_money(row.get('total_fee'))}"
            for row in rows
        ) if rows else heading + ":\n- **Status:** No matching programs were found."
        return _result(route=route, reply=reply, started=started)

    if route == ROUTE_SPECIALIZATIONS:
        if course_slug:
            pool = await pool_provider()
            rows = await queries.get_specializations(pool, course_slug, university_slug, limit=5)
            reply = "Specializations:\n" + "\n".join(
                f"- **{row.get('spec_name')}:** {_text(row.get('duration'))} · {_money(row.get('total_fee'))}"
                for row in rows
            ) if rows else "Specializations:\n- **Status:** No verified specializations are listed for this program."
            return _result(route=route, reply=reply, started=started)
        return _result(
            route=route,
            reply="Specializations:\n- **Next step:** Choose a program before checking its available specializations.",
            started=started,
        )

    if route == ROUTE_ACCREDITATION:
        if not university_slug:
            return _result(
                route=route,
                reply="Accreditations:\n- **Next step:** Name a university so I can check its verified UGC and NAAC information.",
                started=started,
            )
        pool = await pool_provider()
        row = await queries.get_university_overview(pool, university_slug)
        reply = "Accreditations:\n" + "\n".join([
            f"- **University:** {_text((row or {}).get('name'), university_slug)}",
            f"- **NAAC grade:** {_text((row or {}).get('naac_grade'))}",
            f"- **UGC status:** {_text((row or {}).get('ugc_approved'))}",
            f"- **Learning mode:** {_text((row or {}).get('mode_of_learning'))}",
        ])
        return _result(route=route, reply=reply, started=started)

    entity_type = "course" if course_slug else "university"
    entity_slug = course_slug or university_slug
    if route in {ROUTE_REVIEWS, ROUTE_RATINGS}:
        if not entity_slug:
            return _result(
                route=route,
                reply="Ratings & reviews:\n- **Next step:** Name a university or program so I can check its verified feedback.",
                started=started,
            )
        pool = await pool_provider()
        rows = await queries.get_reviews(pool, entity_type, entity_slug, limit=5)
        points = [
            f"- **{_text(row.get('reviewer_name'), 'Student')}:** {_text(row.get('review_text'))}"
            for row in rows
            if row.get("review_text")
        ]
        if route == ROUTE_RATINGS:
            points.insert(0, "- **Numeric rating:** DegreeBaba does not currently store a verified aggregate rating for this selection.")
        if not points:
            points = ["- **Status:** No verified student reviews are listed yet."]
        return _result(
            route=route,
            reply="Ratings & reviews:\n" + "\n".join(points),
            started=started,
        )

    return None
