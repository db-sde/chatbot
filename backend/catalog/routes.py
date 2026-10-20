from __future__ import annotations

import hashlib
import hmac
import time
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from auth import check_admin_auth
from catalog.schema import CatalogError, CatalogEvent
from catalog.service import enqueue, event_status
from db.pool import get_pool
from settings import settings

router = APIRouter()
MAX_BODY_BYTES = 2 * 1024 * 1024


def verify_signature(request: Request, body: bytes):
    secret = settings.catalog_webhook_secret or ""
    if len(secret.strip()) < 32:
        raise HTTPException(503, "Catalog sync is not configured")
    timestamp = request.headers.get("X-Catalog-Timestamp", "")
    signature = request.headers.get("X-Catalog-Signature", "")
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError
    except ValueError:
        raise HTTPException(401, "Invalid catalog signature") from None
    message = f"{timestamp}.{request.method}.{request.url.path}.".encode() + body
    expected = "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        raise HTTPException(401, "Invalid catalog signature")


@router.post("/webhook/catalog")
async def receive_catalog(request: Request):
    # Bound memory even for chunked requests without a Content-Length header.
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_BODY_BYTES:
            raise HTTPException(413, "Catalog event exceeds 2 MiB")
        chunks.extend(chunk)
    body = bytes(chunks)
    verify_signature(request, body)
    try:
        event = CatalogEvent.model_validate_json(body)
    except (ValidationError, ValueError, RecursionError):
        raise HTTPException(422, "Invalid catalog event; see schema_version 1 contract") from None
    allowed_hosts = {host.strip().lower() for host in settings.catalog_source_hosts.split(",") if host.strip()}
    if event.source_url.host.lower() not in allowed_hosts:
        raise HTTPException(422, "source_url host is not allowed")
    try:
        status, created = await enqueue(await get_pool(), event)
    except CatalogError as exc:
        raise HTTPException(409, str(exc)) from None
    return JSONResponse(status_code=202 if created else 200, content={"ok": True, **status})


@router.get("/webhook/catalog/{event_id}")
async def catalog_event_status(event_id: UUID, request: Request):
    verify_signature(request, b"")
    pool = await get_pool()
    row = await pool.fetchrow("SELECT * FROM catalog_events WHERE event_id=$1", event_id)
    if not row:
        raise HTTPException(404, "Catalog event not found")
    return {"ok": True, **event_status(row)}


@router.get("/api/admin/catalog/events", dependencies=[Depends(check_admin_auth)])
async def catalog_events(limit: int = 50):
    rows = await (await get_pool()).fetch("SELECT * FROM catalog_events ORDER BY id DESC LIMIT $1", max(1, min(limit, 200)))
    return [{**event_status(row), "source_id": row["source_id"], "entity_type": row["entity_type"], "version": row["version"]} for row in rows]


@router.post("/api/admin/catalog/events/{event_id}/retry", dependencies=[Depends(check_admin_auth)])
async def retry_catalog_event(event_id: UUID):
    row = await (await get_pool()).fetchrow("UPDATE catalog_events SET status='queued',attempts=0,last_error=NULL,next_attempt_at=now(),updated_at=now() WHERE event_id=$1 AND status='failed' RETURNING *", event_id)
    if not row:
        raise HTTPException(409, "Event is missing or is not failed")
    return {"ok": True, **event_status(row)}


@router.get("/api/admin/catalog/entities", dependencies=[Depends(check_admin_auth)])
async def catalog_entities(entity_type: Literal["university", "course", "specialization"] = "university", limit: int = 100, offset: int = 0):
    # A review aid for linking existing catalog rows before backfill, not fuzzy auto-adoption.
    table, title = {"university": ("universities", "name"), "course": ("courses", "program_name"), "specialization": ("specializations", "spec_name")}[entity_type]
    parent_columns = "" if entity_type == "university" else ",e.university_id" if entity_type == "course" else ",e.university_id,e.course_id"
    rows = await (await get_pool()).fetch(
        f"SELECT e.id,e.slug,e.{title} AS name{parent_columns},cs.source_id FROM {table} e LEFT JOIN catalog_sources cs ON cs.entity_type=$1 AND cs.entity_id=e.id ORDER BY e.id LIMIT $2 OFFSET $3",
        entity_type, max(1, min(limit, 200)), max(0, offset),
    )
    return [dict(row) for row in rows]
