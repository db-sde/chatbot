from __future__ import annotations

"""
LangGraph agent loop for the DegreeBaba chatbot.

Node sequence
─────────────
  START
    → resolve_entities      (entity snap + session context)
    → agent_decide           (LLM chooses tools or replies directly)
    ↕  ↕  (loop until no tool calls remain)
    → execute_tools          (LangGraph ToolNode runs tool functions)
    → synthesize_reply       (LLM writes the final human-facing answer)
    → update_lead_score      (silent — never blocks the reply stream)
  END

run_chat_turn() is the public entry-point called from main.py.
It owns all session / message persistence so the graph nodes stay pure.
"""

import asyncio
import json
import logging
from typing import Annotated, Any, AsyncIterator, TypedDict

import groq

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from agent.guardrail import OFF_TOPIC_REDIRECT
from security.output_scan import scan_output
from agent.llm_client import SYSTEM_PROMPT, llm_client
from agent.resolve import resolve_entities as _resolve_entities
from agent.tools import TOOLS, log_anonymous_signal, log_unanswered
from db import queries
from db.pool import get_pool

logger = logging.getLogger(__name__)

from leads.scoring import classify_score_events, log_score_events, should_append_lead_ask


# ---------------------------------------------------------------------------
# State schema
#
# LangGraph merges partial dicts returned by each node.  Keys NOT declared
# here will be silently dropped between nodes.  `messages` uses add_messages
# so the list is appended-to rather than replaced.
# ---------------------------------------------------------------------------

class ChatState(TypedDict, total=False):
    # LangChain message history — appended by add_messages reducer
    messages: Annotated[list[BaseMessage], add_messages]
    # Immutable turn metadata
    session_id: str
    site_id: str
    raw_message: str
    page_university_slug: str | None
    context: dict[str, Any]
    # Mutable turn output
    resolved: dict[str, Any]
    reply: str
    tool_calls_log: list[dict[str, Any]]
    lead_ask: bool
    tool_call_count: int


def _make_state(
    *,
    session_id: str,
    site_id: str,
    message: str,
    page_university_slug: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the initial graph state from a single user turn."""
    return {
        "messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=message)],
        "session_id": session_id,
        "site_id": site_id,
        "raw_message": message,
        "page_university_slug": page_university_slug,
        "context": context,
        "resolved": {},
        "reply": "",
        "tool_calls_log": [],
        "lead_ask": False,
        "tool_call_count": 0,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def node_resolve_entities(state: ChatState) -> dict[str, Any]:
    """
    Entity resolution: LLM extraction → fuzzy slug snap → context fallback.

    page_university_slug is passed to the resolver as a *passive hint* —
    it is only used when the user's message requires factual catalog data
    and no entity was found via extraction or conversational context.

    Persists resolved slugs back to session_context so the next turn
    inherits them — but only slugs that came from real extraction or prior
    conversational context, never page-hint-only slugs.
    """
    message = state["raw_message"]
    context = state.get("context", {})
    session_id = state["session_id"]
    page_university_slug = state.get("page_university_slug")

    resolved = await _resolve_entities(message, context, page_university_slug)

    # Only persist slugs that were established through user intent this turn
    # (via LLM extraction or prior conversational context).  A slug that came
    # solely from the page hint should NOT be written into session_context,
    # because that would promote a passive page hint into conversational fact.
    context_university = context.get("current_university_slug")
    new_university = resolved.get("university_slug")
    # If the resolved university equals the page hint AND was not already in
    # conversational context, it came only from the page — don't persist it.
    from agent.resolve import _message_needs_entity
    page_hint_only = (
        new_university == page_university_slug
        and new_university != context_university
        and not _message_needs_entity(message)
    )
    persist_university = None if page_hint_only else new_university

    pool = await get_pool()
    await queries.update_session_context(
        pool,
        session_id,
        persist_university,
        resolved.get("course_slug"),
        resolved.get("specialization_slug"),
    )

    # Log anonymous demand signals
    intent_text = message.lower()
    if any(t in intent_text for t in ("fee", "fees", "cost", "price", "emi")):
        await log_anonymous_signal(
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            "fee",
        )
    elif any(t in intent_text for t in ("eligible", "eligibility", "criteria")):
        await log_anonymous_signal(
            session_id,
            resolved.get("university_slug"),
            resolved.get("course_slug"),
            "eligibility",
        )

    # Attach a flag so node_agent_decide knows whether this resolution is
    # backed by real user intent or is merely a passive page hint.
    resolved["_page_hint_only"] = page_hint_only
    return {"resolved": resolved}


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
            # Recreate ToolMessage with sanitized string content
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


async def node_agent_decide(state: ChatState) -> dict[str, Any]:
    """
    The LLM (with tools bound) decides which tool(s) to call or returns a
    direct reply.  Supports parallel tool calling in a single response.

    A context note is only injected when slugs were established through real
    user intent (extraction or prior conversational context).  Page-hint-only
    resolutions (e.g. greeting on an NMIMS page) produce no context note so
    the LLM is free to reply naturally.
    """
    if llm_client.groq_chat and llm_client.gemini_chat:
        model_with_tools = llm_client.groq_chat.bind_tools(TOOLS).with_fallbacks(
            [llm_client.gemini_chat.bind_tools(TOOLS)]
        )
    elif llm_client.groq_chat:
        model_with_tools = llm_client.groq_chat.bind_tools(TOOLS)
    elif llm_client.gemini_chat:
        model_with_tools = llm_client.gemini_chat.bind_tools(TOOLS)
    else:
        model_with_tools = llm_client.chat_model.bind_tools(TOOLS) if llm_client.chat_model else None

    if model_with_tools is None:
        # No LLM key — return a static offline fallback.
        return {
            "messages": [
                AIMessage(
                    content="I can help with DegreeBaba course fees, eligibility, and admissions."
                )
            ]
        }

    messages = list(state["messages"])
    resolved = state.get("resolved", {})

    # Only inject a context note when resolution is backed by real user intent.
    # _page_hint_only=True means the slug came only from the page URL and the
    # user did not ask a factual question — do NOT pollute the LLM context.
    page_hint_only = resolved.get("_page_hint_only", False)
    context_parts = []
    if not page_hint_only:
        if resolved.get("university_slug"):
            context_parts.append(f"university_slug={resolved['university_slug']}")
        if resolved.get("course_slug"):
            context_parts.append(f"course_slug={resolved['course_slug']}")
        if resolved.get("specialization_slug"):
            context_parts.append(f"specialization_slug={resolved['specialization_slug']}")

    if context_parts:
        context_note = (
            f"[Resolved context for this turn: {', '.join(context_parts)}. "
            "Use these exact slugs when calling tools.]"
        )
        # Insert as a SystemMessage right before the last HumanMessage
        messages = messages[:-1] + [SystemMessage(content=context_note)] + messages[-1:]

    try:
        response: AIMessage = await model_with_tools.ainvoke(_clean_messages(messages))
    except groq.RateLimitError:
        logger.warning("Groq rate limit hit in node_agent_decide — returning rate-limit message.")
        return {
            "messages": [
                AIMessage(
                    content="I'm temporarily unavailable due to high demand. Please try again in a moment."
                )
            ]
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Groq agent call failed: %s", exc)
        return {
            "messages": [
                AIMessage(
                    content="I encountered an issue processing your request. Please try again."
                )
            ]
        }
    return {"messages": [response]}  # add_messages will append, not replace


async def node_synthesize_reply(state: ChatState) -> dict[str, Any]:
    """
    After all tools have run, ask the LLM to produce a natural, grounded reply
    using the full conversation history (including ToolMessage results).
    Also builds the compact tool_calls_log for admin transcript inspection.
    """
    messages = state["messages"]

    # Gather tool call log for admin
    tool_calls_log: list[dict[str, Any]] = []
    tool_result_iter = iter(
        [m for m in messages if isinstance(m, ToolMessage)]
    )
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                entry: dict[str, Any] = {"name": tc["name"], "args": tc["args"]}
                # Attach the next tool result to this call
                try:
                    tm = next(tool_result_iter)
                    entry["result_summary"] = str(tm.content)[:600]
                except StopIteration:
                    pass
                tool_calls_log.append(entry)

    # If no tool calls happened, check whether the last AI message already
    # contains a direct answer (the LLM replied without tools).
    last_ai = next(
        (m for m in reversed(messages) if isinstance(m, AIMessage) and m.content),
        None,
    )
    if not tool_calls_log and last_ai:
        return {
            "reply": str(last_ai.content),
            "tool_calls_log": tool_calls_log,
        }

    # Tool calls ran — ask the LLM to synthesise a final reply.
    if llm_client.chat_model is None:
        reply_text = (
            "I found the data but couldn't format it — please check with our team."
        )
    else:
        synthesis_messages = list(messages) + [
            HumanMessage(
                content=(
                    "Based on the tool results above, write a concise, helpful reply "
                    "for the student. Use Rs formatting for fees. Do not invent any "
                    "data not present in the tool results."
                )
            )
        ]
        try:
            response: AIMessage = await llm_client.chat_model.ainvoke(_clean_messages(synthesis_messages))
            reply_text = str(response.content) if response.content else (
                "I found the data but couldn't format it — please check with our team."
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Groq synthesis failed: %s", exc)
            reply_text = "I found the data but couldn't format it — please try again in a moment."

    return {"reply": reply_text, "tool_calls_log": tool_calls_log}


async def node_execute_tools(state: ChatState) -> dict[str, Any]:
    """Execute tools node wrapper that increments the loop counter."""
    tool_node = ToolNode(TOOLS)
    result = await tool_node.ainvoke(state)
    count = state.get("tool_call_count", 0) + 1
    return {**result, "tool_call_count": count}


MAX_TOOL_ITERATIONS = 4


def route_after_agent_decide(state: ChatState) -> str:
    """Decides whether to execute tools or exit synthesis based on iteration cap."""
    if state.get("tool_call_count", 0) >= MAX_TOOL_ITERATIONS:
        logger.warning("Agent reached maximum tool call iterations (%d). Bypassing to synthesis.", MAX_TOOL_ITERATIONS)
        return "synthesize_reply"
    next_step = tools_condition(state)
    if next_step == "tools":
        return "execute_tools"
    return "synthesize_reply"


async def node_update_lead_score(state: ChatState) -> dict[str, Any]:
    """Silent node — scores the turn and sets lead_ask flag if threshold crossed."""
    session_id = state["session_id"]
    message = state["raw_message"]
    events = classify_score_events(message)
    score = await log_score_events(session_id, events)
    lead_ask = await should_append_lead_ask(session_id, score)
    return {"lead_ask": lead_ask}


# ---------------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    graph = StateGraph(ChatState)

    graph.add_node("resolve_entities", node_resolve_entities)
    graph.add_node("agent_decide", node_agent_decide)
    graph.add_node("execute_tools", node_execute_tools)
    graph.add_node("synthesize_reply", node_synthesize_reply)
    graph.add_node("update_lead_score", node_update_lead_score)

    graph.add_edge(START, "resolve_entities")
    graph.add_edge("resolve_entities", "agent_decide")

    graph.add_conditional_edges(
        "agent_decide",
        route_after_agent_decide,
        {
            "execute_tools": "execute_tools",
            "synthesize_reply": "synthesize_reply",
        },
    )
    graph.add_edge("execute_tools", "agent_decide")  # ReAct loop

    graph.add_edge("synthesize_reply", "update_lead_score")
    graph.add_edge("update_lead_score", END)

    return graph.compile()


_graph = _build_graph()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _stream_text(text: str) -> AsyncIterator[str]:
    for token in text.split(" "):
        yield token + " "
        await asyncio.sleep(0)


def _all_tool_calls_failed(state: dict[str, Any]) -> bool:
    """
    True only when EVERY tool call made this turn returned not_found=True.

    Previously this flagged the whole turn as unanswered if ANY single tool
    call failed, even when other tool calls in the same turn succeeded and
    the user got a genuinely good reply (e.g. a comparison that succeeds
    alongside one unrelated FAQ lookup that doesn't). That polluted the
    unanswered_questions analytics — the one signal meant to show real
    content gaps — with turns that were actually answered fine. If no tool
    calls happened at all this turn, this returns False (nothing to judge
    as failed); the empty-reply check at the call site still catches that
    case separately.
    """
    tool_messages = [m for m in state.get("messages", []) if isinstance(m, ToolMessage)]
    if not tool_messages:
        return False
    for msg in tool_messages:
        try:
            result = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            return False
        if not (isinstance(result, dict) and result.get("not_found")):
            return False
    return True


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def run_chat_turn(
    session_id: str,
    site_id: str,
    message: str,
    page_university_slug: str | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Drive a single user turn through the full agent pipeline and stream SSE
    events back to the HTTP layer.

    Emits:
      { event: "token", data: { text: "..." } }   — one per word token
      { event: "final", data: { lead_ask: bool, quick_replies: [...] } }
    """
    pool = await get_pool()

    # ── Session bootstrap + user message persistence ──
    await queries.ensure_session(pool, session_id, site_id, page_university_slug, ip_address, user_agent)
    await queries.insert_message(pool, session_id, "user", message)

    # ── Load prior session context so slugs carry forward ──
    context = await queries.get_session_context(pool, session_id)

    # ── Run LangGraph agent ──
    initial_state = _make_state(
        session_id=session_id,
        site_id=site_id,
        message=message,
        page_university_slug=page_university_slug,
        context=context,
    )
    final_state: dict[str, Any] = await _graph.ainvoke(initial_state)

    reply: str = final_state.get("reply", "")
    lead_ask: bool = final_state.get("lead_ask", False)

    # ── Log unanswered only when every tool call failed, or there's no reply ──
    if _all_tool_calls_failed(final_state) or not reply:
        await log_unanswered(session_id, message, None, None)
        reply = reply or (
            "I don't have that detail on file yet — I've logged this so the "
            "DegreeBaba team can fill the gap. Feel free to ask about fees, "
            "eligibility, or available programs."
        )

    # ── Append soft lead capture prompt ──
    if lead_ask:
        reply += (
            "\n\nI can also put together a personalised fee-comparison PDF or "
            "arrange a callback from a counsellor. Just share your name and phone — "
            "or choose 'No thanks' if you prefer to keep browsing."
        )

    # ── Output security scan ──
    scan = scan_output(reply)
    if not scan["clean"]:
        logger.warning(
            "Output scan blocked response (reason=%s) for session=%s",
            scan["reason"], session_id,
        )
        await queries.insert_flagged_message(
            pool, session_id, reply[:500], f"output_scan:{scan['reason']}"
        )
        reply = scan["safe_reply"]

    # ── Persist assistant reply + compact tool log ──
    tool_calls_log: list[dict[str, Any]] = final_state.get("tool_calls_log", [])
    await queries.insert_message(pool, session_id, "assistant", reply, tool_calls_log)

    # ── Stream reply tokens ──
    async for token in _stream_text(reply):
        yield {"event": "token", "data": {"text": token}}

    yield {
        "event": "final",
        "data": {
            "lead_ask": lead_ask,
            "quick_replies": (
                ["No thanks, just browsing"]
                if lead_ask
                else ["Check fees", "Eligibility", "Talk to counsellor"]
            ),
        },
    }
