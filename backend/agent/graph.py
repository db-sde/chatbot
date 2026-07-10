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
from agent.llm_client import SYSTEM_PROMPT, llm_client
from agent.resolve import resolve_entities as _resolve_entities
from agent.tools import TOOLS, log_anonymous_signal, log_unanswered
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
        await queries.update_session_context(
            pool,
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            resolved.get("specialization_slug"),
            replace_dependents=True,
        )
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
    return {"resolved": resolved, "resolver_ms": resolver_ms}


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
    if not llm_client.enabled:
        return {"messages": [AIMessage(content="I can help with DegreeBaba course fees, eligibility, and admissions.")]}

    messages = list(state["messages"])
    resolved = state.get("resolved", {})
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
    resolution_status = resolved.get("resolution_status", "none")
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
    
    init_observability_context()

    t_stage = time.perf_counter()
    pool = await get_pool()
    pool_ms = (time.perf_counter() - t_stage) * 1000

    t_stage = time.perf_counter()
    await queries.ensure_session(pool, session_id, site_id, page_university_slug, ip_address, user_agent)
    ensure_session_ms = (time.perf_counter() - t_stage) * 1000

    t_stage = time.perf_counter()
    history_result = await queries.get_session_history(pool, session_id, limit=settings.max_conversation_messages)
    history_ms = (time.perf_counter() - t_stage) * 1000
    history_messages: list[BaseMessage] = []
    for msg in history_result.get("messages", []):
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            history_messages.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            history_messages.append(AIMessage(content=content))

    t_stage = time.perf_counter()
    await queries.insert_message(pool, session_id, "user", message)
    persist_user_message_ms = (time.perf_counter() - t_stage) * 1000

    t_stage = time.perf_counter()
    context = await queries.get_session_context(pool, session_id)
    session_context_ms = (time.perf_counter() - t_stage) * 1000

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

    def mark_first_sse_event() -> None:
        nonlocal first_sse_event_at
        if first_sse_event_at is None:
            first_sse_event_at = time.perf_counter()
            mark_first_token()
    
    # This observes graph events. node_agent currently uses model.ainvoke(), so
    # user-visible token events occur only if a node itself uses a streaming
    # model call; otherwise the first token is emitted from the buffered reply
    # after graph completion below.
    graph_stream_started = time.perf_counter()
    async for event in _graph.astream_events(initial_state, version="v2"):
        event_kind = event["event"]
        
        # Buffer model chunks. Output security scanning must inspect the full
        # response before any generated text is emitted to the client.
        if event_kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessage) and chunk.content:
                node_name = event.get("metadata", {}).get("langgraph_node")
                if node_name in ("agent", "chitchat_reply"):
                    reply_text += chunk.content
                    
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

    # BACKGROUND LEAD SCORING (analytics only — does not control this turn's lead_ask)
    _create_background_task(
        background_lead_scoring(session_id, message, final_state.get("messages", []) if final_state else []),
        name="lead-scoring",
    )

    # Output security scan
    scan = scan_output(reply_text)
    if not scan["clean"]:
        logger.warning("Output scan blocked response (reason=%s) for session=%s", scan["reason"], session_id)
        await queries.insert_flagged_message(
            pool,
            session_id,
            reply_text[:500],
            layer=f"output_scan:{scan['reason']}",
            risk_score=1.0,
            reason=scan["reason"] or "output_scan",
        )
        reply_text = scan["safe_reply"]

    # This is the first point at which generated text is known to be safe.
    mark_first_sse_event()
    yield {"event": "token", "data": {"text": reply_text}}

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
    pre_graph_setup_ms = (
        pool_ms + ensure_session_ms + history_ms + persist_user_message_ms + session_context_ms
    )
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
            "quick_replies": ["Check fees", "Eligibility", "Talk to counsellor"],
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
