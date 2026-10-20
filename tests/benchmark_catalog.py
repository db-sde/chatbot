"""Manual local benchmark. Uses only an explicitly supplied disposable *_test DB.
No LLM, WordPress or parser requests. Removes only its own synthetic catalog rows.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from catalog.retrieval import retrieve_sections
from catalog.schema import CatalogEvent
from catalog.service import enqueue, process_next
from db import queries
from db.migrate import run_migrations
from db.pool import close_pool, get_pool
from settings import settings


def percentile(values, fraction):
    return round(sorted(values)[int((len(values)-1)*fraction)], 2)


async def main():
    url = os.environ["TEST_DATABASE_URL"]
    if not urlparse(url).path.endswith("_test"):
        raise ValueError("Disposable *_test database required")
    settings.database_url = url
    await run_migrations()
    pool = await get_pool()
    prefix = "bench"+uuid4().hex
    events = []
    try:
        for i in range(800):
            kind = "university" if i == 0 else "course"
            data = {"university_name": "Benchmark University"} if i == 0 else {"program_name": f"Benchmark MBA {i}", "total_fee": "₹1,20,000"}
            data.update({
                "about_content": "Flexible online learning with recorded lectures and live tutorials. "*20,
                "syllabus_content": "Statistics, finance, marketing, analytics, research methods and project work. "*20,
                "exam_content": "Remotely proctored examinations with semester assessments and assignments. "*20,
                "placement_content": "Career support includes resume preparation and interview practice. "*20,
                "eligibility_content": "Graduation from a recognized university.",
                "admission_steps": "Apply online, upload documents, verify eligibility and pay admission fees.",
            })
            payload = {"schema_version": 1, "event_id": str(uuid4()), "source": "degreebaba-parser", "entity_type": kind, "source_id": prefix+str(i), "version": 1, "publication_status": "publish", "source_url": f"https://degreebaba.com/catalog-benchmark/{prefix}/{i}/", "data": data}
            if i:
                payload["university_source_id"] = prefix+"0"
            events.append(CatalogEvent.model_validate(payload))
        started = time.perf_counter()
        for event in events:
            await enqueue(pool, event)
        for _ in events:
            assert await process_next(pool)
        import_seconds = time.perf_counter()-started
        assert await pool.fetchval("SELECT count(*) FROM catalog_events WHERE source_id LIKE $1 AND status='applied'", prefix+"%") == 800
        uni_slug = await pool.fetchval("SELECT entity_slug FROM catalog_sources WHERE source_id=$1", prefix+"0")
        course_slugs = [r["entity_slug"] for r in await pool.fetch("SELECT entity_slug FROM catalog_sources WHERE source_id LIKE $1 AND entity_type='course' ORDER BY source_id", prefix+"%")]

        async def probes(count=300):
            semaphore = asyncio.Semaphore(5)
            async def probe(i):
                async with semaphore:
                    start = time.perf_counter()
                    course_slug = course_slugs[i % len(course_slugs)]
                    fee = await queries.get_fee(pool, uni_slug, course_slug, None)
                    excerpts = await retrieve_sections(pool, uni_slug, course_slug, None, "proctored")
                    assert fee and excerpts
                    return (time.perf_counter()-start)*1000
            times = await asyncio.gather(*(probe(i) for i in range(count)))
            return {"requests": count, "concurrency": 5, "p50_ms": round(statistics.median(times), 2), "p95_ms": percentile(times, .95), "max_ms": round(max(times), 2)}

        await probes(20)  # warm connections/query plans
        baseline = await probes()
        for event in events[1:101]:
            await enqueue(pool, event.model_copy(update={"event_id": uuid4(), "version": 2}))
        async def imports():
            for _ in range(100):
                assert await process_next(pool)
        _, during = await asyncio.gather(imports(), probes())
        section_count = await pool.fetchval("SELECT count(*) FROM catalog_sections WHERE source_id LIKE $1", prefix+"%")
        print(json.dumps({"dataset_pages": 800, "indexed_sections": section_count, "initial_enqueue_and_import_seconds": round(import_seconds, 2), "read_workload": "One existing fee lookup plus one scoped full-text retrieval per probe; no HTTP, resolver or LLM", "without_imports": baseline, "during_100_updates": during}, indent=2))
    finally:
        mappings = await pool.fetch("SELECT entity_type,entity_id FROM catalog_sources WHERE source_id LIKE $1", prefix+"%")
        for mapping in mappings:
            await pool.execute("DELETE FROM entity_search WHERE entity_type=$1 AND entity_id=$2", mapping["entity_type"], mapping["entity_id"])
        uni_id = await pool.fetchval("SELECT entity_id FROM catalog_sources WHERE source_id=$1", prefix+"0")
        await pool.execute("DELETE FROM catalog_sources WHERE source_id LIKE $1", prefix+"%")
        await pool.execute("DELETE FROM catalog_events WHERE source_id LIKE $1", prefix+"%")
        if uni_id:
            await pool.execute("DELETE FROM universities WHERE id=$1", uni_id)
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
