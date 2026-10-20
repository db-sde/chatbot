from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio


# Add backend directory and root directory to python path
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir / "backend"))
sys.path.insert(0, str(root_dir))

from db import migrate
from db.pool import close_pool
from ingestion.microapp_to_db import ingest
from agent import tools


@pytest.fixture(scope="module", autouse=True)
def setup_integration_db():
    from urllib.parse import urlparse
    from settings import settings
    test_url = os.getenv("TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL database ending in _test")
    if not urlparse(test_url).path.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must name an isolated database ending in _test")
    original_url = settings.database_url
    settings.database_url = test_url

    import asyncio
    async def _async_setup():
        await migrate.run_migrations()
        fixtures_dir = root_dir / "ingestion" / "fixtures"
        await ingest(fixtures_dir / "sample_university.json", "university")
        await ingest(fixtures_dir / "sample_course.json", "course")
        await ingest(fixtures_dir / "sample_specialization.json", "specialization")
        await close_pool()

    try:
        asyncio.run(_async_setup())
        yield
    finally:
        settings.database_url = original_url


@pytest.mark.asyncio
async def test_integration_get_fee():
    try:
        # NMIMS online-mba is seeded from sample files
        result = await tools.get_fee("nmims", "online-mba")
        assert result.get("slug") == "online-mba"
        assert float(result["total_fee"]) == 220000.0
        assert result["university_name"] == "NMIMS"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_integration_get_eligibility():
    try:
        result = await tools.get_eligibility("nmims", "online-mba")
        assert result.get("slug") == "online-mba"
        assert "Graduation" in result["eligibility_summary"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_integration_list_courses():
    try:
        result = await tools.list_courses(course_type="MBA")
        assert len(result) > 0
        assert result[0]["slug"] == "online-mba"
    finally:
        await close_pool()


@pytest_asyncio.fixture
async def lead_db():
    from uuid import uuid4
    from db import queries
    from db.pool import get_pool
    pool = await get_pool()
    session_id = str(uuid4())
    await queries.ensure_session(pool, session_id, "degreebaba_dev", None)
    try:
        yield pool, session_id
    finally:
        await pool.execute("DELETE FROM leads WHERE session_id=$1::uuid", session_id)
        await pool.execute("DELETE FROM sessions WHERE id=$1::uuid", session_id)
        await close_pool()


@pytest.mark.asyncio
async def test_ingestion_upsert_and_cold_catalog_keep_parent_scope(monkeypatch):
    from agent import resolve
    from db import queries
    from db.pool import get_pool
    try:
        fixture = root_dir / "ingestion/fixtures/sample_course.json"
        await ingest(fixture, "course")
        await ingest(fixture, "course")
        pool = await get_pool()
        rows = await queries.find_entity_search(pool, "course")
        assert rows[0]["university_id"] is not None
        assert rows[0]["slug"] == "online-mba"
        monkeypatch.setattr(resolve, "ENTITY_CACHE", {"university": [], "course": [], "specialization": []})
        assert await resolve.snap_course("MBA", rows[0]["university_id"]) == ("online-mba", rows[0]["entity_id"])
        assert await resolve.snap_course("MBA", -1) == (None, None)
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_callback_without_email_is_saved_and_later_email_updates_it(lead_db, monkeypatch):
    from db import queries
    from settings import settings
    pool, session_id = lead_db
    monkeypatch.setattr(settings, "crm_webhook_url", "https://crm.example.test/leads")
    await queries.save_progressive_lead_field(pool, session_id, "name", "Test Student")
    await queries.save_progressive_lead_field(pool, session_id, "phone", "9999999999")
    row = await pool.fetchrow("SELECT * FROM leads WHERE session_id=$1::uuid", session_id)
    assert row["email"] is None
    assert await pool.fetchval("SELECT count(*) FROM crm_deliveries WHERE lead_id=$1", row["id"]) == 1
    await queries.save_progressive_lead_field(pool, session_id, "email", "student@example.test")
    rows = await pool.fetch("SELECT * FROM leads WHERE session_id=$1::uuid", session_id)
    assert len(rows) == 1
    assert rows[0]["id"] == row["id"]
    assert rows[0]["email"] == "student@example.test"


@pytest.mark.asyncio
async def test_concurrent_contact_saves_and_stale_chat_profile_preserve_fields(lead_db):
    import asyncio
    from db import queries
    pool, session_id = lead_db
    await asyncio.gather(*(
        queries.save_progressive_lead_field(pool, session_id, field, value)
        for field, value in {"name": "Test Student", "phone": "9999999999", "email": "student@example.test"}.items()
    ))
    await queries.update_profile_context(pool, session_id, {"lead": {}, "qualification": {"course_type": "MBA"}}, 2)
    context = await queries.get_session_context(pool, session_id)
    assert context["profile_context"]["lead"] == {"name": "Test Student", "phone": "9999999999", "email": "student@example.test"}
    assert context["profile_context"]["qualification"]["course_type"] == "MBA"
    assert await pool.fetchval("SELECT count(*) FROM leads WHERE session_id=$1::uuid", session_id) == 1


@pytest.mark.asyncio
async def test_retried_full_submission_has_one_lead_and_one_delivery(lead_db, monkeypatch):
    import asyncio
    from uuid import uuid4
    from db import queries
    from settings import settings
    pool, session_id = lead_db
    monkeypatch.setattr(settings, "crm_webhook_url", "https://crm.example.test/leads")
    submission = str(uuid4())
    rows = await asyncio.gather(*(
        queries.insert_lead(pool, session_id, "Test Student", "9999999999", None, "MBA", "widget_form", submission)
        for _ in range(3)
    ))
    assert len({row["id"] for row in rows}) == 1
    assert await pool.fetchval("SELECT count(*) FROM crm_deliveries WHERE lead_id=$1", rows[0]["id"]) == 1
    # A different explicit request in the same session remains a separate lead.
    other = await queries.insert_lead(pool, session_id, "Another Student", "8888888888", None, "BCA", "widget_form", str(uuid4()))
    assert other["id"] != rows[0]["id"]


@pytest.mark.asyncio
async def test_crm_http_failure_retries_with_same_idempotency_key(lead_db, monkeypatch):
    import httpx
    from db import queries
    from leads.delivery import deliver_next
    from settings import settings
    pool, session_id = lead_db
    monkeypatch.setattr(settings, "crm_webhook_url", "https://crm.example.test/leads")
    lead = await queries.insert_lead(pool, session_id, "Test Student", "9999999999", None, "MBA", "test")
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(500 if len(requests) == 1 else 200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await deliver_next(pool, client)
        row = await pool.fetchrow("SELECT * FROM crm_deliveries WHERE lead_id=$1", lead["id"])
        assert row["status"] == "pending"
        assert row["last_status_code"] == 500
        await pool.execute("UPDATE crm_deliveries SET next_attempt_at=now() WHERE id=$1", row["id"])
        assert await deliver_next(pool, client)
    row = await pool.fetchrow("SELECT * FROM crm_deliveries WHERE lead_id=$1", lead["id"])
    assert row["status"] == "delivered"
    assert row["attempts"] == 2
    assert requests[0].headers["Idempotency-Key"] == requests[1].headers["Idempotency-Key"]


@pytest.mark.asyncio
async def test_crm_claims_cannot_send_same_job_concurrently_and_recover_after_restart(lead_db, monkeypatch):
    import asyncio
    import httpx
    from db import queries
    from leads.delivery import deliver_next
    from settings import settings
    pool, session_id = lead_db
    monkeypatch.setattr(settings, "crm_webhook_url", "https://crm.example.test/leads")
    lead = await queries.insert_lead(pool, session_id, "Test Student", "9999999999", None, None, "test")
    started, release = asyncio.Event(), asyncio.Event()
    async def handle(_request):
        started.set()
        await release.wait()
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        first = asyncio.create_task(deliver_next(pool, client))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            assert await deliver_next(pool, client) is False
        finally:
            release.set()
            assert await first
        # Simulate an interrupted process with an expired claim.
        await pool.execute("UPDATE crm_deliveries SET status='processing', locked_at=now()-interval '2 minutes' WHERE lead_id=$1", lead["id"])
        assert await deliver_next(pool, client)
    assert await pool.fetchval("SELECT status FROM crm_deliveries WHERE lead_id=$1", lead["id"]) == "delivered"


@pytest.mark.asyncio
async def test_first_message_flag_is_persisted_with_foreign_key(lead_db):
    import main
    pool, session_id = lead_db
    await pool.execute("DELETE FROM sessions WHERE id=$1::uuid", session_id)
    await main._record_flagged_input(pool, session_id, "synthetic blocked input", site_id="degreebaba_dev", layer="policy", risk_score=0.9, reason="test")
    assert await pool.fetchval("SELECT count(*) FROM flagged_messages WHERE session_id=$1::uuid", session_id) == 1


@pytest.mark.asyncio
async def test_naac_minimum_uses_grade_rank_instead_of_text_order(lead_db):
    from db import queries
    pool, _ = lead_db
    async with pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            university_id = await conn.fetchval("SELECT id FROM universities WHERE slug='nmims'")
            grades = ['D', 'C', 'B', 'B+', 'B++', 'A', 'A+', 'A++']
            for index, grade in enumerate(grades):
                await conn.execute(
                    "INSERT INTO courses(slug,university_id,program_name,naac_grade) VALUES($1,$2,$3,$4)",
                    f"naac-regression-{index}", university_id, "NAAC regression program", grade,
                )
            rows = await queries.list_courses(conn, "NAAC regression", None, None, "A", None, "asc", 20)
            assert {row["naac_grade"] for row in rows} == {"A", "A+", "A++"}
        finally:
            await transaction.rollback()


@pytest.mark.asyncio
async def test_existing_schema_upgrade_adds_columns_before_dependent_indexes(lead_db):
    from db import queries
    pool, session_id = lead_db
    await queries.insert_message(pool, session_id, "user", "Preserve this test message")
    await pool.execute("ALTER TABLE messages DROP COLUMN model_name CASCADE")
    await pool.execute("ALTER TABLE sessions DROP COLUMN lead_intent_detected CASCADE")
    await migrate.run_migrations()
    assert await pool.fetchval("SELECT content FROM messages WHERE session_id=$1::uuid", session_id) == "Preserve this test message"
    assert await pool.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_name='messages' AND column_name='model_name'") == 1
