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
"""

import asyncio
import json
import logging
import time
from typing import Annotated, Any, AsyncIterator, TypedDict

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

from leads.scoring import classify_score_events, log_score_events, should_append_lead_ask
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
    tool_call_count: int
    # New fields for optimization
    triage_intent: str
    cache_hit: bool


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
        "tool_call_count": 0,
        "triage_intent": "factual",
        "cache_hit": False,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def node_triage(state: ChatState) -> dict[str, Any]:
    """
    FAST PATH: Semantic Cache + Chitchat Router.
    This node should use a VERY cheap/fast model (e.g., Llama-3-8B) or non-LLM methods.
    """
    message = state["raw_message"]
    
    # 1. SEMANTIC CACHE (Pseudo-code)
    # cached_reply = await semantic_cache.get(message)
    # if cached_reply:
    #     return {"reply": cached_reply, "cache_hit": True}
    
    # 2. FAST INTENT CLASSIFICATION (Pseudo-code)
    # intent = await fast_classifier.classify(message) # "chitchat" or "factual"
    # For now, we default to "factual" to route to the heavy pipeline.
    
    return {"triage_intent": "factual", "cache_hit": False}

def route_after_triage(state: ChatState) -> str:
    if state.get("cache_hit"):
        return END # Skip everything, run_chat_turn will use state["reply"]
    if state.get("triage_intent") == "chitchat":
        return "chitchat_reply"
    return "resolve_entities"

async def node_chitchat_reply(state: ChatState) -> dict[str, Any]:
    """Handles simple greetings without hitting the heavy agent or DB."""
    # Use a tiny model or hardcoded responses here to save $$
    reply = "Hello! I'm the DegreeBaba assistant. How can I help you with courses, fees, or admissions today?"
    return {"reply": reply, "messages": [AIMessage(content=reply)]}


async def node_resolve_entities(state: ChatState) -> dict[str, Any]:
    """
    Entity resolution: LLM extraction → fuzzy slug snap → context fallback.
    
    CRITICAL OPTIMIZATION: _resolve_entities MUST use a fast/cheap model 
    (e.g., Groq Llama-3-8B) or a non-LLM fuzzy matcher. Do not use your 
    expensive Agent model here.
    """
    message = state["raw_message"]
    context = state.get("context", {})
    session_id = state["session_id"]
    page_university_slug = state.get("page_university_slug")

    resolved = await _resolve_entities(message, context, page_university_slug)

    context_university = context.get("current_university_slug")
    new_university = resolved.get("university_slug")
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

    intent_text = message.lower()
    if any(t in intent_text for t in ("fee", "fees", "cost", "price", "emi")):
        await log_anonymous_signal(session_id, resolved.get("university_slug"), resolved.get("course_slug"), "fee")
    elif any(t in intent_text for t in ("eligible", "eligibility", "criteria")):
        await log_anonymous_signal(session_id, resolved.get("university_slug"), resolved.get("course_slug"), "eligibility")

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
        messages = messages[:-1] + [SystemMessage(content=page_note)] + messages[-1:]

    # ── Resolved entity slugs note (from fuzzy entity resolution) ─────────
    page_hint_only = resolved.get("_page_hint_only", False)
    context_parts = []
    if not page_hint_only:
        if resolved.get("university_slug"): context_parts.append(f"university_slug={resolved['university_slug']}")
        if resolved.get("course_slug"): context_parts.append(f"course_slug={resolved['course_slug']}")
        if resolved.get("specialization_slug"): context_parts.append(f"specialization_slug={resolved['specialization_slug']}")

    if context_parts:
        context_note = (
            f"[Resolved context for this turn: {', '.join(context_parts)}. "
            "Use these exact slugs when calling tools.]"
        )
        messages = messages[:-1] + [SystemMessage(content=context_note)] + messages[-1:]

    mark_llm_start()
    t_start = time.perf_counter()
    try:
        # Get the raw LangChain model and bind tools
        model = llm_client.chat_model.bind_tools(TOOLS)

        # Invoke as a Runnable so LangGraph's astream_events can intercept the stream
        response = await model.ainvoke(_clean_messages(messages))

        mark_first_token()
        return {"messages": [response]}
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent failed: %s", exc)
        return {"messages": [AIMessage(content="I encountered an issue processing your request. Please try again.")]}
    finally:
        record_llm_call_duration(int((time.perf_counter() - t_start) * 1000))


async def node_execute_tools(state: ChatState) -> dict[str, Any]:
    tool_node = ToolNode(TOOLS)
    result = await tool_node.ainvoke(state)
    count = state.get("tool_call_count", 0) + 1
    return {**result, "tool_call_count": count}


MAX_TOOL_ITERATIONS = 4

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
    graph.add_node("resolve_entities", node_resolve_entities)
    graph.add_node("agent", node_agent)
    graph.add_node("execute_tools", node_execute_tools)

    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, {
        "resolve_entities": "resolve_entities",
        "chitchat_reply": "chitchat_reply",
        END: END
    })
    
    graph.add_edge("chitchat_reply", END)
    graph.add_edge("resolve_entities", "agent")

    graph.add_conditional_edges("agent", route_after_agent, {
        "execute_tools": "execute_tools",
        END: END
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
) -> AsyncIterator[dict[str, Any]]:
    
    init_observability_context()
    pool = await get_pool()

    await queries.ensure_session(pool, session_id, site_id, page_university_slug, ip_address, user_agent)

    history_result = await queries.get_session_history(pool, session_id, limit=20)
    history_messages: list[BaseMessage] = []
    for msg in history_result.get("messages", []):
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "user":
            history_messages.append(HumanMessage(content=content))
        elif role == "assistant" and content:
            history_messages.append(AIMessage(content=content))

    await queries.insert_message(pool, session_id, "user", message)
    context = await queries.get_session_context(pool, session_id)

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
    
    # REAL TOKEN STREAMING using astream_events
    async for event in _graph.astream_events(initial_state, version="v2"):
        event_kind = event["event"]
        
        # Capture real LLM tokens as they are generated
        if event_kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessage) and chunk.content:
                node_name = event.get("metadata", {}).get("langgraph_node")
                if node_name in ("agent", "chitchat_reply"):
                    reply_text += chunk.content
                    yield {"event": "token", "data": {"text": chunk.content}}
                    
        # Capture the final state updates
        if event_kind == "on_chain_end" and event["name"] == "LangGraph":
            final_state = event["data"]["output"]

    # Fallback if astream_events didn't capture the final state properly or if streaming didn't output text
    if not final_state:
        final_state = await _graph.ainvoke(initial_state)

    if not reply_text:
        if final_state.get("reply"):
            reply_text = final_state["reply"]
        elif final_state.get("messages"):
            last_msg = final_state["messages"][-1]
            if isinstance(last_msg, AIMessage) and not last_msg.tool_calls:
                reply_text = str(last_msg.content)
        
        if reply_text:
            yield {"event": "token", "data": {"text": reply_text}}

    # Handle Cache Hits
    if final_state.get("cache_hit") and not reply_text:
        reply_text = final_state.get("reply", "")
        yield {"event": "token", "data": {"text": reply_text}}

    lead_ask = False
    lead_ask_triggered_by = "Score Engine"

    if not reply_text:
        await log_unanswered(session_id, message, None, None)
        reply_text = (
            "I don't have that detail on file yet — I've logged this so the "
            "DegreeBaba team can fill the gap. Feel free to ask about fees, "
            "eligibility, or available programs."
        )

    # BACKGROUND LEAD SCORING (Non-blocking)
    asyncio.create_task(
        background_lead_scoring(session_id, message, final_state.get("messages", []))
    )

    # Output security scan
    scan = scan_output(reply_text)
    if not scan["clean"]:
        logger.warning("Output scan blocked response (reason=%s) for session=%s", scan["reason"], session_id)
        await queries.insert_flagged_message(pool, session_id, reply_text[:500], f"output_scan:{scan['reason']}")
        reply_text = scan["safe_reply"]

    # Observability stats
    metadata = request_metadata_var.get()
    started_at = metadata["started_at"]
    from datetime import datetime, timezone
    completed_at = datetime.now(timezone.utc)
    
    t_now = time.perf_counter()
    response_time_ms = int((t_now - metadata["t_start"]) * 1000)
    
    t_first = metadata.get("t_first_token") or t_now
    ttft_ms = int((t_first - metadata["t_start"]) * 1000)
    
    tools_executed = tool_metrics_var.get() or []
    tool_exec_time = sum(m.get("duration_ms", 0) for m in tools_executed)

    tool_calls_log = _build_tool_calls_log(final_state.get("messages", []))
    
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

    yield {
        "event": "final",
        "data": {
            "lead_ask": lead_ask,
            "quick_replies": ["Check fees", "Eligibility", "Talk to counsellor"],
            "metrics": {
                "response_time_ms": response_time_ms,
                "ttft_ms": ttft_ms,
                "llm_duration_ms": metadata.get("llm_duration_ms", 0),
                "tool_execution_time_ms": tool_exec_time,
                "input_tokens": metadata["input_tokens"],
                "output_tokens": metadata["output_tokens"],
                "total_tokens": metadata["total_tokens"],
                "estimated_cost_usd": metadata["estimated_cost_usd"],
                "model_name": metadata["model_name"],
            },
        },
    }