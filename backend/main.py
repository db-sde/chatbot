
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from agent.graph import run_chat_turn
from agent.tools import capture_lead
from auth import check_admin_auth, validate_site_request
from db import queries
from db.pool import close_pool, get_pool, init_pool
from rate_limit import limiter
from security.scanner import check_prompt_safety
from security.policy import check_policy
from settings import settings


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app_: FastAPI):  # noqa: ARG001
    await init_pool()
    yield
    await close_pool()


app = FastAPI(title="DegreeBaba AI Chatbot", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}))
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
# Added last so it is the OUTERMOST middleware (Starlette wraps in reverse
# add-order) — it must rewrite request.client.host from X-Forwarded-For
# BEFORE CORS/SlowAPI run, or get_remote_address() sees the proxy's IP for
# every request instead of the real visitor IP. trusted_hosts must be the
# proxy's own IP (or "*" only if this app is never reachable except through
# that proxy) — see settings.trusted_proxies / TRUSTED_PROXIES env var.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxies)


class ChatRequest(BaseModel):
    session_id: str
    site_key: str
    message: str = Field(min_length=1, max_length=4000)
    page_university_slug: str | None = None


class LeadRequest(BaseModel):
    session_id: str
    site_key: str
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=30)
    email: EmailStr | None = None
    course_interest: str | None = None



@app.get("/health")
async def health() -> dict[str, str]:
    return {"ok": "true"}


@app.post("/chat")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def chat(request: Request, body: ChatRequest = Body(...)) -> StreamingResponse:
    validate_site_request(body.site_key, request.headers.get("origin"), request.headers.get("referer"))
    pool = await get_pool()
    if await queries.count_site_messages_today(pool, body.site_key) >= settings.daily_message_cap_per_site:
        raise HTTPException(status_code=429, detail="Daily site message cap exceeded")

    _PROMPT_GUARD_BLOCKED = (
        "I'm not able to process that message. "
        "I'm here to help with universities, courses, fees, and admissions."
    )

    async def event_stream():
        try:
            pool = await get_pool()

            # ── Layer 1: Prompt Guard 2 ──
            safety = await check_prompt_safety(body.message)
            if not safety["safe"]:
                source = safety.get("source", "unknown")
                logger.warning(
                    "Prompt Guard blocked message (score=%.4f reason=%s source=%s) session=%s",
                    safety["risk_score"], safety["reason"], source, body.session_id,
                )
                await queries.insert_flagged_message(
                    pool, body.session_id, body.message,
                    layer=f"prompt_guard:{source}",
                    risk_score=safety["risk_score"],
                    reason=safety["reason"] or "injection",
                )
                await queries.insert_message(pool, body.session_id, "user", body.message)
                await queries.insert_message(pool, body.session_id, "assistant", _PROMPT_GUARD_BLOCKED, [])
                yield f"event: token\ndata: {json.dumps({'text': _PROMPT_GUARD_BLOCKED})}\n\n"
                yield f"event: final\ndata: {json.dumps({'lead_ask': False, 'quick_replies': []})}\n\n"
                return


            # ── Layer 2: DegreeBaba Policy ──
            policy = check_policy(body.message)
            if not policy["passed"]:
                logger.warning(
                    "Policy blocked message (rule=%s) session=%s",
                    policy["rule"], body.session_id,
                )
                _POLICY_BLOCKED = (
                    "I'm DegreeBaba's AI assistant and I can only help with "
                    "university, course, and admissions questions."
                )
                await queries.insert_flagged_message(
                    pool, body.session_id, body.message,
                    layer="policy",
                    risk_score=0.9,
                    reason=policy["rule"] or "policy_violation",
                )
                await queries.insert_message(pool, body.session_id, "user", body.message)
                await queries.insert_message(pool, body.session_id, "assistant", _POLICY_BLOCKED, [])
                yield f"event: token\ndata: {json.dumps({'text': _POLICY_BLOCKED})}\n\n"
                yield f"event: final\ndata: {json.dumps({'lead_ask': False, 'quick_replies': []})}\n\n"
                return

            # ── Layer 3: LangGraph Agent ──
            async for event in run_chat_turn(
                session_id=body.session_id,
                site_id=body.site_key,
                message=body.message,
                page_university_slug=body.page_university_slug,
            ):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"

        except Exception as exc:  # noqa: BLE001
            logger.error("event_stream error: %s", exc)
            error_msg = "I'm temporarily unavailable. Please try again in a moment."
            yield f"event: token\ndata: {json.dumps({'text': error_msg})}\n\n"
            yield f"event: final\ndata: {json.dumps({'lead_ask': False, 'quick_replies': []})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/webhook/lead")
@limiter.limit("3/minute")
async def lead_webhook(request: Request, body: LeadRequest = Body(...)) -> dict[str, bool]:
    validate_site_request(body.site_key, request.headers.get("origin"), request.headers.get("referer"))
    await capture_lead(
        body.session_id,
        body.name,
        body.phone,
        str(body.email) if body.email else None,
        body.course_interest,
        "widget_form",
    )
    if settings.crm_webhook_url:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(settings.crm_webhook_url, json=body.model_dump())
    return {"ok": True}


# ── Single Page Application Static Files Routing for built React app ──

admin_dist_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin", "dist"
)

@app.get("/admin")
async def serve_admin_dashboard_root():
    index_file = os.path.join(admin_dist_path, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    return HTMLResponse(
        "Dashboard build output not found. Please run <code>npm run build</code> inside the <code>admin</code> folder."
    )


@app.get("/admin/{path_name:path}")
async def serve_admin_dashboard(path_name: str):
    file_path = os.path.join(admin_dist_path, path_name)
    if path_name and os.path.isfile(file_path):
        return FileResponse(file_path)
    # Default to single-page application fallback
    index_file = os.path.join(admin_dist_path, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    return HTMLResponse(
        "Dashboard build output not found. Please run <code>npm run build</code> inside the <code>admin</code> folder."
    )


# ── Backend Administration API Endpoints (prefixed with /api/admin) ──

@app.get("/api/admin/conversations")
async def admin_conversations(
    _: Annotated[None, Depends(check_admin_auth)],
    university: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_lead: bool | None = None,
    has_unanswered: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    return await queries.list_conversations(pool, university, date_from, date_to, has_lead, has_unanswered, limit, offset)


@app.get("/api/admin/conversations/{session_id}")
async def admin_conversation(session_id: str, _: Annotated[None, Depends(check_admin_auth)]) -> dict:
    pool = await get_pool()
    return await queries.get_conversation(pool, session_id)


@app.get("/api/admin/leads")
async def admin_leads(_: Annotated[None, Depends(check_admin_auth)], limit: int = 100, offset: int = 0) -> list[dict]:
    pool = await get_pool()
    return await queries.list_leads(pool, limit, offset)


@app.get("/api/admin/unanswered")
async def admin_unanswered(_: Annotated[None, Depends(check_admin_auth)]) -> list[dict]:
    pool = await get_pool()
    return await queries.group_unanswered(pool)


@app.get("/api/admin/flagged")
async def admin_flagged(
    _: Annotated[None, Depends(check_admin_auth)],
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    return await queries.list_flagged_messages(pool, limit, offset)


@app.get("/api/admin/analytics")
async def admin_analytics(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    pool = await get_pool()
    return await queries.analytics(pool)


@app.get("/api/admin/security/summary")
async def admin_security_summary(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Security block summary: total, by layer, by reason, last 24h."""
    pool = await get_pool()
    return await queries.get_security_summary(pool)


@app.get("/api/admin/security/attacks")
async def admin_security_attacks(
    _: Annotated[None, Depends(check_admin_auth)],
    limit: int = 20,
) -> list[dict]:
    """Top attack patterns — most frequent blocked messages grouped by reason."""
    pool = await get_pool()
    return await queries.get_top_attack_patterns(pool, limit)

widget_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "widget"
)

@app.get("/widget.js")
async def serve_widget_js():
    return FileResponse(
        os.path.join(widget_dir, "widget.js"),
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=86400"},
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=2323, reload=True)



