from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


@pytest.mark.asyncio
async def test_prompt_guard_overlaps_independent_db_prechecks(monkeypatch):
    import main

    guard_started = asyncio.Event()
    release_guard = asyncio.Event()
    overlap_observed = False

    async def guard(_message, _session_id):
        guard_started.set()
        await release_guard.wait()
        return {
            "safe": True,
            "risk_score": 0.0,
            "risk_level": "benign",
            "reason": None,
            "source": "prompt_guard_2",
            "details": {},
        }

    async def is_ip_blocked(_pool, _ip):
        nonlocal overlap_observed
        await guard_started.wait()
        overlap_observed = True
        release_guard.set()
        return False

    async def count_messages(_pool, _site):
        await asyncio.sleep(0)
        return 0

    async def graph_turn(**_kwargs):
        yield {"event": "token", "data": {"text": "Done"}}
        yield {"event": "final", "data": {"lead_ask": False, "quick_replies": [], "metrics": {}}}

    async def pool():
        return object()

    monkeypatch.setattr(main, "check_prompt_safety", guard)
    monkeypatch.setattr(main, "check_policy", lambda _message: {"passed": True, "rule": None})
    monkeypatch.setattr(main, "validate_site_request", lambda *_args: None)
    monkeypatch.setattr(main, "get_pool", pool)
    monkeypatch.setattr(main.queries, "is_ip_blocked", is_ip_blocked)
    monkeypatch.setattr(main.queries, "count_site_messages_today", count_messages)
    monkeypatch.setattr(main, "run_chat_turn", graph_turn)

    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"origin": "http://localhost"},
    )
    body = main.ChatRequest(
        session_id="11111111-1111-4111-8111-111111111111",
        site_key="test",
        message="What is the MBA fee?",
    )

    response = await main.chat.__wrapped__(request, body)
    _ = [chunk async for chunk in response.body_iterator]

    assert overlap_observed is True
