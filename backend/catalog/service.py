from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from urllib.parse import urlsplit

from catalog.adapter import TABLES, adapt_data, build_sections, child_fields
from catalog.schema import CatalogError, CatalogEvent
from db.pool import get_pool
from catalog.importer import upsert_course, upsert_specialization, upsert_university

logger = logging.getLogger(__name__)
IMPORTERS = {"university": upsert_university, "course": upsert_course, "specialization": upsert_specialization}


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def event_status(row):
    return {key: (decode(row[key]) if key == "warnings" else str(row[key]) if key == "event_id" else row[key]) for key in ("event_id", "status", "attempts", "last_error", "warnings", "entity_slug")}


async def enqueue(pool, event: CatalogEvent):
    payload = event.model_dump(mode="json")
    body = encoded(payload)
    digest = hashlib.sha256(body.encode()).hexdigest()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO catalog_events(event_id,source,entity_type,source_id,version,payload,payload_hash)
                VALUES($1,$2,$3,$4,$5,$6::jsonb,$7) ON CONFLICT DO NOTHING RETURNING *""",
                event.event_id, event.source, event.entity_type, event.source_id, event.version, body, digest,
            )
            if row:
                return event_status(row), True
            row = await conn.fetchrow("SELECT * FROM catalog_events WHERE event_id=$1", event.event_id)
            if not row or row["payload_hash"] != digest:
                raise CatalogError("event_or_version_conflict")
            return event_status(row), False


async def read_baseline(conn, entity_type, row):
    if not row:
        return {}
    raw = decode(row["raw_json"]) or {}
    baseline = {**raw, **{k: v for k, v in dict(row).items() if k != "raw_json"}}
    for table, fields in child_fields(entity_type).items():
        if table in {"faqs", "reviews", "job_profiles", "highlights"}:
            rows = await conn.fetch(f"SELECT {','.join(fields)} FROM {table} WHERE entity_type=$1 AND entity_id=$2 ORDER BY id", entity_type, row["id"])
        else:
            fk = {"university": "university_id", "course": "course_id", "specialization": "specialization_id"}[entity_type]
            rows = await conn.fetch(f"SELECT {','.join(fields)} FROM {table} WHERE {fk}=$1 ORDER BY id", row["id"])
        baseline[table] = [dict(r) for r in rows]
    return baseline


async def source_row(conn, event, entity_type, source_id):
    return await conn.fetchrow("SELECT * FROM catalog_sources WHERE source=$1 AND entity_type=$2 AND source_id=$3", event.source, entity_type, source_id)


async def apply_event(conn, event: CatalogEvent):
    mapping = await source_row(conn, event, event.entity_type, event.source_id)
    if mapping and mapping["applied_version"] >= event.version:
        return "ignored", mapping["entity_slug"], []
    if mapping and event.catalog_slug and event.catalog_slug != mapping["entity_slug"]:
        raise CatalogError("cannot_change_catalog_slug")
    slug = mapping["entity_slug"] if mapping else event.catalog_slug
    if not slug:
        stable = hashlib.sha256(f"{event.source}:{event.source_id}".encode()).hexdigest()[:20]
        slug = f"wp-{event.entity_type}-{stable}"
    table = TABLES[event.entity_type]
    row = await conn.fetchrow(f"SELECT * FROM {table} WHERE slug=$1 FOR UPDATE", slug)
    if mapping and (not row or row["id"] != mapping["entity_id"]):
        raise CatalogError("catalog_mapping_changed")
    if row and not mapping:
        claimed = await conn.fetchval("SELECT 1 FROM catalog_sources WHERE entity_type=$1 AND entity_id=$2", event.entity_type, row["id"])
        if claimed:
            raise CatalogError("catalog_row_already_linked")
        if not event.catalog_slug:
            raise CatalogError("generated_slug_collision")

    source_path = urlsplit(str(event.source_url)).path.rstrip("/") or "/"
    path_owner = await conn.fetchval(
        "SELECT 1 FROM catalog_sources WHERE source=$1 AND source_path=$2 AND (entity_type<>$3 OR source_id<>$4)",
        event.source, source_path, event.entity_type, event.source_id,
    )
    if path_owner:
        raise CatalogError("source_path_already_linked")
    university = course = None
    if event.university_source_id:
        university = await source_row(conn, event, "university", event.university_source_id)
        if not university:
            raise CatalogError("parent_university_not_synced")
        if not await conn.fetchval("SELECT 1 FROM universities WHERE id=$1 AND slug=$2", university["entity_id"], university["entity_slug"]):
            raise CatalogError("parent_university_missing")
        if row and row["university_id"] != university["entity_id"]:
            raise CatalogError("cannot_reparent_existing_entity")
    if event.course_source_id:
        course = await source_row(conn, event, "course", event.course_source_id)
        if not course:
            raise CatalogError("parent_course_not_synced")
        valid = await conn.fetchval("SELECT 1 FROM courses WHERE id=$1 AND slug=$2 AND university_id=$3", course["entity_id"], course["entity_slug"], university["entity_id"])
        if not valid:
            raise CatalogError("course_university_mismatch")
        if row and row["course_id"] != course["entity_id"]:
            raise CatalogError("cannot_reparent_existing_entity")

    baseline = await read_baseline(conn, event.entity_type, row)
    normalized, warnings = await asyncio.to_thread(adapt_data, event.entity_type, event.data, baseline, event.clear_fields)
    normalized["slug"] = slug
    if university:
        normalized["university_slug"] = university["entity_slug"]
    if course:
        normalized["course_slug"] = course["entity_slug"]
    # Strip DB-only values; raw_json is the merged, safe importer snapshot.
    for key in ("id", "created_at", "updated_at", "university_id", "course_id", "_meta"):
        normalized.pop(key, None)
    sections = await asyncio.to_thread(build_sections, normalized)
    slug, entity_id = await IMPORTERS[event.entity_type](conn, normalized)
    path = urlsplit(str(event.source_url)).path.rstrip("/") or "/"
    await conn.execute(
        """INSERT INTO catalog_sources(source,entity_type,source_id,entity_id,entity_slug,applied_version,source_url,source_path,original_payload)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
        ON CONFLICT(source,entity_type,source_id) DO UPDATE SET
        applied_version=EXCLUDED.applied_version,source_url=EXCLUDED.source_url,source_path=EXCLUDED.source_path,
        original_payload=EXCLUDED.original_payload,updated_at=now()""",
        event.source, event.entity_type, event.source_id, entity_id, slug, event.version, str(event.source_url), path, encoded(event.data),
    )
    await conn.execute("DELETE FROM catalog_sections WHERE source=$1 AND entity_type=$2 AND source_id=$3", event.source, event.entity_type, event.source_id)
    if sections:
        await conn.executemany(
            "INSERT INTO catalog_sections(source,entity_type,source_id,section_id,title,content) VALUES($1,$2,$3,$4,$5,$6)",
            [(event.source, event.entity_type, event.source_id, i, title, content) for i, (title, content) in enumerate(sections)],
        )
    await conn.execute("UPDATE catalog_revision SET revision=revision+1 WHERE singleton=TRUE")
    return "applied", slug, warnings


async def process_next(pool) -> bool:
    """One short transaction, one importer across all API workers; crashes roll back."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval("SELECT pg_try_advisory_xact_lock(63881742)"):
                return False
            await conn.execute("SET LOCAL statement_timeout='8s'")
            await conn.execute("SET LOCAL lock_timeout='1s'")
            row = await conn.fetchrow("SELECT * FROM catalog_events WHERE status='queued' AND next_attempt_at<=now() ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED")
            if not row:
                return False
            attempts = row["attempts"] + 1
            try:
                async with conn.transaction():  # savepoint preserves event lock if import fails
                    event = CatalogEvent.model_validate(decode(row["payload"]))
                    async with asyncio.timeout(15):
                        status, slug, warnings = await apply_event(conn, event)
            except Exception as exc:
                code = str(exc) if isinstance(exc, CatalogError) else "import_error"
                # Only missing parents and transient database errors retry automatically.
                retryable = code in {"parent_university_not_synced", "parent_course_not_synced", "import_error"}
                status = "queued" if retryable and attempts < 10 else "failed"
                await conn.execute(
                    """UPDATE catalog_events SET status=$2,attempts=$3,last_error=$4,
                    next_attempt_at=now()+$5*interval '1 second',updated_at=now() WHERE id=$1""",
                    row["id"], status, attempts, code, min(300, 2**min(attempts, 9)),
                )
                logger.warning("Catalog event %s: %s (%s)", row["event_id"], status, code)
            else:
                await conn.execute("UPDATE catalog_events SET status=$2,attempts=$3,entity_slug=$4,warnings=$5::jsonb,last_error=NULL,updated_at=now() WHERE id=$1", row["id"], status, attempts, slug, encoded(warnings))
    return True


async def run_import_worker():
    while True:
        try:
            worked = await process_next(await get_pool())
        except Exception:
            logger.exception("Catalog worker will retry after a database error")
            worked = False
        await asyncio.sleep(0.1 if worked else 2)


async def watch_catalog_revision():
    """Refresh each process's cache in batches; no per-chat revision check."""
    seen = None
    while True:
        try:
            pool = await get_pool()
            revision = await pool.fetchval("SELECT revision FROM catalog_revision WHERE singleton=TRUE")
            if revision != seen:
                from agent.resolve import load_entity_cache
                await load_entity_cache()
                seen = revision
        except Exception:
            logger.exception("Catalog cache refresh will retry")
        await asyncio.sleep(2)
