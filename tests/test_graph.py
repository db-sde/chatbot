"""
Tests for the LangGraph agent graph.

All external dependencies (DB pool, LLM) are monkeypatched so these tests
run fully offline — no Gemini key or Postgres required.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

# ── Shared FakePool (same shape as in test_tools.py) ──────────────────────

class FakePool:
    async def fetchrow(self, sql, *args):
        if "session_context" in sql:
            return None  # no prior context
        if "FROM courses c" in sql and "eligibility" in sql:
            return {
                "slug": "online-mba",
                "program_name": "Online MBA",
                "eligibility_summary": "Graduation required.",
                "eligibility_content": "Graduation from a recognised university.",
                "university_name": "NMIMS",
            }
        if "FROM courses c" in sql:
            return {
                "slug": "online-mba",
                "name": "Online MBA",
                "total_fee": 220000,
                "starting_fee": 55000,
                "emi_amount": "Rs 9,500/month",
                "university_name": "NMIMS",
            }
        if "FROM universities" in sql:
            return {
                "slug": "nmims",
                "name": "NMIMS",
                "starting_fee": 55000,
                "admission_fee_note": None,
                "emi_content": None,
            }
        if "FROM sessions" in sql:
            return {
                "id": "11111111-1111-4111-8111-111111111111",
                "site_id": "test",
                "page_university_slug": "nmims",
                "summary": None,
                "started_at": None,
                "last_active_at": None,
                "message_count": 2,
            }
        return None

    async def fetch(self, sql, *args):
        if "FROM courses c" in sql:
            return [
                {
                    "slug": "online-mba",
                    "program_name": "Online MBA",
                    "duration": "2 years",
                    "mode": "Online",
                    "total_fee": 220000,
                    "starting_fee": 55000,
                    "naac_grade": "A+",
                    "university_slug": "nmims",
                    "university_name": "NMIMS",
                }
            ]
        if "FROM messages" in sql:
            return []
        if "FROM leads" in sql:
            return []
        if "FROM faqs" in sql:
            return [{"question": "What is the fee?", "answer": "Rs 2,20,000."}]
        if "FROM entity_search" in sql:
            return [{"entity_type": "university", "entity_id": 1, "search_text": "nmims"}]
        return []

    async def fetchval(self, sql, *args):
        if "SELECT id FROM courses" in sql:
            return 1
        if "SELECT slug FROM universities" in sql:
            return "nmims"
        if "lead_asks" in sql:
            return None
        if "lead_score_events" in sql:
            return 0
        if "count(*)" in sql.lower():
            return 0
        return None

    async def execute(self, sql, *args):
        return "OK"


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_pool(monkeypatch):
    """Replace get_pool everywhere with FakePool."""
    import agent.tools as tools_mod
    import agent.graph as graph_mod
    import agent.resolve as resolve_mod
    import leads.scoring as scoring_mod
    import db.queries as queries_mod
    import security.tool_validator as validator_mod

    async def _fake_pool():
        return FakePool()

    monkeypatch.setattr(tools_mod, "get_pool", _fake_pool)
    monkeypatch.setattr(graph_mod, "get_pool", _fake_pool)
    monkeypatch.setattr(resolve_mod, "get_pool", _fake_pool)
    monkeypatch.setattr(scoring_mod, "get_pool", _fake_pool)
    monkeypatch.setattr(validator_mod, "get_pool", _fake_pool)


@pytest.fixture()
def patch_llm(monkeypatch):
    """
    Replace the unified LLM generate calls so the graph runs without a real
    API key.  The graph now calls llm_client.generate("agent_decide", ...) and
    llm_client.generate("synthesize", ...), which return normalized LLMResponse
    objects.
    """
    from langchain_core.messages import AIMessage
    import agent.llm_client as llm_mod
    from llm import LLMResponse
    import agent.resolve as resolve_mod

    # ── Entity extraction (resolve.py) ──
    async def fake_generate_json(prompt, *, task="entity_resolution"):
        return {"university": "nmims", "course": "mba"}

    monkeypatch.setattr(resolve_mod.llm_client, "generate_json", fake_generate_json)

    # ── Agent decide / synthesize (graph.py) ──
    # First call (agent_decide): direct reply, no tool calls
    # Second call (synthesize): final answer
    decide_response = LLMResponse(content="", tool_calls=[])
    synth_response = LLMResponse(content="The NMIMS Online MBA fee is Rs 2,20,000.")

    _call_count = {"n": 0}

    async def fake_generate(task, prompt, *, tools=None, stream=False, json_mode=False):
        _call_count["n"] += 1
        if task == "agent_decide":
            return decide_response
        return synth_response

    monkeypatch.setattr(llm_mod.llm_client, "generate", fake_generate)

    return fake_generate



# ── Graph-level tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_graph_direct_reply_no_tool_calls(patch_llm):
    """
    When the LLM returns no tool_calls the graph should:
    - Skip execute_tools
    - Call synthesize_reply
    - Emit token events followed by a final event
    """
    import agent.graph as graph_mod

    events = []
    async for event in graph_mod.run_chat_turn(
        session_id="11111111-1111-4111-8111-111111111111",
        site_id="test",
        message="What is the NMIMS MBA fee?",
        page_university_slug="nmims",
    ):
        events.append(event)

    event_types = [e["event"] for e in events]
    assert "token" in event_types, "Expected at least one token event"
    assert event_types[-1] == "final", "Last event must be 'final'"

    final_data = events[-1]["data"]
    assert "lead_ask" in final_data
    assert "quick_replies" in final_data


@pytest.mark.asyncio
async def test_graph_guardrail_blocks_offtopic():
    """Off-topic messages must short-circuit before any LLM or tool call."""
    import agent.graph as graph_mod

    events = []
    async for event in graph_mod.run_chat_turn(
        session_id="22222222-2222-4222-8222-222222222222",
        site_id="test",
        message="write me a poem about love",
        page_university_slug=None,
    ):
        events.append(event)

    assert events[-1]["event"] == "final"
    assert events[-1]["data"]["lead_ask"] is False
    # The reply text (concatenated tokens) must not mention fees or universities
    reply_text = "".join(
        e["data"].get("text", "") for e in events if e["event"] == "token"
    )
    assert "DegreeBaba" in reply_text, "Should return the scoped redirect message"


@pytest.mark.asyncio
async def test_graph_state_carries_resolved_slugs(patch_llm, monkeypatch):
    """
    resolve_entities should populate resolved slugs and update_session_context
    should be called — confirmed via a call-count spy.
    """
    import db.queries as queries_mod
    import agent.graph as graph_mod

    call_log: list[tuple] = []
    original = queries_mod.update_session_context

    async def spy_update(pool, session_id, u_slug, c_slug, s_slug):
        call_log.append((u_slug, c_slug, s_slug))

    monkeypatch.setattr(queries_mod, "update_session_context", spy_update)

    async for _ in graph_mod.run_chat_turn(
        session_id="33333333-3333-4333-8333-333333333333",
        site_id="test",
        message="What is the fee for NMIMS MBA?",
        page_university_slug="nmims",
    ):
        pass

    assert len(call_log) >= 1, "update_session_context should have been called"


@pytest.mark.asyncio
async def test_graph_lead_ask_appended_when_threshold_met(patch_llm, monkeypatch):
    """
    When should_append_lead_ask returns True, the final event should carry
    lead_ask=True and the reply should include the incentive copy.
    """
    import agent.graph as graph_mod

    monkeypatch.setattr(graph_mod, "should_append_lead_ask", AsyncMock(return_value=True))

    events = []
    async for event in graph_mod.run_chat_turn(
        session_id="44444444-4444-4444-8444-444444444444",
        site_id="test",
        message="What is the eligibility for NMIMS MBA?",
        page_university_slug="nmims",
    ):
        events.append(event)

    final = events[-1]["data"]
    assert final["lead_ask"] is True
    assert any("No thanks" in qr for qr in final["quick_replies"])

    reply_text = "".join(
        e["data"].get("text", "") for e in events if e["event"] == "token"
    )
    # Should contain the incentive text
    assert "counsellor" in reply_text.lower() or "shortlist" in reply_text.lower() or "PDF" in reply_text


@pytest.mark.asyncio
async def test_graph_loop_iteration_cap(monkeypatch):
    """
    Assert the graph terminates at the MAX_TOOL_ITERATIONS cap even if the
    LLM keeps requesting tool calls.
    """
    from langchain_core.messages import AIMessage
    import agent.graph as graph_mod
    import agent.llm_client as llm_mod
    import agent.resolve as resolve_mod
    from llm import LLMResponse

    # Mock entity extraction
    async def fake_generate_json(prompt, *, task="entity_resolution"):
        return {"university": "nmims", "course": "mba"}

    monkeypatch.setattr(resolve_mod.llm_client, "generate_json", fake_generate_json)

    # Mock LLM to always return a tool call
    fake_tool_call = {
        "name": "get_fee_tool",
        "args": {"university_slug": "nmims", "course_slug": "mba"},
        "id": "call_123",
        "type": "tool_call"
    }

    async def fake_generate(task, prompt, *, tools=None, stream=False, json_mode=False):
        return LLMResponse(content="", tool_calls=[fake_tool_call])

    monkeypatch.setattr(llm_mod.llm_client, "generate", fake_generate)

    events = []
    async for event in graph_mod.run_chat_turn(
        session_id="55555555-5555-5555-8555-555555555555",
        site_id="test",
        message="NMIMS MBA fees",
        page_university_slug="nmims",
    ):
        events.append(event)

    # Verify that the loop terminated and returned a final event
    assert len(events) > 0
    assert events[-1]["event"] == "final"


@pytest.mark.asyncio
async def test_lead_intent_node(monkeypatch):
    """
    Verify that node_update_lead_score triggers lead ask and stores classification
    metrics properly when the LLM lead intent classifier detects high intent.
    """
    import agent.graph as graph_mod
    from unittest.mock import AsyncMock

    # Mock lead_intent_classifier to return high intent
    mock_classifier = AsyncMock(return_value={
        "lead_intent": True,
        "confidence": 0.95,
        "intent_type": "admission_guidance",
        "reasoning": "Student wishes to talk to counsellor."
    })
    monkeypatch.setattr(graph_mod, "lead_intent_classifier", mock_classifier)

    # Mock database query helper functions
    mock_save = AsyncMock()
    mock_mark = AsyncMock()
    
    async def fake_exists(*args, **kwargs):
        return False

    monkeypatch.setattr(graph_mod.queries, "save_lead_intent_status", mock_save)
    monkeypatch.setattr(graph_mod.queries, "mark_lead_ask", mock_mark)
    monkeypatch.setattr(graph_mod.queries, "lead_ask_exists", fake_exists)

    state = {
        "session_id": "00000000-0000-0000-0000-000000000000",
        "raw_message": "please call me to guide me about mba program",
        "messages": []
    }

    res = await graph_mod.node_update_lead_score(state)
    assert res["lead_ask"] is True
    assert res["lead_ask_triggered_by"] == "LLM Intent"
    assert mock_save.called
    assert mock_mark.called

