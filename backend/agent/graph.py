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

from agent.guardrail import OFF_TOPIC_REDIRECT, guardrail_check, get_guardrail_reason
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
    Persists resolved slugs back to session_context so the next turn inherits.
    Also logs anonymous demand signals for fee / eligibility intent.
    """
    message = state["raw_message"]
    context = state.get("context", {})
    session_id = state["session_id"]

    resolved = await _resolve_entities(message, context)

    pool = await get_pool()
    await queries.update_session_context(
        pool,
        session_id,
        resolved.get("university_slug"),
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

    return {"resolved": resolved}


async def node_agent_decide(state: ChatState) -> dict[str, Any]:
    """
    The LLM (with tools bound) decides which tool(s) to call or returns a
    direct reply.  Supports parallel tool calling in a single response.
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

    # Inject resolved context so the LLM knows exactly which slugs to pass to tools.
    # Without this, the LLM must guess arguments and often declines to call any tool.
    resolved = state.get("resolved", {})
    context_parts = []
    if resolved.get("university_slug"):
        context_parts.append(f"university_slug={resolved['university_slug']}")
    if resolved.get("course_slug"):
        context_parts.append(f"course_slug={resolved['course_slug']}")
    if resolved.get("specialization_slug"):
        context_parts.append(f"specialization_slug={resolved['specialization_slug']}")

    messages = list(state["messages"])
    if context_parts:
        context_note = (
            f"[Resolved context for this turn: {', '.join(context_parts)}. "
            "Use these exact slugs when calling tools.]"
        )
        # Insert as a SystemMessage right before the last HumanMessage
        messages = messages[:-1] + [SystemMessage(content=context_note)] + messages[-1:]

    try:
        response: AIMessage = await model_with_tools.ainvoke(messages)
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
            response: AIMessage = await llm_client.chat_model.ainvoke(synthesis_messages)
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
    graph.add_node("execute_tools", ToolNode(TOOLS))
    graph.add_node("synthesize_reply", node_synthesize_reply)
    graph.add_node("update_lead_score", node_update_lead_score)

    graph.add_edge(START, "resolve_entities")
    graph.add_edge("resolve_entities", "agent_decide")

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


def _any_tool_not_found(state: dict[str, Any]) -> bool:
    """True when any ToolMessage result carries not_found=True."""
    for msg in state.get("messages", []):
        if isinstance(msg, ToolMessage):
            try:
                result = json.loads(msg.content)
                if isinstance(result, dict) and result.get("not_found"):
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
    return False


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

async def run_chat_turn(
    session_id: str,
    site_id: str,
    message: str,
    page_university_slug: str | None,
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
    await queries.ensure_session(pool, session_id, site_id, page_university_slug)
    await queries.insert_message(pool, session_id, "user", message)

    # ── Guardrail: cheap pre-check before any LLM call ──
    if not guardrail_check(message):
        reason = get_guardrail_reason(message)
        await queries.insert_flagged_message(pool, session_id, message, reason)
        await queries.insert_message(pool, session_id, "assistant", OFF_TOPIC_REDIRECT, [])
        async for token in _stream_text(OFF_TOPIC_REDIRECT):
            yield {"event": "token", "data": {"text": token}}
        yield {"event": "final", "data": {"lead_ask": False, "quick_replies": []}}
        return


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

    # ── Log unanswered when no data was found ──
    if _any_tool_not_found(final_state) or not reply:
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
