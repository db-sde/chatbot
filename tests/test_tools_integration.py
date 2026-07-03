from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Configure database URL for test database
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5433/degreebaba_ai_test"

# Add backend directory and root directory to python path
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir / "backend"))
sys.path.insert(0, str(root_dir))

from db import migrate
from db.pool import get_pool, close_pool
from ingestion.microapp_to_db import ingest
from agent import tools


@pytest.fixture(scope="module", autouse=True)
def setup_integration_db():
    # Only run if test-db on 5433 is reachable
    import socket
    try:
        s = socket.create_connection(("localhost", 5433), timeout=2)
        s.close()
    except (ConnectionRefusedError, socket.timeout):
        pytest.skip("Test database on port 5433 is not running. Skipping integration tests.")

    import asyncio
    async def _async_setup():
        await migrate.run_migrations()
        fixtures_dir = root_dir / "ingestion" / "fixtures"
        await ingest(fixtures_dir / "sample_university.json", "university")
        await ingest(fixtures_dir / "sample_course.json", "course")
        await ingest(fixtures_dir / "sample_specialization.json", "specialization")
        await close_pool()

    asyncio.run(_async_setup())


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
