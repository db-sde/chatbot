from __future__ import annotations

"""
Optimized LangGraph agent loop for the DegreeBaba chatbot.

Key Optimizations:
1. Native Tool Calling: Merged Agent Decide + Synthesis into a single ReAct loop.
   The LLM now extracts entities, calls tools, and formats the final response natively.
2. Background Lead Scoring: Moved out of the critical path to reduce latency.
3. Real Token Streaming: Replaced fake word-by-word streaming with real LLM token streaming.
4. Triage Node: Added a fast-path router for chitchat and semantic caching.
5. Lightweight Entity Resolution: Kept resolve_entities but isolated it for a fast/cheap model.
6. Resolved-Entity Tool-Argument Merge: Tool calls are corrected against
   resolve_entities()'s canonical university/course/specialization slugs
   immediately before execution, so an LLM guess (e.g. "nmims"/"mba") can
   never override a slug the resolver already found (e.g.
   "nmims-online"/"executive-mba-nmims-online").
7. Timing visibility: resolver_ms / llm_ms_total / tool_ms_total are tracked
   through state and logged as a TIMING SUMMARY per turn, to localize
   latency without changing any behavior.
"""

import asyncio
from settings import settings
import json
import logging
import time
from typing import Annotated, Any, AsyncIterator, Awaitable, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from security.output_scan import scan_output
from agent.constants import quick_replies_for
from agent.llm_client import SYSTEM_PROMPT, llm_client
from agent.resolve import is_greeting, resolve_entities as _resolve_entities
from agent.tools import TOOLS, list_courses as list_courses_catalog, log_anonymous_signal, log_unanswered
from db import queries
from db.pool import get_pool
from observability import (
    tool_metrics_var,
    request_metadata_var,
    init_observability_context,
    mark_llm_start,
    mark_first_token,
    record_llm_call_duration,
)


logger = logging.getLogger(__name__)

# asyncio keeps only weak references to scheduled tasks. Retain active
# analytics tasks until completion so they cannot disappear mid-execution.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_SESSION_LOCKS: dict[str, dict[str, Any]] = {}

from leads.scoring import (
    classify_score_events,
    log_score_events,
    should_append_lead_ask,
    detect_fast_lead_intent,
    is_contact_intent,
)
from leads.intent import lead_intent_classifier, LEAD_INTENT_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class ChatState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    site_id: str
    raw_message: str
    page_university_slug: str | None
    # Human-readable page context resolved from URL pathname
    page_context: dict[str, Any]
    context: dict[str, Any]
    resolved: dict[str, Any]
    reply: str
    tool_calls_log: list[dict[str, Any]]
    lead_ask: bool
    lead_ask_triggered_by: str
    # Actual tool invocations across the entire user turn. This is separate
    # from tool_call_count, which retains its existing meaning of ReAct rounds.
    tool_calls_executed: int
    tool_call_limit_reached: bool
    # True only when the immediately preceding tool batch returned complete,
    # successful results that can be synthesized without another lookup.
    tool_batch_completed: bool
    tool_call_count: int
    # New fields for optimization
    triage_intent: str
    cache_hit: bool
    # Timing instrumentation (visibility only, see run_chat_turn TIMING SUMMARY).
    # llm_ms_total / tool_ms_total accumulate across every ReAct loop iteration.
    resolver_ms: float
    llm_ms_total: float
    tool_ms_total: float
    profile_context_update: dict[str, Any]
    progressive_lead_field: str


def _make_state(
    *,
    session_id: str,
    site_id: str,
    message: str,
    page_university_slug: str | None,
    context: dict[str, Any],
    page_context: dict[str, Any] | None = None,
    history_messages: list[BaseMessage] | None = None,
) -> dict[str, Any]:
    history_messages = history_messages or []
    return {
        "messages": [SystemMessage(content=SYSTEM_PROMPT), *history_messages, HumanMessage(content=message)],
        "session_id": session_id,
        "site_id": site_id,
        "raw_message": message,
        "page_university_slug": page_university_slug,
        "page_context": page_context or {},
        "context": context,
        "resolved": {},
        "reply": "",
        "tool_calls_log": [],
        "lead_ask": False,
        "tool_calls_executed": 0,
        "tool_call_limit_reached": False,
        "tool_batch_completed": False,
        "tool_call_count": 0,
        "triage_intent": "factual",
        "cache_hit": False,
        "resolver_ms": 0.0,
        "llm_ms_total": 0.0,
        "tool_ms_total": 0.0,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

CONTACT_REPLY = (
    "I'd be happy to connect you with an admission counsellor. "
    "Please share your contact details."
)


def _is_program_overview_request(message: str) -> bool:
    text = message.lower()
    return any(
        phrase in text
        for phrase in ("tell me about", "details about", "overview of", "information about")
    ) and not any(
        term in text
        for term in ("fee", "cost", "eligib", "specialization", "review", "rating", "accredit")
    )


async def node_triage(state: ChatState) -> dict[str, Any]:
    """
    FAST PATH: Greeting / contact intent / future semantic cache.
    Uses zero-cost checks — no LLM, no DB, no network.
    """
    from agent.resolve import is_greeting
    message = state["raw_message"]
    session_id = state.get("session_id")

    if is_greeting(message):
        logger.info("[%s] TRIAGE -> chitchat (greeting detected: %r)", session_id, message[:60])
        return {"triage_intent": "chitchat", "cache_hit": False, "lead_ask": False}

    if is_contact_intent(message):
        logger.info("[%s] CONTACT INTENT DETECTED | triage msg=%r", session_id, message[:80])
        return {"triage_intent": "contact", "cache_hit": False, "lead_ask": True}

    # Future: semantic cache lookup here before hitting the full pipeline.
    return {"triage_intent": "factual", "cache_hit": False}


def route_after_triage(state: ChatState) -> str:
    if state.get("cache_hit"):
        return END
    if state.get("triage_intent") == "chitchat":
        return "chitchat_reply"
    if state.get("triage_intent") == "contact":
        return "contact_reply"
    return "resolve_entities"


async def node_chitchat_reply(state: ChatState) -> dict[str, Any]:
    """Handles greetings/simple chitchat without hitting the DB or the agent."""
    reply = "Hello! I'm the DegreeBaba assistant. How can I help you with universities, courses, fees, or admissions today?"
    return {"reply": reply, "messages": [AIMessage(content=reply)]}


async def node_contact_reply(state: ChatState) -> dict[str, Any]:
    """Contact/lead intent: skip entity resolve + agent; open lead form."""
    logger.info(
        "[%s] CONTACT INTENT DETECTED | LEAD ASK TRIGGERED | msg=%r",
        state.get("session_id"),
        state.get("raw_message", "")[:80],
    )
    return {
        "reply": CONTACT_REPLY,
        "messages": [AIMessage(content=CONTACT_REPLY)],
        "lead_ask": True,
        "lead_ask_triggered_by": "Contact Intent",
        "resolved": {
            "resolution_status": "contact",
            "intent_type": "contact",
            "university_slug": None,
            "course_slug": None,
            "specialization_slug": None,
            "_page_hint_only": True,
        },
    }


async def node_resolve_entities(state: ChatState) -> dict[str, Any]:
    """
    Entity resolution: catalog-first university detection → course/spec snap → context.
    Contact intent is handled in triage before this node runs.
    """
    message = state["raw_message"]
    context = state.get("context", {})
    session_id = state["session_id"]
    page_university_slug = state.get("page_university_slug")

    # Defense in depth: contact messages must never enter entity extraction
    if is_contact_intent(message):
        logger.info("[%s] CONTACT INTENT DETECTED | resolve bypass", session_id)
        return {
            "lead_ask": True,
            "lead_ask_triggered_by": "Contact Intent",
            "resolved": {
                "resolution_status": "contact",
                "intent_type": "contact",
                "university_slug": None,
                "course_slug": None,
                "specialization_slug": None,
                "_page_hint_only": True,
            },
        }

    logger.info("[%s] RESOLVE ENTITIES | msg=%r", session_id, message[:100])
    t0 = time.perf_counter()
    resolved = await _resolve_entities(message, context, page_university_slug)
    resolver_ms = (time.perf_counter() - t0) * 1000
    logger.info("[%s] TIMING | resolver_ms=%.1f", session_id, resolver_ms)

    # If resolve itself detected contact (safety)
    if resolved.get("resolution_status") == "contact" or resolved.get("intent_type") == "contact":
        logger.info("[%s] CONTACT INTENT DETECTED | from resolve layer", session_id)
        return {
            "lead_ask": True,
            "lead_ask_triggered_by": "Contact Intent",
            "resolved": {**resolved, "_page_hint_only": True},
            "resolver_ms": resolver_ms,
        }

    resolution_status = resolved.get("resolution_status", "none")
    logger.info(
        "[%s] RESOLVE RESULT | uni=%s course=%s spec=%s mode=%s max_fee=%s status=%s",
        session_id,
        resolved.get("university_slug"), resolved.get("course_slug"),
        resolved.get("specialization_slug"), resolved.get("mode"), resolved.get("max_fee"),
        resolution_status,
    )

    # Persist newly catalog-resolved entities. replace_dependents clears stale course/spec
    # when the user switches university (NMIMS → Sharda).
    pool = await get_pool()
    if resolution_status == "resolved" and resolved.get("university_slug"):
        context_update = queries.update_session_context(
            pool,
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            resolved.get("specialization_slug"),
            replace_dependents=True,
        )
        if resolved.get("course_slug") and _is_program_overview_request(message):
            _, prefetched_program = await asyncio.gather(
                context_update,
                queries.get_program_details(
                    pool,
                    resolved["course_slug"],
                    resolved["university_slug"],
                ),
            )
            resolved["_program_details"] = prefetched_program
        else:
            await context_update
        logger.info(
            "[%s] SESSION CONTEXT UPDATED | uni=%s course=%s spec=%s",
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            resolved.get("specialization_slug"),
        )
        if len(resolved.get("comparison_targets") or []) > 1:
            await queries.update_comparison_context(
                pool,
                session_id,
                {
                    "university_slugs": resolved["comparison_targets"],
                    "course_slug": resolved.get("course_slug"),
                    "specialization_slug": resolved.get("specialization_slug"),
                },
            )
            logger.info("[%s] COMPARISON CONTEXT UPDATED | targets=%s", session_id, resolved["comparison_targets"])
    elif resolution_status == "resolved":
        # Comparison-only edge: no single primary uni — still safe no-op
        pass

    intent_text = message.lower()
    if any(t in intent_text for t in ("fee", "fees", "cost", "price", "emi")):
        _schedule_anonymous_signal(
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            "fee",
        )
    elif any(t in intent_text for t in ("eligible", "eligibility", "criteria")):
        _schedule_anonymous_signal(
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            "eligibility",
        )

    # _page_hint_only=True suppresses the "resolved context" system note in node_agent.
    #
    # FIX: "session_context" and "page_context" used to be in this suppression
    # list. That meant whenever the resolver correctly carried forward a
    # university/course from a prior turn or the current page (e.g. the user
    # just says "MBA" after previously discussing NMIMS), node_agent never
    # told the LLM what had been resolved — the LLM had to reconstruct it from
    # raw chat history alone, which is exactly how "nmims-online" /
    # "executive-mba-nmims-online" became the LLM's own "nmims" / "mba"
    # guesses. Only genuinely-empty or handled-elsewhere statuses (which
    # already get their own dedicated advisory note further down in
    # node_agent, or have nothing to show) should suppress this note.
    page_hint_only = resolution_status in (
        "entity_not_found", "partial_match", "none", "contact",
    )
    resolved["_page_hint_only"] = page_hint_only
    result: dict[str, Any] = {"resolved": resolved, "resolver_ms": resolver_ms}
    if resolved.get("profile_context_update") is not None:
        result["profile_context_update"] = resolved["profile_context_update"]
    return result


def _clean_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    cleaned = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            content = msg.content
            if not isinstance(content, str):
                try:
                    content = json.dumps(content)
                except Exception:
                    content = str(content)
            cleaned.append(
                ToolMessage(
                    content=content,
                    name=getattr(msg, "name", None),
                    tool_call_id=msg.tool_call_id,
                    status=getattr(msg, "status", "success"),
                    artifact=getattr(msg, "artifact", None),
                )
            )
        else:
            cleaned.append(msg)
    return cleaned


async def node_agent(state: ChatState) -> dict[str, Any]:
    """
    The main ReAct Agent. Handles both tool calling AND final response synthesis.
    This replaces the old agent_decide + synthesize_reply nodes.
    """
    resolved = state.get("resolved", {})
    resolution_status = resolved.get("resolution_status", "none")

    raw_message = state.get("raw_message", "")
    overview_request = _is_program_overview_request(raw_message)
    if (
        resolution_status == "resolved"
        and resolved.get("course_slug")
        and resolved.get("university_slug")
        and overview_request
    ):
        program = resolved.get("_program_details")
        lookup_ms = 0.0
        if program is None:
            pool = await get_pool()
            started = time.perf_counter()
            program = await queries.get_program_details(
                pool,
                resolved["course_slug"],
                resolved["university_slug"],
            )
            lookup_ms = (time.perf_counter() - started) * 1000
        if program:
            requested_course = (resolved.get("raw") or {}).get("course_query")
            program_name = program.get("program_name") or program.get("slug")
            university_name = program.get("university_name") or resolved["university_slug"]
            if requested_course and requested_course.casefold() != program_name.casefold():
                intro = (
                    f"The matching {university_name} catalog record for "
                    f"**{requested_course.upper()}** is **{program_name}**:"
                )
            else:
                intro = f"The matching catalog program is **{program_name}** at **{university_name}**:"

            total_fee = program.get("total_fee")
            fee_text = f"₹{float(total_fee):,.0f}" if total_fee is not None else "Not listed"
            bullets = [
                f"- **Program:** {program_name}",
                f"- **Duration:** {program.get('duration') or 'Not listed'}",
                f"- **Mode:** {program.get('mode') or 'Not listed'}",
                f"- **Total fee:** {fee_text}",
            ]
            if program.get("eligibility_summary"):
                bullets.append(f"- **Eligibility:** {program['eligibility_summary']}")
            reply = (
                intro + "\n" + "\n".join(bullets[:5])
                + "\n\nWould you like to check eligibility next?"
            )
            return {
                "messages": [AIMessage(content=reply)],
                "reply": reply,
                "tool_ms_total": state.get("tool_ms_total", 0.0) + lookup_ms,
            }

    if resolution_status == "subjective_recommendation":
        qualification = dict(resolved.get("qualification") or {})
        profile_context = dict(resolved.get("profile_context_update") or {})
        awaiting = qualification.get("awaiting")
        if awaiting == "budget":
            reply = (
                "To narrow this down using the catalog, what is your maximum total "
                "program budget (for example, ₹2 lakh)?"
            )
        elif awaiting == "mode":
            reply = "Which study mode do you prefer: online or distance?"
        elif awaiting == "specialization":
            reply = (
                "Which specialization interests you most (for example, finance, marketing, "
                "or analytics)? You can also say ‘no preference’."
            )
        else:
            matches = await list_courses_catalog(
                course_type=qualification.get("course_type"),
                mode=qualification.get("mode"),
                max_fee=qualification.get("max_fee"),
                sort_by="fee",
                order="asc",
                limit=3,
                specialization_query=qualification.get("specialization"),
            )
            if not isinstance(matches, list) or not matches:
                reply = (
                    "I couldn't find a verified catalog match for all of those preferences. "
                    "I can broaden the budget or specialization, or optionally connect you "
                    "with a counsellor."
                )
                return {
                    "messages": [AIMessage(content=reply)],
                    "reply": reply,
                    "lead_ask": True,
                    "lead_ask_triggered_by": "No Answer Available",
                    "profile_context_update": profile_context,
                }

            bullets = []
            for row in matches:
                fee = row.get("total_fee")
                fee_text = f"₹{float(fee):,.0f}" if fee is not None else "fee not listed"
                bullets.append(
                    f"- **{row.get('program_name') or row.get('slug')}:** "
                    f"{row.get('university_name') or row.get('university_slug')} · {fee_text} · "
                    f"{row.get('mode') or qualification.get('mode')}"
                )
            offer_email = not state.get("context", {}).get("has_lead") and not (
                (profile_context.get("lead") or {}).get("email")
            )
            reply = (
                "I've found verified programs matching the filters you shared:\n"
                + "\n".join(bullets)
                + (
                    "\n\nWould you like to optionally share your email so you can keep these options?"
                    if offer_email else ""
                )
            )
            qualification["status"] = "complete"
            profile_context["qualification"] = qualification
            result = {
                "messages": [AIMessage(content=reply)],
                "reply": reply,
                "profile_context_update": profile_context,
            }
            if offer_email:
                result["progressive_lead_field"] = "email"
            return result

        return {
            "messages": [AIMessage(content=reply)],
            "reply": reply,
            "profile_context_update": profile_context,
        }

    # Unknown/partial catalog entities are a deterministic gap, not a prompt
    # for open-ended synthesis. Never give the model room to invent specifics.
    if resolution_status == "entity_not_found":
        requested = resolved.get("requested_entity") or "that university"
        reply = (
            f"I don't currently have verified information for {requested} in DegreeBaba's catalog. "
            "I can still help with available universities, fees, eligibility, accreditations, "
            "specializations, or connect you with a counsellor."
        )
        return {
            "messages": [AIMessage(content=reply)],
            "reply": reply,
            "lead_ask": True,
            "lead_ask_triggered_by": "No Answer Available",
        }
    if resolution_status == "partial_match":
        found = ", ".join(resolved.get("comparison_found") or []) or "none"
        missing = ", ".join(resolved.get("comparison_missing") or []) or "one requested university"
        reply = (
            f"I found {found}, but I couldn't verify {missing} in DegreeBaba's catalog, "
            "so I can't make a reliable comparison yet. Please clarify the name, or optionally "
            "ask me to connect you with a counsellor."
        )
        return {
            "messages": [AIMessage(content=reply)],
            "reply": reply,
            "lead_ask": True,
            "lead_ask_triggered_by": "No Answer Available",
        }

    if state.get("tool_call_limit_reached") and not state.get("tool_batch_completed"):
        reply = (
            "I couldn't complete a verified lookup within this turn's tool limit. "
            "I can try a narrower fee, eligibility, accreditation, review, or program question, "
            "or optionally connect you with a counsellor."
        )
        return {
            "messages": [AIMessage(content=reply)],
            "reply": reply,
            "lead_ask": True,
            "lead_ask_triggered_by": "No Answer Available",
        }

    if not llm_client.enabled:
        return {"messages": [AIMessage(content="I can help with DegreeBaba course fees, eligibility, and admissions.")]}

    messages = list(state["messages"])
    page_ctx = state.get("page_context", {})

    # ── Page context note (from URL pathname, human-readable names) ────────
    page_notes = []
    if page_ctx.get("page_university_name"):
        page_notes.append(f"page_university={page_ctx['page_university_name']} (slug={page_ctx['page_university_slug']})")
    if page_ctx.get("page_course_name"):
        page_notes.append(f"page_course={page_ctx['page_course_name']} (slug={page_ctx['page_course_slug']})")
    if page_ctx.get("page_spec_name"):
        page_notes.append(f"page_specialization={page_ctx['page_spec_name']} (slug={page_ctx['page_spec_slug']})")
    if page_notes:
        page_note = (
            f"[The user is currently viewing: {', '.join(page_notes)}. "
            "Use these slugs when calling tools if the message refers to 'this university', "
            "'this course', or 'this page'.]"
        )
        # Inject BEFORE the last HumanMessage only — never between AIMessage(tool_calls)
        # and ToolMessage, which violates OpenAI's tool-calling protocol.
        last_human_idx = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
            None,
        )
        if last_human_idx is not None:
            messages = messages[:last_human_idx] + [SystemMessage(content=page_note)] + messages[last_human_idx:]

    # ── Resolved entity slugs note (from fuzzy entity resolution) ─────────
    page_hint_only = resolved.get("_page_hint_only", False)
    context_parts = []
    if not page_hint_only:
        comp_targets = resolved.get("comparison_targets", [])
        if len(comp_targets) > 1:
            context_parts.append(f"comparison_targets={comp_targets}")
        elif resolved.get("university_slug"):
            context_parts.append(f"university_slug={resolved['university_slug']}")
            
        if resolved.get("course_slug"): context_parts.append(f"course_slug={resolved['course_slug']}")
        if resolved.get("specialization_slug"): context_parts.append(f"specialization_slug={resolved['specialization_slug']}")

    if context_parts:
        context_note = (
            f"[Resolved context for this turn: {', '.join(context_parts)}. "
            "Use these exact slugs when calling tools.]"
        )
        # Same rule: inject before the last HumanMessage to never break the
        # AIMessage(tool_calls) → ToolMessage sequence required by OpenAI.
        last_human_idx = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
            None,
        )
        if last_human_idx is not None:
            messages = messages[:last_human_idx] + [SystemMessage(content=context_note)] + messages[last_human_idx:]

    # ── Contact intent advisory (defense if agent path is reached) ────────────
    if resolution_status == "contact" or resolved.get("intent_type") == "contact":
        contact_note = (
            "[The user wants to speak with a counsellor / get in touch. "
            "Do NOT call catalog tools. Respond briefly that you'll connect them "
            "with an admission counsellor and ask them to share contact details.]"
        )
        last_human_idx = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
            None,
        )
        if last_human_idx is not None:
            messages = messages[:last_human_idx] + [SystemMessage(content=contact_note)] + messages[last_human_idx:]

    # ── Entity-not-found advisory note ────────────────────────────────────────
    if resolution_status == "entity_not_found":
        requested = resolved.get("requested_entity") or "the university you mentioned"
        not_found_note = (
            f"[The user asked about '{requested}' but this entity was NOT found in "
            "DegreeBaba's catalog. Do NOT call any tools. Inform the user politely that "
            f"'{requested}' is not currently available in the catalog and ask them to "
            "clarify or try a different university name.]"
        )
        last_human_idx = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
            None,
        )
        if last_human_idx is not None:
            messages = messages[:last_human_idx] + [SystemMessage(content=not_found_note)] + messages[last_human_idx:]

    # ── Partial-match advisory note ───────────────────────────────────────────
    if resolution_status == "partial_match":
        found = resolved.get("comparison_found") or []
        missing = resolved.get("comparison_missing") or []
        found_str = ", ".join(found) if found else "None"
        missing_str = ", ".join(missing) if missing else "None"
        partial_note = (
            f"[The user wants to compare multiple universities. "
            f"We found: {found_str}. We could NOT find: {missing_str}. "
            "Do NOT call any comparison tools. Inform the user politely about which "
            "universities were found and which were not, and ask them to clarify or "
            "try different university names.]"
        )
        last_human_idx = next(
            (i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)),
            None,
        )
        if last_human_idx is not None:
            messages = messages[:last_human_idx] + [SystemMessage(content=partial_note)] + messages[last_human_idx:]

    mark_llm_start()
    t_start = time.perf_counter()
    result: dict[str, Any]
    try:
        # A completed tool batch already supplies the facts for synthesis, so
        # avoid sending the full tool catalog again. Failed, not-found, or
        # incomplete results retain tool access for the existing ReAct path.
        model = llm_client.chat_model
        if not (
            state.get("tool_call_limit_reached")
            or state.get("tool_batch_completed")
        ):
            model = model.bind_tools(TOOLS)

        # Invoke as a Runnable so LangGraph's astream_events can intercept the stream
        response = await model.ainvoke(_clean_messages(messages))

        # Extract and record token usage for observability/pricing.
        # Prefer usage_metadata (populated for both streaming and batch by LangChain)
        # over response_metadata['token_usage'] (batch-only, uses raw OpenAI field names).
        try:
            from observability import record_llm_call
            from llm import config

            input_tok = 0
            output_tok = 0
            total_tok = 0

            # Path 1: usage_metadata — normalized by LangChain; works for streaming + batch
            usage_meta = getattr(response, "usage_metadata", None)
            if usage_meta:
                input_tok = usage_meta.get("input_tokens") or 0
                output_tok = usage_meta.get("output_tokens") or 0
                total_tok = usage_meta.get("total_tokens") or (input_tok + output_tok)

            # Path 2: response_metadata['token_usage'] — batch mode fallback (raw OpenAI names)
            if input_tok == 0:
                meta = getattr(response, "response_metadata", {}) or {}
                usage = meta.get("token_usage") or {}
                input_tok = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                output_tok = usage.get("completion_tokens") or usage.get("output_tokens") or 0
                total_tok = usage.get("total_tokens") or (input_tok + output_tok)

            record_llm_call({
                "model_name": config.MAIN_AGENT_MODEL,
                "token_usage": {
                    "input_tokens": input_tok,
                    "output_tokens": output_tok,
                    "total_tokens": total_tok,
                },
            })
        except Exception as o_exc:
            logger.warning("Failed to record agent token usage: %s", o_exc)

        result = {"messages": [response]}

    except Exception as exc:  # noqa: BLE001
        logger.warning("agent failed: %s", exc)
        result = {"messages": [AIMessage(content="I encountered an issue processing your request. Please try again.")]}
    finally:
        duration_ms = (time.perf_counter() - t_start) * 1000
        record_llm_call_duration(int(duration_ms))
        llm_ms_total = state.get("llm_ms_total", 0.0) + duration_ms
        logger.info(
            "[%s] TIMING | llm_call_ms=%.1f llm_ms_total=%.1f",
            state.get("session_id"), duration_ms, llm_ms_total,
        )

    result["llm_ms_total"] = llm_ms_total
    return result


# ---------------------------------------------------------------------------
# Resolved-entity → tool-argument merge (Rules 1-3)
# ---------------------------------------------------------------------------

_RESOLVED_ENTITY_ARG_KEYS = ("university_slug", "course_slug", "specialization_slug")


def _merge_resolved_into_tool_args(llm_args: dict[str, Any], resolved: dict[str, Any]) -> dict[str, Any]:
    """
    Canonical-truth merge for tool call arguments.

      Rule 1/2 - resolved course/university slugs ALWAYS override whatever
                 the LLM guessed for the same argument, whenever the LLM's
                 tool call actually includes that argument.
      Rule 3   - an argument the resolver did not resolve (None/missing) is
                 left exactly as the LLM produced it.

    Deliberately conservative in two ways:
      - Only touches university_slug / course_slug / specialization_slug.
        comparison_targets and any other tool argument (max_fee, mode,
        sort_by, ...) are left to the LLM untouched — per Rule 4, preserve
        existing behavior for comparison_targets / comparison queries.
      - Never ADDS a key the LLM's tool call didn't already include. A
        comparison-style tool that only takes e.g. `comparison_targets`
        (no `university_slug` param at all) must not have an unexpected
        kwarg forced onto it.
    """
    merged = dict(llm_args)
    # Comparison tools take lists of entity-specific slugs.  Their arguments
    # are never replaced with the primary entity selected for normal lookups.
    comparison_targets = resolved.get("comparison_targets") or []
    if len(comparison_targets) > 1:
        if "slugs" in merged:
            merged["slugs"] = list(comparison_targets)
        # A course list is already entity-specific. Do not overwrite it with
        # the one primary course resolver result unless we have one course per
        # target (which this resolver deliberately does not infer).
        if "course_slugs" in merged:
            return merged
    for key in _RESOLVED_ENTITY_ARG_KEYS:
        if key not in merged:
            continue
        resolved_value = resolved.get(key)
        if resolved_value:
            merged[key] = resolved_value
    return merged


async def node_execute_tools(state: ChatState) -> dict[str, Any]:
    session_id = state.get("session_id", "?")
    resolved = state.get("resolved", {}) or {}
    last_msg = state["messages"][-1]

    # ── Merge resolver's canonical slugs into the LLM's tool-call args ─────
    # Root fix for "resolver found nmims-online / executive-mba-..., but the
    # tool executed with nmims / mba": the LLM's own tool-call arguments were
    # never checked against resolve_entities()'s output before execution. We
    # rebuild the last AIMessage with the SAME id (so LangGraph's add_messages
    # reducer replaces it in place rather than duplicating it in history) but
    # corrected args, then execute tools against that corrected message.
    corrected_state = state
    tool_calls_executed = state.get("tool_calls_executed", 0)
    remaining_tool_calls = max(MAX_TOOL_CALLS_PER_TURN - tool_calls_executed, 0)
    tool_call_limit_reached = state.get("tool_call_limit_reached", False)
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        requested_tool_calls = list(last_msg.tool_calls)
        if len(requested_tool_calls) > remaining_tool_calls:
            logger.warning(
                "[%s] TOOL CALL LIMIT | requested=%d remaining=%d cap=%d; forcing synthesis after allowed calls",
                session_id,
                len(requested_tool_calls),
                remaining_tool_calls,
                MAX_TOOL_CALLS_PER_TURN,
            )
            requested_tool_calls = requested_tool_calls[:remaining_tool_calls]
            tool_call_limit_reached = True

        merged_tool_calls = []
        for tc in requested_tool_calls:
            original_args = tc.get("args", {}) or {}
            new_args = _merge_resolved_into_tool_args(original_args, resolved)
            if new_args != original_args:
                logger.info(
                    "[%s] TOOL ARGS CORRECTED | %s | llm=%s -> final=%s",
                    session_id, tc.get("name"), original_args, new_args,
                )
            merged_tool_calls.append({**tc, "args": new_args})

        last_msg = AIMessage(
            content=last_msg.content,
            tool_calls=merged_tool_calls,
            id=last_msg.id,
            name=getattr(last_msg, "name", None),
            additional_kwargs=getattr(last_msg, "additional_kwargs", {}) or {},
            response_metadata=getattr(last_msg, "response_metadata", {}) or {},
            usage_metadata=getattr(last_msg, "usage_metadata", None),
        )
        corrected_state = {**state, "messages": [*state["messages"][:-1], last_msg]}

    # Log which tools are being called (post-correction, so this reflects
    # what will actually be sent to the tool)
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        for tc in last_msg.tool_calls:
            logger.info("[%s] TOOL CALL | %s args=%s", session_id, tc["name"], tc["args"])

    tool_node = ToolNode(TOOLS)
    t0 = time.perf_counter()
    result = await tool_node.ainvoke(corrected_state)
    tool_ms = (time.perf_counter() - t0) * 1000
    tool_ms_total = state.get("tool_ms_total", 0.0) + tool_ms
    logger.info("[%s] TIMING | tool_exec_ms=%.1f tool_ms_total=%.1f", session_id, tool_ms, tool_ms_total)

    # Log tool results
    tool_messages = [
        msg for msg in result.get("messages", []) if isinstance(msg, ToolMessage)
    ]
    for msg in tool_messages:
        if isinstance(msg, ToolMessage):
            content_preview = str(msg.content)[:200]
            logger.info("[%s] TOOL RESULT | %s -> %s", session_id, getattr(msg, "name", "?"), content_preview)

    tool_batch_completed = _tool_batch_completed(last_msg, tool_messages)

    executed_this_round = len(last_msg.tool_calls) if isinstance(last_msg, AIMessage) else 0
    tool_calls_executed += executed_this_round
    if tool_calls_executed >= MAX_TOOL_CALLS_PER_TURN:
        tool_call_limit_reached = True
    count = state.get("tool_call_count", 0) + 1

    # Re-emit the corrected AIMessage alongside the new ToolMessages. It shares
    # the original message's id, so add_messages replaces the wrong-args copy
    # already in history instead of appending a duplicate — this keeps
    # _build_tool_calls_log (and anything else reading message history)
    # consistent with what actually executed.
    out_messages = result.get("messages", [])
    if corrected_state is not state:
        out_messages = [last_msg, *out_messages]

    return {
        **result,
        "messages": out_messages,
        "tool_call_count": count,
        "tool_calls_executed": tool_calls_executed,
        "tool_call_limit_reached": tool_call_limit_reached,
        "tool_batch_completed": tool_batch_completed,
        "tool_ms_total": tool_ms_total,
    }


MAX_TOOL_ITERATIONS = 4
MAX_TOOL_CALLS_PER_TURN = 8


def _tool_batch_completed(last_msg: BaseMessage, tool_messages: list[ToolMessage]) -> bool:
    """Whether all requested tools returned facts suitable for final synthesis.

    Tool failures use the uniform ``{"not_found": true}`` envelope. Unknown
    payloads are treated conservatively so the model retains its existing
    ability to request another lookup.
    """
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return False
    if len(tool_messages) != len(last_msg.tool_calls):
        return False

    for message in tool_messages:
        if getattr(message, "status", "success") != "success":
            return False
        content = message.content
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                return False
        if isinstance(content, dict) and (
            content.get("not_found")
            or content.get("incomplete")
            or content.get("requires_follow_up")
            or content.get("follow_up_required")
            or content.get("next_action") == "follow_up_lookup"
        ):
            return False
    return True

def route_after_agent(state: ChatState) -> str:
    """Decides whether to execute tools or exit based on iteration cap and tool calls."""
    if state.get("tool_call_count", 0) >= MAX_TOOL_ITERATIONS:
        logger.warning("Agent reached maximum tool call iterations (%d). Bypassing to END.", MAX_TOOL_ITERATIONS)
        return END
    
    # tools_condition returns "tools" if there are tool calls, else "__end__"
    next_step = tools_condition(state)
    
    # Map LangGraph's internal "tools" string to our custom node name "execute_tools"
    return "execute_tools" if next_step == "tools" else END


# ---------------------------------------------------------------------------
# Background Tasks
# ---------------------------------------------------------------------------

def _observe_background_task(task: asyncio.Task[Any]) -> None:
    """Ensure an unexpected analytics-task failure is logged and observed."""
    _BACKGROUND_TASKS.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Background analytics task cancelled")
    except Exception:
        logger.exception("Background analytics task failed")


def _create_background_task(awaitable: Awaitable[Any], *, name: str) -> asyncio.Task[Any]:
    task = asyncio.create_task(awaitable, name=name)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_observe_background_task)
    return task


async def _persist_fast_path(
    *,
    session_id: str,
    site_id: str,
    message: str,
    reply: str,
    page_university_slug: str | None,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """Persist a deterministic reply in order without delaying first paint."""
    pool = await get_pool()
    await queries.ensure_session(
        pool, session_id, site_id, page_university_slug, ip_address, user_agent
    )
    await queries.insert_message(pool, session_id, "user", message)
    await queries.insert_message(pool, session_id, "assistant", reply)


def _plan_progressive_lead_field(
    context: dict[str, Any],
    profile_context: dict[str, Any],
    *,
    forced_field: str | None = None,
) -> tuple[str | None, dict[str, Any], int]:
    """Advance the optional one-field lead cadence for a successful factual turn."""
    profile = dict(profile_context)
    lead_profile = dict(profile.get("lead") or {})
    asked_fields = list(profile.get("lead_asked_fields") or [])
    counter = int(context.get("factual_turns_since_profile_ask") or 0)

    if context.get("has_lead"):
        return None, profile, counter

    if forced_field and not lead_profile.get(forced_field):
        if forced_field not in asked_fields:
            asked_fields.append(forced_field)
        profile["lead_asked_fields"] = asked_fields
        return forced_field, profile, 0

    counter += 1
    if counter < 2:
        return None, profile, counter

    next_field = next(
        (
            field for field in ("name", "phone", "email")
            if not lead_profile.get(field) and field not in asked_fields
        ),
        None,
    )
    if next_field is None:
        missing_fields = [
            field for field in ("name", "phone", "email")
            if not lead_profile.get(field)
        ]
        if missing_fields:
            # A skipped field may be offered again only after the complete
            # sequence and another full cadence interval, never immediately.
            next_field = missing_fields[0]
            asked_fields = [
                field for field in asked_fields if lead_profile.get(field)
            ]
    if next_field:
        asked_fields.append(next_field)
        profile["lead_asked_fields"] = asked_fields
        return next_field, profile, 0
    return None, profile, 0


def _schedule_anonymous_signal(
    session_id: str,
    university_slug: str | None,
    course_slug: str | None,
    question_type: str,
) -> None:
    _create_background_task(
        log_anonymous_signal(session_id, university_slug, course_slug, question_type),
        name="anonymous-signal",
    )

async def background_lead_scoring(session_id: str, message: str, messages: list[BaseMessage]):
    """Runs lead scoring asynchronously after the user has received their response."""
    try:
        pool = await get_pool()
        events = classify_score_events(message)
        score = await log_score_events(session_id, events)
        score_triggered = await should_append_lead_ask(session_id, score)

        history = [{"role": "user" if isinstance(m, HumanMessage) else "assistant", "content": str(m.content)} for m in messages]
        intent_res = await lead_intent_classifier(session_id, message, history)
        
        lead_intent_detected = intent_res.get("lead_intent", False)
        lead_intent_confidence = intent_res.get("confidence", 0.0)
        intent_triggered = False
        
        if lead_intent_detected and lead_intent_confidence >= LEAD_INTENT_CONFIDENCE_THRESHOLD:
            if not await queries.lead_ask_exists(pool, session_id):
                intent_triggered = True
                await queries.mark_lead_ask(pool, session_id)

        triggered_by = "Score Engine" if score_triggered else ("LLM Intent" if intent_triggered else None)

        await queries.save_lead_intent_status(
            pool, session_id, lead_intent_detected, intent_res.get("intent_type", "none"),
            lead_intent_confidence, intent_res.get("reasoning", ""), triggered_by or "Score Engine",
        )
    except Exception as e:
        logger.error(f"Background lead scoring failed for {session_id}: {e}")


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    graph = StateGraph(ChatState)

    graph.add_node("triage", node_triage)
    graph.add_node("chitchat_reply", node_chitchat_reply)
    graph.add_node("contact_reply", node_contact_reply)
    graph.add_node("resolve_entities", node_resolve_entities)
    graph.add_node("agent", node_agent)
    graph.add_node("execute_tools", node_execute_tools)

    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, {
        "resolve_entities": "resolve_entities",
        "chitchat_reply": "chitchat_reply",
        "contact_reply": "contact_reply",
        END: END,
    })

    graph.add_edge("chitchat_reply", END)
    graph.add_edge("contact_reply", END)
    graph.add_edge("resolve_entities", "agent")

    # Contact status set only in resolve (defense) should still reach agent OR short-circuit.
    # resolve_entities always continues to agent for factual turns; contact is handled in triage.
    graph.add_conditional_edges("agent", route_after_agent, {
        "execute_tools": "execute_tools",
        END: END,
    })
    graph.add_edge("execute_tools", "agent")  # ReAct loop

    return graph.compile()

_graph = _build_graph()


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def _build_tool_calls_log(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Reconstructs the tool call log from the final message history."""
    tool_calls_log = []
    tool_results = [m for m in messages if isinstance(m, ToolMessage)]
    
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                entry = {"name": tc["name"], "args": tc["args"], "status": "SUCCESS"}
                tool_calls_log.append(entry)
    return tool_calls_log

async def _run_chat_turn_unlocked(
    session_id: str,
    site_id: str,
    message: str,
    page_university_slug: str | None,
    page_context: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_started_at: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    
    init_observability_context()

    # Hardcoded local paths do not need conversation history or resolver state.
    # Persistence runs concurrently after control is yielded to the SSE caller.
    greeting = is_greeting(message)
    contact = is_contact_intent(message)
    if greeting or contact:
        reply = CONTACT_REPLY if contact else (
            "Hello! I'm the DegreeBaba assistant. How can I help you with "
            "universities, courses, fees, or admissions today?"
        )
        persistence_task = _create_background_task(
            _persist_fast_path(
                session_id=session_id,
                site_id=site_id,
                message=message,
                reply=reply,
                page_university_slug=page_university_slug,
                ip_address=ip_address,
                user_agent=user_agent,
            ),
            name="fast-path-persistence",
        )
        mark_first_token()
        yield {"event": "token", "data": {"text": reply}}
        yield {
            "event": "final",
            "data": {
                "lead_ask": contact,
                "quick_replies": quick_replies_for(message),
                "metrics": {
                    "response_time_ms": 0,
                    "ttft_ms": 0,
                    "first_sse_event_ms": 0,
                    "agent_ttft_ms": 0,
                    "llm_duration_ms": 0,
                    "tool_execution_time_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "model_name": None,
                    "timing_tree": {"fast_path": True},
                },
            },
        }
        # Keep the session lock until ordered persistence has completed, while
        # the user has already received both SSE events.
        await persistence_task
        return

    t_stage = time.perf_counter()
    pool = await get_pool()
    pool_ms = (time.perf_counter() - t_stage) * 1000

    async def _timed(coro):
        started = time.perf_counter()
        value = await coro
        return value, (time.perf_counter() - started) * 1000

    pre_graph_started = time.perf_counter()
    (__, ensure_session_ms), (history_result, history_ms), (context, session_context_ms) = await asyncio.gather(
        _timed(queries.ensure_session(
            pool, session_id, site_id, page_university_slug, ip_address, user_agent
        )),
        _timed(queries.get_session_history(
            pool, session_id, limit=settings.max_conversation_messages
        )),
        _timed(queries.get_session_context(pool, session_id)),
    )
    history_messages: list[BaseMessage] = []
    for msg in history_result.get("messages", []):
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            history_messages.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            history_messages.append(AIMessage(content=content))

    async def _persist_user_message() -> float:
        started = time.perf_counter()
        await queries.insert_message(pool, session_id, "user", message)
        return (time.perf_counter() - started) * 1000

    user_persist_task = _create_background_task(
        _persist_user_message(), name="user-message-persistence"
    )
    pre_graph_setup_wall_ms = (time.perf_counter() - pre_graph_started) * 1000

    initial_state = _make_state(
        session_id=session_id,
        site_id=site_id,
        message=message,
        page_university_slug=page_university_slug,
        page_context=page_context or {},
        context=context,
        history_messages=history_messages,
    )

    reply_text = ""
    final_state = None
    first_sse_event_at: float | None = None
    streamed_any = False
    stream_replaced = False
    output_scan_incident: dict[str, Any] | None = None
    unsafe_reply_text: str | None = None

    def mark_first_sse_event() -> None:
        nonlocal first_sse_event_at
        if first_sse_event_at is None:
            first_sse_event_at = time.perf_counter()
            mark_first_token()
    
    # LangGraph exposes provider chunks even though node_agent calls ainvoke().
    # Scan a trailing window before each chunk is emitted; a final full scan
    # below can still retract/replace the accumulated response.
    graph_stream_started = time.perf_counter()
    async for event in _graph.astream_events(initial_state, version="v2"):
        event_kind = event["event"]
        
        # Forward clean model chunks immediately for real TTFT.
        if event_kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessage) and chunk.content:
                node_name = event.get("metadata", {}).get("langgraph_node")
                if node_name in ("agent", "chitchat_reply"):
                    chunk_text = str(chunk.content)
                    reply_text += chunk_text
                    if not stream_replaced:
                        incremental_scan = scan_output(reply_text[-1000:])
                        if incremental_scan["clean"]:
                            mark_first_sse_event()
                            streamed_any = True
                            yield {"event": "token", "data": {"text": chunk_text}}
                        else:
                            output_scan_incident = incremental_scan
                            unsafe_reply_text = reply_text
                            stream_replaced = True
                            mark_first_sse_event()
                            yield {
                                "event": "replace",
                                "data": {"text": incremental_scan["safe_reply"]},
                            }
                    
        # Capture the final state updates
        if event_kind == "on_chain_end" and event["name"] == "LangGraph":
            final_state = event["data"]["output"]
    graph_stream_ms = (time.perf_counter() - graph_stream_started) * 1000

    # Fallback if astream_events didn't capture the final state properly or if streaming didn't output text
    graph_fallback_ms = 0.0
    if not final_state:
        graph_fallback_started = time.perf_counter()
        final_state = await _graph.ainvoke(initial_state)
        graph_fallback_ms = (time.perf_counter() - graph_fallback_started) * 1000

    reply_assembly_started = time.perf_counter()
    if not reply_text:
        if final_state.get("reply"):
            reply_text = final_state["reply"]
        elif final_state.get("messages"):
            last_msg = final_state["messages"][-1]
            if isinstance(last_msg, AIMessage) and not last_msg.tool_calls:
                reply_text = str(last_msg.content)
        
    # Handle cache hits.
    if final_state.get("cache_hit") and not reply_text:
        reply_text = final_state.get("reply", "")

    # P0: request-time lead decision (must be in SSE final before client disconnects)
    lead_ask = bool(final_state.get("lead_ask")) if final_state else False
    lead_ask_triggered_by = final_state.get("lead_ask_triggered_by") if final_state else None
    if not lead_ask and detect_fast_lead_intent(message):
        lead_ask = True
        lead_ask_triggered_by = lead_ask_triggered_by or "Fast Lead Intent"
    if not lead_ask_triggered_by:
        lead_ask_triggered_by = "Score Engine"

    if lead_ask:
        logger.info(
            "[%s] LEAD ASK TRIGGERED | reason=%s | msg=%r",
            session_id,
            lead_ask_triggered_by,
            message[:80],
        )

    if not reply_text:
        # Contact path should already have set reply via state; fallback safety
        if lead_ask and (final_state or {}).get("triage_intent") == "contact":
            reply_text = CONTACT_REPLY
        else:
            await log_unanswered(session_id, message, None, None)
            reply_text = (
                "I don't have that detail on file yet — I've logged this so the "
                "DegreeBaba team can fill the gap. Feel free to ask about fees, "
                "eligibility, or available programs."
            )
            lead_ask = True
            lead_ask_triggered_by = "No Answer Available"

    # BACKGROUND LEAD SCORING (analytics only — does not control this turn's lead_ask)
    _create_background_task(
        background_lead_scoring(session_id, message, final_state.get("messages", []) if final_state else []),
        name="lead-scoring",
    )

    # Final full-response scan. If streaming already began, replace the bubble
    # rather than pretending the earlier chunks were never delivered.
    scan = scan_output(reply_text)
    if not scan["clean"]:
        output_scan_incident = scan
        unsafe_reply_text = reply_text
        logger.warning("Output scan blocked response (reason=%s) for session=%s", scan["reason"], session_id)
        reply_text = scan["safe_reply"]
        if streamed_any and not stream_replaced:
            stream_replaced = True
            yield {"event": "replace", "data": {"text": reply_text}}

    if output_scan_incident:
        await queries.insert_flagged_message(
            pool,
            session_id,
            (unsafe_reply_text or reply_text)[:500],
            layer=f"output_scan:{output_scan_incident['reason']}",
            risk_score=1.0,
            reason=output_scan_incident["reason"] or "output_scan",
        )

    if stream_replaced:
        reply_text = (output_scan_incident or scan)["safe_reply"]
    elif not streamed_any:
        mark_first_sse_event()
        yield {"event": "token", "data": {"text": reply_text}}

    # User persistence overlaps graph/model work but must finish before the
    # assistant row so chronological message IDs remain correct.
    persist_user_message_ms = await user_persist_task

    # Observability stats
    metadata = request_metadata_var.get()
    started_at = metadata["started_at"]
    from datetime import datetime, timezone
    completed_at = datetime.now(timezone.utc)
    
    t_now = time.perf_counter()
    response_time_ms = int((t_now - metadata["t_start"]) * 1000)
    
    t_first = first_sse_event_at or t_now
    agent_ttft_ms = int((t_first - metadata["t_start"]) * 1000)
    ttft_ms = int((t_first - (request_started_at or metadata["t_start"])) * 1000)
    
    tools_executed = tool_metrics_var.get() or []
    tool_exec_time = sum(m.get("duration_ms", 0) for m in tools_executed)

    # ── Timing visibility: resolver / llm / tool / total ────────────────────
    # Added purely for bottleneck localization (per the "RESOLVED -> ~2s ->
    # TOOL CALL" / "TOOL RESULT -> ~2s -> CHAT COMPLETE" gaps) — no behavior
    # or latency changes here, only logging.
    resolver_ms = (final_state or {}).get("resolver_ms", 0.0)
    llm_ms_total = (final_state or {}).get("llm_ms_total", 0.0)
    tool_ms_total = (final_state or {}).get("tool_ms_total", 0.0)
    pre_graph_setup_ms = pool_ms + pre_graph_setup_wall_ms
    graph_internal_overhead_ms = max(
        graph_stream_ms - resolver_ms - llm_ms_total - tool_ms_total,
        0.0,
    )
    reply_assembly_ms = (t_now - reply_assembly_started) * 1000
    accounted_ms = pre_graph_setup_ms + graph_stream_ms + graph_fallback_ms + reply_assembly_ms
    unaccounted_ms = max(response_time_ms - accounted_ms, 0.0)

    tool_calls_log = _build_tool_calls_log(final_state.get("messages", []))
    # Tool calls are reconstructed from graph messages for compatibility;
    # attach the timing/status captured by the execution decorator so analytics
    # retains per-invocation duration instead of only an aggregate total.
    for call, metric in zip(tool_calls_log, tools_executed):
        call.update({
            "duration_ms": metric.get("duration_ms", 0),
            "status": metric.get("status", call.get("status", "SUCCESS")),
            "started_at": metric.get("started_at"),
            "completed_at": metric.get("completed_at"),
        })
    
    assistant_persist_started = time.perf_counter()
    await queries.insert_message(
        pool, session_id, "assistant", reply_text,
        tool_calls=tool_calls_log,
        response_time_ms=response_time_ms,
        ttft_ms=ttft_ms,
        model_name=metadata["model_name"],
        input_tokens=metadata["input_tokens"],
        output_tokens=metadata["output_tokens"],
        total_tokens=metadata["total_tokens"],
        estimated_cost_usd=metadata["estimated_cost_usd"],
        tool_execution_time_ms=tool_exec_time,
        started_at=started_at,
        completed_at=completed_at,
    )
    assistant_persist_ms = (time.perf_counter() - assistant_persist_started) * 1000

    profile_context = dict(
        (final_state or {}).get("profile_context_update")
        or context.get("profile_context")
        or {}
    )
    progressive_lead_field = (final_state or {}).get("progressive_lead_field")
    profile_write_needed = (final_state or {}).get("profile_context_update") is not None
    resolved_status = ((final_state or {}).get("resolved") or {}).get("resolution_status")
    if progressive_lead_field:
        progressive_lead_field, profile_context, profile_counter = _plan_progressive_lead_field(
            context,
            profile_context,
            forced_field=progressive_lead_field,
        )
        profile_write_needed = True
    elif not lead_ask and resolved_status in {
        "resolved", "session_context", "page_context", "catalog_query", "comparison_context", "none"
    }:
        progressive_lead_field, profile_context, profile_counter = _plan_progressive_lead_field(
            context,
            profile_context,
        )
        profile_write_needed = True
    else:
        profile_counter = int(context.get("factual_turns_since_profile_ask") or 0)

    if profile_write_needed:
        await queries.update_profile_context(
            pool,
            session_id,
            profile_context,
            profile_counter,
        )

    turn_total_ms = (time.perf_counter() - metadata["t_start"]) * 1000
    turn_accounted_ms = accounted_ms + assistant_persist_ms
    turn_unaccounted_ms = max(turn_total_ms - turn_accounted_ms, 0.0)
    logger.info(
        "[%s] TIMING TREE | pool_ms=%.1f ensure_session_ms=%.1f history_ms=%.1f "
        "persist_user_ms=%.1f session_context_ms=%.1f resolver_ms=%.1f llm_ms=%.1f "
        "tool_ms=%.1f graph_ms=%.1f graph_overhead_ms=%.1f reply_assembly_ms=%.1f "
        "assistant_persist_ms=%.1f accounted_ms=%.1f total_ms=%.1f unaccounted_ms=%.1f "
        "ttft_first_sse_ms=%d agent_ttft_ms=%d",
        session_id,
        pool_ms, ensure_session_ms, history_ms, persist_user_message_ms, session_context_ms,
        resolver_ms, llm_ms_total, tool_ms_total, graph_stream_ms, graph_internal_overhead_ms,
        reply_assembly_ms, assistant_persist_ms, turn_accounted_ms, turn_total_ms,
        turn_unaccounted_ms, ttft_ms, agent_ttft_ms,
    )

    yield {
        "event": "final",
        "data": {
            "lead_ask": lead_ask,
            "progressive_lead_field": progressive_lead_field,
            "quick_replies": quick_replies_for(message),
            "metrics": {
                "response_time_ms": response_time_ms,
                "ttft_ms": ttft_ms,
                "first_sse_event_ms": agent_ttft_ms,
                "agent_ttft_ms": agent_ttft_ms,
                "llm_duration_ms": metadata.get("llm_duration_ms", 0),
                "tool_execution_time_ms": tool_exec_time,
                "input_tokens": metadata["input_tokens"],
                "output_tokens": metadata["output_tokens"],
                "total_tokens": metadata["total_tokens"],
                "estimated_cost_usd": metadata["estimated_cost_usd"],
                "model_name": metadata["model_name"],
                "timing_tree": {
                    "pool_ms": round(pool_ms, 1),
                    "ensure_session_ms": round(ensure_session_ms, 1),
                    "history_ms": round(history_ms, 1),
                    "persist_user_message_ms": round(persist_user_message_ms, 1),
                    "session_context_ms": round(session_context_ms, 1),
                    "pre_graph_setup_ms": round(pre_graph_setup_ms, 1),
                    "graph_execution_ms": round(graph_stream_ms, 1),
                    "graph_fallback_ms": round(graph_fallback_ms, 1),
                    "graph_internal_overhead_ms": round(graph_internal_overhead_ms, 1),
                    "reply_assembly_ms": round(reply_assembly_ms, 1),
                    "assistant_persist_ms": round(assistant_persist_ms, 1),
                    "response_generation_ms": response_time_ms,
                    "response_generation_unaccounted_ms": round(unaccounted_ms, 1),
                    "accounted_ms": round(turn_accounted_ms, 1),
                    "total_ms": round(turn_total_ms, 1),
                    "unaccounted_ms": round(turn_unaccounted_ms, 1),
                },
            },
        },
    }


async def run_chat_turn(
    session_id: str,
    site_id: str,
    message: str,
    page_university_slug: str | None,
    page_context: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_started_at: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Serialize turns per session while allowing unrelated sessions to run."""
    entry = _SESSION_LOCKS.get(session_id)
    if entry is None:
        entry = {"lock": asyncio.Lock(), "users": 0}
        _SESSION_LOCKS[session_id] = entry
    entry["users"] += 1
    try:
        async with entry["lock"]:
            async for event in _run_chat_turn_unlocked(
                session_id=session_id,
                site_id=site_id,
                message=message,
                page_university_slug=page_university_slug,
                page_context=page_context,
                ip_address=ip_address,
                user_agent=user_agent,
                request_started_at=request_started_at,
            ):
                yield event
    finally:
        entry["users"] -= 1
        if entry["users"] == 0 and _SESSION_LOCKS.get(session_id) is entry:
            _SESSION_LOCKS.pop(session_id, None)
