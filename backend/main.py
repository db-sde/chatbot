
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel, EmailStr, Field
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
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


from db.migrate import run_migrations


@asynccontextmanager
async def lifespan(app_: FastAPI):  # noqa: ARG001
    await run_migrations()
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
# proxy's own IP. "*" is rejected in settings because it lets any client
# spoof X-Forwarded-For and bypass per-IP rate limits.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxies)  # type: ignore


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:;"
    )
    return response


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


class WidgetSettingsRequest(BaseModel):
    show_estimated_wait_time: bool = True
    sound_notifications: bool = True
    desktop_notifications: bool = True
    mobile_message_preview: bool = True
    agent_typing_indicator: bool = True
    visitor_typing_indicator: bool = True
    browser_tab_notifications: bool = True
    hide_when_offline: bool = False
    hide_on_desktop: bool = False
    hide_on_mobile: bool = False
    offline_if_no_agents: bool = False
    emoji_picker_enabled: bool = True
    file_upload_enabled: bool = True
    chat_rating_enabled: bool = True
    email_transcript_enabled: bool = True


class WidgetSettingsUpdate(BaseModel):
    show_estimated_wait_time: bool | None = None
    sound_notifications: bool | None = None
    desktop_notifications: bool | None = None
    mobile_message_preview: bool | None = None
    agent_typing_indicator: bool | None = None
    visitor_typing_indicator: bool | None = None
    browser_tab_notifications: bool | None = None
    hide_when_offline: bool | None = None
    hide_on_desktop: bool | None = None
    hide_on_mobile: bool | None = None
    offline_if_no_agents: bool | None = None
    emoji_picker_enabled: bool | None = None
    file_upload_enabled: bool | None = None
    chat_rating_enabled: bool | None = None
    email_transcript_enabled: bool | None = None



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

    # Extract visitor metadata from the HTTP layer (server-side; not from the client body)
    client_ip: str | None = request.client.host if request.client else None
    client_ua: str | None = request.headers.get("user-agent")

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
                yield f"event: token\ndata: {json.dumps({'text': _POLICY_BLOCKED})}\n\n"
                yield f"event: final\ndata: {json.dumps({'lead_ask': False, 'quick_replies': []})}\n\n"
                return

            # ── Layer 3: LangGraph Agent ──
            async for event in run_chat_turn(
                session_id=body.session_id,
                site_id=body.site_key,
                message=body.message,
                page_university_slug=body.page_university_slug,
                ip_address=client_ip,
                user_agent=client_ua,
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


@app.get("/api/session/history")
@limiter.limit("20/minute")
async def session_history(
    request: Request,
    session_id: str,
    site_key: str,
    limit: int = 20,
    before_id: int | None = None,
) -> dict:
    """Public endpoint for the widget to load prior messages on page load.

    Gated by origin + site_key validation (same as /chat) — no admin token
    required. Tool call payloads are intentionally excluded from this response;
    they are available only through the admin /api/admin/conversations/{id} route.
    """
    validate_site_request(site_key, request.headers.get("origin"), request.headers.get("referer"))
    pool = await get_pool()
    return await queries.get_session_history(pool, session_id, limit=limit, before_id=before_id)


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


@app.get("/api/admin/analytics/overview")
async def admin_analytics_overview(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return high-level overview metrics for the AI Advisor performance dashboard."""
    pool = await get_pool()
    return await queries.get_analytics_overview(pool)


@app.get("/api/admin/analytics/models")
async def admin_analytics_models(_: Annotated[None, Depends(check_admin_auth)]) -> list[dict]:
    """Return token count, cost, and latency averages grouped by LLM model."""
    pool = await get_pool()
    return await queries.get_analytics_models(pool)


@app.get("/api/admin/analytics/tools")
async def admin_analytics_tools(_: Annotated[None, Depends(check_admin_auth)]) -> list[dict]:
    """Return execution counts, average durations, and success rates for all tools."""
    pool = await get_pool()
    return await queries.get_analytics_tools(pool)


@app.get("/api/admin/analytics/universities")
async def admin_analytics_universities(_: Annotated[None, Depends(check_admin_auth)]) -> list[dict]:
    """Return conversation volume, conversion rate, token usage, and cost grouped by university page context."""
    pool = await get_pool()
    return await queries.get_analytics_universities(pool)


@app.get("/api/admin/analytics/costs")
async def admin_analytics_costs(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return platform cost stats (daily, weekly, monthly) and list most expensive conversations."""
    pool = await get_pool()
    return await queries.get_analytics_costs(pool)


@app.get("/api/admin/analytics/funnel")
async def admin_analytics_funnel(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return overall user funnel counts and conversions (qualified chats, leads, cost per lead)."""
    pool = await get_pool()
    return await queries.get_analytics_funnel(pool)


@app.get("/api/admin/analytics/leads")
async def admin_analytics_leads(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return lead source breakdowns and category distributions."""
    pool = await get_pool()
    return await queries.get_lead_intent_analytics(pool)


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

@app.get("/api/admin/settings/status")
async def admin_settings_status(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return read-only status of AI providers, lead delivery, and active session user."""
    from llm import config
    from agent.llm_client import llm_client
    
    ai_status = "Connected" if llm_client.enabled else "Not Configured"
    lead_enabled = bool(settings.crm_webhook_url)
    
    return {
        "ai_provider": {
            "provider": config.PROVIDER.title(),
            "model": config.MODEL,
            "status": ai_status
        },
        "lead_delivery": {
            "enabled": lead_enabled,
            "delivery_method": "CRM Webhook" if lead_enabled else "None",
            "last_delivery_status": "Success" if lead_enabled else "N/A"
        },
        "current_user": {
            "username": "admin",
            "role": "System Administrator"
        }
    }


@app.get("/api/admin/settings/site-domains")
async def admin_site_domains(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return configured site keys and their allowed domains."""
    return {"site_domains": settings.site_domains}



@app.get("/api/admin/widget-settings")
async def admin_list_widget_settings(_: Annotated[None, Depends(check_admin_auth)]) -> list[dict]:
    """List widget settings for all configured sites."""
    pool = await get_pool()
    return await queries.list_widget_settings(pool)


@app.get("/api/admin/widget-settings/{site_id}")
async def admin_get_widget_settings(site_id: str, _: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Get widget settings for a specific site."""
    pool = await get_pool()
    return await queries.get_widget_settings(pool, site_id)


@app.put("/api/admin/widget-settings/{site_id}")
async def admin_update_widget_settings(
    site_id: str,
    body: WidgetSettingsUpdate = Body(...),
    _: Annotated[None, Depends(check_admin_auth)] = None,
) -> dict:
    """Update widget settings for a specific site."""
    pool = await get_pool()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    return await queries.upsert_widget_settings(pool, site_id, update)


@app.get("/public/widget-settings")
@limiter.limit("60/minute")
async def public_widget_settings(request: Request, site_key: str) -> dict:
    """Public endpoint for the widget to fetch its runtime configuration.

    Only safe, widget-facing settings are exposed.  site_key is validated
    against allowed origins just like /chat.
    """
    validate_site_request(site_key, request.headers.get("origin"), request.headers.get("referer"))
    pool = await get_pool()
    row = await queries.get_widget_settings(pool, site_key)

    # Strip internal/admin-only fields before returning to the browser.
    safe_keys = [
        "site_id",
        "show_estimated_wait_time",
        "sound_notifications",
        "desktop_notifications",
        "mobile_message_preview",
        "agent_typing_indicator",
        "visitor_typing_indicator",
        "browser_tab_notifications",
        "hide_when_offline",
        "hide_on_desktop",
        "hide_on_mobile",
        "offline_if_no_agents",
        "emoji_picker_enabled",
        "file_upload_enabled",
        "chat_rating_enabled",
        "email_transcript_enabled",
    ]
    return {k: row.get(k) for k in safe_keys}


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



