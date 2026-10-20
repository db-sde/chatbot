from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from catalog.adapter import adapt_data, build_sections, plain_text
from catalog.schema import CatalogError, CatalogEvent

SECRET = "catalog-test-secret-not-a-real-secret-123456"


def example_event(**overrides):
    return {
        "schema_version": 1, "event_id": str(uuid4()), "source": "degreebaba-parser",
        "entity_type": "university", "source_id": "101", "version": 1,
        "publication_status": "publish", "source_url": "https://degreebaba.com/colleges/test/",
        "data": {"university_name": "Test University"}, **overrides,
    }


def signed_headers(method, path, body=b"", timestamp=None):
    timestamp = str(timestamp or int(time.time()))
    message = f"{timestamp}.{method}.{path}.".encode() + body
    return {"Content-Type": "application/json", "X-Catalog-Timestamp": timestamp,
            "X-Catalog-Signature": "sha256=" + hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()}


def test_acf_normalization_preserves_gaps_and_maps_eligibility():
    original = {"name": "Old", "about_content": "Existing", "faqs": [{"question": "Q", "answer": "A"}]}
    result, warnings = adapt_data("university", {"university_name": "New", "university_full_name": "New Full", "faqs": [], "about_content": None}, original, [])
    assert result == {**original, "name": "New", "full_name": "New Full"}
    assert original["name"] == "Old"
    assert warnings == []
    course, _ = adapt_data("course", {"program_name": "MBA", "university_name": "Parent", "eligibility_content": [{"eligibility_title": "Qualification", "eligibility_description": "Graduation"}]}, {}, [])
    assert "Graduation" in course["eligibility_content"]
    assert "name" not in course


def test_clear_fields_are_explicit_and_protected():
    result, _ = adapt_data("university", {}, {"name": "Test", "about_content": "Old", "faqs": [{"question": "Q", "answer": "A"}]}, ["about_content", "faqs"])
    assert result["about_content"] is None and result["faqs"] == []
    for field in ["slug", "name", "linked_university", "_meta"]:
        with pytest.raises(CatalogError):
            adapt_data("university", {}, {"name": "Test"}, [field])


def test_ambiguous_fee_is_not_promoted_to_a_total():
    result, warnings = adapt_data("course", {"total_fee": "₹20,000 per semester", "starting_fee": "₹1.2 lakh"}, {"program_name": "MBA", "total_fee": 100000}, [])
    assert result["total_fee"] == 100000
    assert result["starting_fee"] == 120000
    assert result["total_fee_source_text"] == "₹20,000 per semester"
    assert warnings == ["unparsed_total_fee"]


def test_invalid_repeater_cannot_partially_replace_saved_faqs():
    with pytest.raises(CatalogError, match="incomplete_faq"):
        adapt_data("university", {"faqs": [{"question": "Q"}]}, {"name": "Test"}, [])


def test_sections_strip_markup_and_scripts_and_bound_each_excerpt():
    assert plain_text("<p>Hello</p><script>steal()</script><style>secret</style>world") == "Hello world"
    sections = build_sections({"about_content": "a"*5000, "hero_image": "https://example.test/image", "slug": "test"})
    assert len(sections) == 4
    assert max(len(content) for _, content in sections) <= 1600
    assert {title for title, _ in sections} == {"about content"}


@pytest.mark.parametrize("overrides", [
    {"publication_status": "draft"}, {"schema_version": 2}, {"version": True}, {"data": {"starting_fee": float("nan")}},
    {"entity_type": "course"}, {"source_url": "http://degreebaba.com/test"},
    {"source_url": "https://user:password@degreebaba.com/test"},
    {"source_url": "https://degreebaba.com/test?secret=123"}, {"unknown": "field"},
])
def test_protocol_rejects_unsupported_or_unsafe_events(overrides):
    with pytest.raises(ValidationError):
        CatalogEvent.model_validate(example_event(**overrides))


@pytest.mark.asyncio
async def test_endpoint_authentication_and_durable_acknowledgement(monkeypatch):
    import main
    from catalog import routes
    monkeypatch.setattr(routes.settings, "catalog_webhook_secret", SECRET)
    async def pool():
        return object()
    calls = []
    async def enqueue(_pool, event):
        calls.append(event)
        return {"event_id": str(event.event_id), "status": "queued"}, True
    monkeypatch.setattr(routes, "get_pool", pool)
    monkeypatch.setattr(routes, "enqueue", enqueue)
    body = json.dumps(example_event(data={"university_name": "Université Test"}), ensure_ascii=False).encode()
    path = "/webhook/catalog"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        assert (await client.post(path, content=body)).status_code == 401
        assert (await client.post(path, content=body, headers=signed_headers("POST", path, body, int(time.time())-400))).status_code == 401
        assert (await client.post(path, content=body+b" ", headers=signed_headers("POST", path, body))).status_code == 401
        assert (await client.post(path, content=body, headers=signed_headers("GET", path, body))).status_code == 401
        response = await client.post(path, content=body, headers=signed_headers("POST", path, body))
        assert response.status_code == 202 and response.json()["status"] == "queued"
        assert len(calls) == 1
        bad = json.dumps(example_event(source_url="https://unrelated.example/test")).encode()
        assert (await client.post(path, content=bad, headers=signed_headers("POST", path, bad))).status_code == 422
        assert (await client.post(path, content=b"x"*(routes.MAX_BODY_BYTES+1))).status_code == 413
        monkeypatch.setattr(routes.settings, "catalog_webhook_secret", None)
        assert (await client.post(path, content=body)).status_code == 503


@pytest.mark.asyncio
async def test_admin_sync_controls_require_authentication(monkeypatch):
    import main
    from settings import settings
    monkeypatch.setattr(settings, "admin_auth_token", "real-test-admin-token")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        assert (await client.get("/api/admin/catalog/events")).status_code == 401
        assert (await client.post(f"/api/admin/catalog/events/{uuid4()}/retry")).status_code == 401


def test_partial_update_preserves_html_and_decimal_fees():
    from decimal import Decimal
    result, _ = adapt_data("university", {}, {"name": "Test", "about_content": "<p>Original <b>content</b></p>", "starting_fee": Decimal("2E+4")}, [])
    assert result["about_content"] == "<p>Original <b>content</b></p>"
    assert result["starting_fee"] == 20000


# --- Parser fee format -----------------------------------------------------
# The parser's source documents write whole amounts as "INR 1,00,000 /-". That
# trailing "/-" used to make the importer treat every such fee as unparseable,
# leaving the numeric total/starting fee empty so fee and budget tools had no value.

import pytest as _pytest


@_pytest.mark.parametrize("text,expected", [
    ("INR 1,00,000 /-", 100000), ("INR 1,75,000 /-", 175000), ("INR 5,725 /-", 5725),
    ("INR 1,00,000/-", 100000), ("Rs. 90,000 /-", 90000), ("₹1,20,000 /-", 120000),
    ("₹1,20,000", 120000), ("1.5 lakh /-", 150000),
])
def test_parser_style_rupee_suffix_is_a_whole_amount(text, expected):
    result, warnings = adapt_data("course", {"program_name": "MBA", "total_fee": text}, {}, [])
    assert result["total_fee"] == expected
    assert warnings == []
    assert "total_fee_source_text" not in result


@_pytest.mark.parametrize("text", [
    "INR 25,000 /- Semester", "INR 25,000 per semester", "₹20,000 per month",
    "INR 90,000 - INR 1,20,000", "Starting from INR 25,000 /- per semester",
])
def test_per_period_and_range_fees_still_are_not_guessed_into_a_total(text):
    result, warnings = adapt_data("course", {"program_name": "MBA", "total_fee": text}, {}, [])
    assert result.get("total_fee") is None
    assert warnings == ["unparsed_total_fee"]
    assert result["total_fee_source_text"] == text


def test_rupee_suffix_does_not_change_conversational_budget_extraction():
    from agent.resolve import _local_extract
    for phrase in ("under INR 2,00,000 /-", "below ₹2 lakh", "maximum budget 200k"):
        assert _local_extract(f"MBA {phrase}")["max_fee"] == 200000
