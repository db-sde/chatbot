from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agent.deterministic import run_deterministic_route
from agent.v2_routes import (
    ROUTE_ACCREDITATION,
    ROUTE_COMPARISON,
    ROUTE_ELIGIBILITY,
    ROUTE_FEE,
    ROUTE_GENERAL,
    ROUTE_PROGRAMS,
    ROUTE_RECOMMENDATION,
    ROUTE_REVIEWS,
    ROUTE_SPECIALIZATIONS,
    context_class_for,
    detect_route,
)


@pytest.mark.parametrize(
    ("message", "route"),
    [
        ("What is the fee?", ROUTE_FEE),
        ("Am I eligible?", ROUTE_ELIGIBILITY),
        ("Show MBA specializations", ROUTE_SPECIALIZATIONS),
        ("Is it UGC approved?", ROUTE_ACCREDITATION),
        ("Show student reviews", ROUTE_REVIEWS),
        ("Ratings & reviews", ROUTE_REVIEWS),
        ("Available programs", ROUTE_PROGRAMS),
        ("Compare NMIMS and Amity", ROUTE_COMPARISON),
        ("Which MBA is best?", ROUTE_RECOMMENDATION),
        ("Can you recommend an online MBA?", ROUTE_RECOMMENDATION),
        ("Fee and eligibility", ROUTE_GENERAL),
    ],
)
def test_v2_route_detection(message, route):
    assert detect_route(message) == route


def test_v2_context_classes_use_minimum_history():
    assert context_class_for("Check fees") == "A"
    assert context_class_for("Compare NMIMS and Amity") == "B"
    assert context_class_for("Which MBA is best?") == "C"


@pytest.mark.asyncio
async def test_deterministic_fee_route_is_grounded_and_structured(monkeypatch):
    from agent import deterministic

    monkeypatch.setattr(deterministic.queries, "get_fee", AsyncMock(return_value={
        "name": "Executive MBA",
        "total_fee": 392000,
        "starting_fee": 58800,
        "emi_amount": "EMI available",
    }))

    async def pool():
        return object()

    result = await run_deterministic_route({
        "raw_message": "Check fees",
        "resolved": {
            "resolution_status": "session_context",
            "university_slug": "nmims-online",
            "course_slug": "executive-mba-nmims-online",
        },
    }, pool)

    assert result["deterministic_route"] == "fee"
    assert "**Total fee:** ₹3,92,000" in result["reply"]
    assert result["progressive_lead_field"] == "name"
    assert result["ui_cards"][0]["type"] == "actions"


@pytest.mark.asyncio
async def test_fee_route_explains_verified_catalog_substitute(monkeypatch):
    from agent import deterministic

    monkeypatch.setattr(deterministic.queries, "get_fee", AsyncMock(return_value={
        "name": "Executive MBA",
        "total_fee": 392000,
        "starting_fee": 58800,
    }))

    async def pool():
        return object()

    result = await run_deterministic_route({
        "raw_message": "What is the NMIMS Online MBA fee?",
        "resolved": {
            "resolution_status": "resolved",
            "university_slug": "nmims-online",
            "course_slug": "executive-mba-nmims-online",
            "raw": {"course_query": "mba"},
        },
    }, pool)

    assert "verified match for your MBA request" in result["reply"]


@pytest.mark.asyncio
async def test_catalog_program_route_uses_course_type_not_entity_slug(monkeypatch):
    from agent import deterministic

    lookup = AsyncMock(return_value=[{
        "program_name": "Online MBA",
        "university_name": "Example University",
        "duration": "2 years",
        "total_fee": 150000,
    }])
    monkeypatch.setattr(deterministic.queries, "list_courses", lookup)

    async def pool():
        return object()

    result = await run_deterministic_route({
        "raw_message": "Online MBA programs",
        "resolved": {
            "resolution_status": "catalog_query",
            "university_slug": None,
            "course_slug": None,
            "mode": "online",
            "raw": {"course_query": "mba"},
        },
    }, pool)

    assert result["deterministic_route"] == "programs"
    assert "Example University" in result["reply"]
    assert lookup.await_args.args[1:3] == ("mba", "online")


@pytest.mark.asyncio
async def test_clarification_only_route_does_not_open_database():
    async def unexpected_pool():
        raise AssertionError("A clarification-only response must not acquire a DB connection")

    result = await run_deterministic_route({
        "raw_message": "Am I eligible?",
        "resolved": {"resolution_status": "none"},
    }, unexpected_pool)

    assert result["deterministic_route"] == "eligibility"
    assert "Select a specific program" in result["reply"]
