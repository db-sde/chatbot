

import json
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from agent.graph import run_chat_turn
from agent.tools import capture_lead
from auth import check_admin_auth, validate_site_request
from db import queries
from db.pool import close_pool, get_pool, init_pool
from rate_limit import limiter
from settings import settings


app = FastAPI(title="DegreeBaba AI Chatbot", version="0.1.0")
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


@app.on_event("startup")
async def on_startup() -> None:
    await init_pool()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_pool()


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

    async def event_stream():
        try:
            async for event in run_chat_turn(
                session_id=body.session_id,
                site_id=body.site_key,
                message=body.message,
                page_university_slug=body.page_university_slug,
            ):
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
        except Exception as exc:  # noqa: BLE001
            # Catch any unhandled error (e.g. 429 quota) so the stream ends cleanly
            # with a visible error token rather than an empty body.
            import logging
            logging.getLogger(__name__).error("event_stream error: %s", exc)
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


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(_: Annotated[None, Depends(check_admin_auth)]) -> str:
    return """
    <!doctype html><html><head><title>DegreeBaba Admin</title></head>
    <body><h1>DegreeBaba AI Admin</h1><pre id="out">Loading...</pre>
    <script>
    const token = prompt("Admin token");
    Promise.all([
      fetch('/admin/conversations', {headers:{Authorization:`Bearer ${token}`}}).then(r=>r.json()),
      fetch('/admin/leads', {headers:{Authorization:`Bearer ${token}`}}).then(r=>r.json()),
      fetch('/admin/unanswered', {headers:{Authorization:`Bearer ${token}`}}).then(r=>r.json())
    ]).then(data => out.textContent = JSON.stringify({conversations:data[0], leads:data[1], unanswered:data[2]}, null, 2));
    </script></body></html>
    """


@app.get("/admin/conversations")
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


@app.get("/admin/conversations/{session_id}")
async def admin_conversation(session_id: str, _: Annotated[None, Depends(check_admin_auth)]) -> dict:
    pool = await get_pool()
    return await queries.get_conversation(pool, session_id)


@app.get("/admin/leads")
async def admin_leads(_: Annotated[None, Depends(check_admin_auth)], limit: int = 100, offset: int = 0) -> list[dict]:
    pool = await get_pool()
    return await queries.list_leads(pool, limit, offset)


@app.get("/admin/unanswered")
async def admin_unanswered(_: Annotated[None, Depends(check_admin_auth)]) -> list[dict]:
    pool = await get_pool()
    return await queries.group_unanswered(pool)


@app.get("/admin/analytics")
async def admin_analytics(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    pool = await get_pool()
    return await queries.analytics(pool)
