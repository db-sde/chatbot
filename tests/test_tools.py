from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from agent import tools


class FakePool:
    async def fetchrow(self, sql, *args):
        if "FROM courses c" in sql and "eligibility" in sql:
            return {
                "slug": "online-mba",
                "program_name": "Online MBA",
                "eligibility_summary": "Graduation from a recognized university is required.",
                "eligibility_content": "Graduation from a recognized university with minimum marks.",
                "university_name": "NMIMS",
            }
        if "FROM courses c" in sql:
            return {
                "slug": "online-mba",
                "name": "Online MBA",
                "total_fee": 220000,
                "starting_fee": 55000,
                "emi_amount": "EMI starts around Rs 9,500 per month",
                "university_name": "NMIMS",
            }
        if "FROM universities" in sql:
            return {"slug": "nmims", "name": "NMIMS", "starting_fee": 55000, "admission_fee_note": None, "emi_content": None}
        return None

    async def fetch(self, sql, *args):
        if "FROM reviews" in sql:
            return [{
                "review_text": "Helpful support.",
                "reviewer_name": "Student",
                "reviewer_label": "Learner",
            }]
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
        if "FROM faqs" in sql:
            return [{"question": "What is the fee?", "answer": "The total fee is Rs 2,20,000."}]
        return []

    async def fetchval(self, sql, *args):
        if "SELECT id FROM courses" in sql:
            return 1
        return None

    async def execute(self, sql, *args):
        return "INSERT 0 1"


@pytest.fixture(autouse=True)
def fake_pool(monkeypatch):
    async def _get_pool():
        return FakePool()

    monkeypatch.setattr(tools, "get_pool", _get_pool)


@pytest.mark.asyncio
async def test_get_fee_for_course():
    result = await tools.get_fee("nmims", "online-mba")
    assert result["total_fee"] == 220000
    assert result["university_name"] == "NMIMS"


@pytest.mark.asyncio
async def test_get_eligibility():
    result = await tools.get_eligibility("nmims", "online-mba")
    assert "Graduation" in result["eligibility_summary"]


@pytest.mark.asyncio
async def test_list_courses():
    result = await tools.list_courses(course_type="MBA", mode="Online", sort_by="fee")
    assert result[0]["slug"] == "online-mba"


@pytest.mark.asyncio
async def test_get_faq():
    result = await tools.get_faq("course", "online-mba", "fee")
    assert result[0]["question"] == "What is the fee?"


@pytest.mark.asyncio
async def test_get_reviews():
    result = await tools.get_reviews("university", "nmims")
    assert result[0]["review_text"] == "Helpful support."


@pytest.mark.asyncio
async def test_list_courses_passes_specialization_filter(monkeypatch):
    from db import queries

    query = AsyncMock(return_value=[])
    monkeypatch.setattr(queries, "list_courses", query)
    await tools.list_courses(
        course_type="mba",
        mode="online",
        max_fee=200000,
        specialization_query="finance",
    )

    assert query.await_args.args[-1] == "finance"
