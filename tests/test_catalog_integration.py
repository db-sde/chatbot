from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from catalog.schema import CatalogError, CatalogEvent
from catalog.service import enqueue, process_next
from db.pool import close_pool, get_pool
from settings import settings
from test_catalog_sync import SECRET, example_event, signed_headers


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated database ending in _test")
    if not urlparse(url).path.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name an isolated database ending in _test")
    original = settings.database_url
    settings.database_url = url
    from db.migrate import run_migrations
    try:
        asyncio.run(run_migrations())
        yield
    finally:
        settings.database_url = original


@pytest_asyncio.fixture
async def catalog_db(monkeypatch):
    monkeypatch.setattr(settings, "catalog_webhook_secret", SECRET)
    pool = await get_pool()
    prefix = "ct"+uuid4().hex
    def event(kind="university", version=1, **kwargs):
        own_id = prefix+{"university": "u", "course": "c", "specialization": "s"}[kind]
        parents = {} if kind == "university" else {"university_source_id": prefix+"u"}
        if kind == "specialization":
            parents["course_source_id"] = prefix+"c"
        data = {"university": {"university_name": "Catalog Test University"}, "course": {"program_name": "Online MBA"}, "specialization": {"spec_name": "Finance"}}[kind]
        return CatalogEvent.model_validate(example_event(entity_type=kind, source_id=own_id, version=version, source_url=f"https://degreebaba.com/catalog-test/{own_id}/", data=data, **parents) | kwargs)
    try:
        yield pool, event, prefix
    finally:
        mappings = await pool.fetch("SELECT * FROM catalog_sources WHERE source_id LIKE $1", prefix+"%")
        for mapping in mappings:
            await pool.execute("DELETE FROM entity_search WHERE entity_type=$1 AND entity_id=$2", mapping["entity_type"], mapping["entity_id"])
            for table in ("faqs", "reviews", "job_profiles", "highlights"):
                await pool.execute(f"DELETE FROM {table} WHERE entity_type=$1 AND entity_id=$2", mapping["entity_type"], mapping["entity_id"])
        university_ids = [m["entity_id"] for m in mappings if m["entity_type"] == "university"]
        await pool.execute("DELETE FROM catalog_sources WHERE source_id LIKE $1", prefix+"%")
        await pool.execute("DELETE FROM catalog_events WHERE source_id LIKE $1", prefix+"%")
        await pool.execute("DELETE FROM universities WHERE id=ANY($1::int[]) OR slug LIKE $2", university_ids, prefix+"%")
        await close_pool()


async def apply(pool, event):
    await enqueue(pool, event)
    for _ in range(10):
        assert await process_next(pool)
        row = await pool.fetchrow("SELECT * FROM catalog_events WHERE event_id=$1", event.event_id)
        if row["attempts"]:
            return row
    raise AssertionError("Event did not get processed")


@pytest.mark.asyncio
async def test_signed_webhook_through_import_tools_retrieval_and_page_context(catalog_db):
    import main
    from agent import tools
    from agent.page_context import resolve_page_context
    from catalog.retrieval import retrieve_sections
    pool, event, _ = catalog_db
    university = event()
    body = university.model_dump_json().encode()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.post("/webhook/catalog", content=body, headers=signed_headers("POST", "/webhook/catalog", body))
        assert response.status_code == 202
        path = f"/webhook/catalog/{university.event_id}"
        assert (await client.get(path, headers=signed_headers("GET", path))).json()["status"] == "queued"
        await process_next(pool)
        assert (await client.get(path, headers=signed_headers("GET", path))).json()["status"] == "applied"
    uni_slug = await pool.fetchval("SELECT entity_slug FROM catalog_sources WHERE source_id=$1", university.source_id)
    course = event("course", data={"program_name": "Online MBA", "total_fee": "₹1.2 lakh", "eligibility_content": [{"eligibility_title": "Qualification", "eligibility_description": "Graduation"}], "exam_content": "Exams use remotely proctored assessments."})
    row = await apply(pool, course)
    assert row["status"] == "applied"
    fee = await tools.get_fee(uni_slug, row["entity_slug"])
    assert float(fee["total_fee"]) == 120000
    eligibility = await tools.get_eligibility(uni_slug, row["entity_slug"])
    assert "Graduation" in eligibility["eligibility_content"]
    snippets = await retrieve_sections(pool, uni_slug, row["entity_slug"], None, "proctored")
    assert len(snippets) == 1 and "remotely" in snippets[0]["content"]
    assert snippets[0]["source_url"] == str(course.source_url)
    tool_result = await tools.search_page_details_tool.ainvoke({"university_slug": uni_slug, "course_slug": row["entity_slug"], "query_text": "proctored"})
    assert tool_result[0]["source_url"] == str(course.source_url)
    spec = await apply(pool, event("specialization", data={"spec_name": "Finance", "syllabus_content": "Financial analytics and portfolio risk."}))
    assert spec["status"] == "applied"
    spec_sections = await retrieve_sections(pool, uni_slug, row["entity_slug"], spec["entity_slug"], "portfolio")
    assert len(spec_sections) == 1
    assert await retrieve_sections(pool, uni_slug, "wrong-course", spec["entity_slug"], "portfolio") == []
    assert await retrieve_sections(pool, "wrong-parent", row["entity_slug"], None, "proctored") == []
    context = await resolve_page_context(urlparse(str(course.source_url)).path, pool)
    assert context["page_course_slug"] == row["entity_slug"] and context["page_university_slug"] == uni_slug


@pytest.mark.asyncio
async def test_duplicates_conflicts_and_older_versions_cannot_overwrite(catalog_db):
    pool, event, _ = catalog_db
    current = event(version=2, data={"university_name": "New name"})
    row = await apply(pool, current)
    assert row["status"] == "applied"
    status, created = await enqueue(pool, current)
    assert not created and status["status"] == "applied"
    for changed in [current.model_copy(update={"data": {"university_name": "Conflicting"}}), current.model_copy(update={"event_id": uuid4()})]:
        with pytest.raises(CatalogError, match="event_or_version_conflict"):
            await enqueue(pool, changed)
    older = await apply(pool, event(version=1, data={"university_name": "Old name"}))
    assert older["status"] == "ignored"
    assert await pool.fetchval("SELECT name FROM universities WHERE slug=$1", row["entity_slug"]) == "New name"


@pytest.mark.asyncio
async def test_empty_fields_preserve_details_and_explicit_clear_removes_them(catalog_db):
    pool, event, _ = catalog_db
    initial = await apply(pool, event(data={"university_name": "Test", "about_content": "Old description", "starting_fee": "₹20,000", "faqs": [{"question": "Q", "answer": "A"}]}))
    slug = initial["entity_slug"]
    updated = await apply(pool, event(version=2, data={"university_name": "Renamed", "about_content": None, "starting_fee": None, "faqs": []}))
    assert updated["status"] == "applied"
    row = await pool.fetchrow("SELECT * FROM universities WHERE slug=$1", slug)
    assert row["about_content"] == "Old description" and float(row["starting_fee"]) == 20000
    assert await pool.fetchval("SELECT count(*) FROM faqs WHERE entity_type='university' AND entity_id=$1", row["id"]) == 1
    assert (await apply(pool, event(version=3, data={}, clear_fields=["about_content", "faqs"])))["status"] == "applied"
    assert await pool.fetchval("SELECT about_content FROM universities WHERE slug=$1", slug) is None
    assert await pool.fetchval("SELECT count(*) FROM faqs WHERE entity_type='university' AND entity_id=$1", row["id"]) == 0


@pytest.mark.asyncio
async def test_out_of_order_parent_retries_and_concurrent_workers_import_once(catalog_db):
    pool, event, _ = catalog_db
    child = event("course")
    row = await apply(pool, child)
    assert row["status"] == "queued" and row["last_error"] == "parent_university_not_synced"
    assert (await apply(pool, event()))["status"] == "applied"
    await pool.execute("UPDATE catalog_events SET next_attempt_at=now() WHERE event_id=$1", child.event_id)
    await asyncio.gather(process_next(pool), process_next(pool), process_next(pool))
    row = await pool.fetchrow("SELECT * FROM catalog_events WHERE event_id=$1", child.event_id)
    assert row["status"] == "applied" and row["attempts"] == 2
    assert await pool.fetchval("SELECT count(*) FROM catalog_sources WHERE source_id=$1", child.source_id) == 1


@pytest.mark.asyncio
async def test_failed_update_rolls_back_catalog_and_can_be_retried(catalog_db):
    import main
    pool, event, _ = catalog_db
    initial = await apply(pool, event(data={"university_name": "Keep name", "about_content": "Keep content"}))
    invalid = event(version=2, data={"university_name": "Bad update", "faqs": [{"question": "No answer"}]})
    failed = await apply(pool, invalid)
    assert failed["status"] == "failed" and failed["last_error"] == "incomplete_faq"
    assert await pool.fetchval("SELECT name FROM universities WHERE slug=$1", initial["entity_slug"]) == "Keep name"
    monkeypatch_token = settings.admin_auth_token
    settings.admin_auth_token = "catalog-test-admin-token"
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.post(f"/api/admin/catalog/events/{invalid.event_id}/retry", headers={"Authorization": "Bearer catalog-test-admin-token"})
            assert response.status_code == 200 and response.json()["status"] == "queued"
        # Corrected data gets a new version/event, never mutates an old receipt.
        assert (await apply(pool, event(version=3, data={"university_name": "Corrected"})))["status"] == "applied"
    finally:
        settings.admin_auth_token = monkeypatch_token


@pytest.mark.asyncio
async def test_reviewed_existing_row_adoption_preserves_database_children(catalog_db):
    from catalog.importer import upsert_university
    pool, event, prefix = catalog_db
    slug = prefix+"-legacy"
    async with pool.acquire() as conn:
        async with conn.transaction():
            _, uni_id = await upsert_university(conn, {"slug": slug, "name": "Legacy", "starting_fee": "₹15,000"})
            await conn.execute("UPDATE universities SET raw_json=NULL WHERE id=$1", uni_id)
            await conn.execute("INSERT INTO faqs(entity_type,entity_id,question,answer) VALUES('university',$1,'Legacy Q','Legacy A')", uni_id)
    adopted = await apply(pool, event(catalog_slug=slug))
    assert adopted["status"] == "applied" and adopted["entity_slug"] == slug
    assert await pool.fetchval("SELECT count(*) FROM universities WHERE slug=$1", slug) == 1
    assert await pool.fetchval("SELECT answer FROM faqs WHERE entity_type='university' AND entity_id=$1", uni_id) == "Legacy A"
    assert float(await pool.fetchval("SELECT starting_fee FROM universities WHERE id=$1", uni_id)) == 15000


@pytest.mark.asyncio
async def test_parent_mismatch_and_url_collision_do_not_modify_existing_rows(catalog_db):
    pool, event, prefix = catalog_db
    uni = event()
    await apply(pool, uni)
    await apply(pool, event("course"))
    other = event(source_id=prefix+"other", source_url=f"https://degreebaba.com/catalog-test/{prefix}other/", data={"university_name": "Other"})
    await apply(pool, other)
    wrong = await apply(pool, event("specialization", university_source_id=other.source_id))
    assert wrong["status"] == "failed" and wrong["last_error"] == "course_university_mismatch"
    changed = await apply(pool, event("course", version=2, university_source_id=other.source_id))
    assert changed["status"] == "failed" and changed["last_error"] == "cannot_reparent_existing_entity"
    collision = await apply(pool, event(version=2, source_url=str(other.source_url), data={"university_name": "Must roll back"}))
    assert collision["status"] == "failed" and collision["last_error"] == "source_path_already_linked"
    assert await pool.fetchval("SELECT name FROM universities u JOIN catalog_sources cs ON cs.entity_id=u.id AND cs.entity_type='university' WHERE cs.source_id=$1", uni.source_id) == "Catalog Test University"
