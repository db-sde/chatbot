
import json
import logging
import logging.config
import os
import time
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


# ---------------------------------------------------------------------------
# Logging configuration
# Must be set before any logger.getLogger() calls so all modules inherit it.
# Render streams stdout to its log console; plain text works best there.
# ---------------------------------------------------------------------------
def configure_logging():
    _LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "default",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": _LOG_LEVEL,
        },
        # Keep uvicorn's own access/error logs visible too
        "loggers": {
            "uvicorn": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["console"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
            # Third-party noise: suppress httpx connection details unless debugging
            "httpx": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            "httpcore": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        },
    })

configure_logging()
logger = logging.getLogger(__name__)


from db.migrate import run_migrations


@asynccontextmanager
async def lifespan(app_: FastAPI):  # noqa: ARG001
    configure_logging()  # Override uvicorn logging initialization at startup
    from llm.provider import validate_provider_config
    validate_provider_config()
    await run_migrations()
    await init_pool()

    # Warm up the in-memory entity cache so the first request is fast
    try:
        from agent.resolve import load_entity_cache
        await load_entity_cache()
    except Exception:
        logger.warning("Entity cache warmup failed — will fall back to DB on first request")
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
    # Zero-config page context: the widget sends the current URL pathname
    # (e.g. "/colleges/nmims/mba-online").  The backend resolves it against
    # the DB; the frontend never needs to know slug conventions.
    page_pathname: str | None = None


class LeadRequest(BaseModel):
    session_id: str
    site_key: str
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=7, max_length=30)
    email: EmailStr | None = None
    course_interest: str | None = None


class WidgetSettingsUpdate(BaseModel):
    # Branding
    primary_color: str | None = None
    widget_title: str | None = None
    bot_name: str | None = None
    welcome_message: str | None = None
    logo_url: str | None = None

    # Behavior
    show_on_mobile: bool | None = None
    show_on_desktop: bool | None = None

    # Lead capture
    lead_capture_enabled: bool | None = None
    capture_name: bool | None = None
    capture_email: bool | None = None
    capture_phone: bool | None = None
    lead_trigger: str | None = None
    lead_form_title: str | None = None
    lead_form_description: str | None = None



@app.get("/health")
async def health() -> dict[str, str]:
    return {"ok": "true"}


@app.get("/")
@app.get("/demo")
async def serve_demo() -> FileResponse:
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    return FileResponse(os.path.join(static_dir, "demo.html"))



@app.post("/chat")
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def chat(request: Request, body: ChatRequest = Body(...)) -> StreamingResponse:
    # Extract visitor metadata from the HTTP layer (server-side; not from the client body)
    client_ip: str | None = request.client.host if request.client else None
    client_ua: str | None = request.headers.get("user-agent")

    logger.info(
        "CHAT REQUEST | session=%s site=%s ip=%s pathname=%s msg_len=%d msg=%r",
        body.session_id, body.site_key, client_ip,
        body.page_pathname or body.page_university_slug or "(none)",
        len(body.message), body.message[:120],
    )

    # ── IP Block Check ──
    if client_ip:
        pool = await get_pool()
        if await queries.is_ip_blocked(pool, client_ip):
            logger.warning("Blocked IP attempted chat: %s session=%s", client_ip, body.session_id)
            await queries.insert_security_event(
                pool,
                ip_address=client_ip,
                user_agent=client_ua,
                session_id=body.session_id,
                event_type="blocked_ip_access",
                severity="high",
                payload=body.message[:500],
                source="system",
                action_taken="blocked",
                blocked=True,
            )
            raise HTTPException(status_code=403, detail="Your access has been restricted due to suspicious activity.")

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
            request_started = time.perf_counter()
            pool = await get_pool()

            # ── Layer 1: Prompt Guard 2 ──
            logger.info("[%s] Running Prompt Guard...", body.session_id)
            stage_started = time.perf_counter()
            safety = await check_prompt_safety(body.message, body.session_id)
            prompt_guard_ms = (time.perf_counter() - stage_started) * 1000
            logger.info(
                "[%s] Prompt Guard result: safe=%s score=%.4f reason=%s source=%s",
                body.session_id, safety["safe"], safety["risk_score"],
                safety.get("reason"), safety.get("source"),
            )
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
                await queries.insert_security_event(
                    pool,
                    ip_address=client_ip,
                    user_agent=client_ua,
                    session_id=body.session_id,
                    event_type="prompt_injection",
                    severity="high" if safety["risk_score"] >= 0.9 else "medium",
                    payload=body.message[:500],
                    source=source,
                    action_taken="blocked",
                    blocked=True,
                    metadata={"risk_score": safety["risk_score"], "reason": safety["reason"]},
                )
                yield f"event: token\ndata: {json.dumps({'text': _PROMPT_GUARD_BLOCKED})}\n\n"
                yield f"event: final\ndata: {json.dumps({'lead_ask': False, 'quick_replies': []})}\n\n"
                return


            # ── Layer 2: DegreeBaba Policy ──
            logger.info("[%s] Running policy check...", body.session_id)
            stage_started = time.perf_counter()
            policy = check_policy(body.message)
            policy_ms = (time.perf_counter() - stage_started) * 1000
            logger.info("[%s] Policy result: passed=%s rule=%s", body.session_id, policy["passed"], policy.get("rule"))
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
                await queries.insert_security_event(
                    pool,
                    ip_address=client_ip,
                    user_agent=client_ua,
                    session_id=body.session_id,
                    event_type="policy_violation",
                    severity="medium",
                    payload=body.message[:500],
                    source="policy",
                    action_taken="blocked",
                    blocked=True,
                    metadata={"rule": policy["rule"]},
                )
                yield f"event: token\ndata: {json.dumps({'text': _POLICY_BLOCKED})}\n\n"
                yield f"event: final\ndata: {json.dumps({'lead_ask': False, 'quick_replies': []})}\n\n"
                return

            # ── Layer 3: LangGraph Agent ──
            # Resolve page context from pathname (zero-config; DB-verified slugs)
            resolved_page_university_slug = body.page_university_slug
            page_context_ms = 0.0
            if body.page_pathname:
                logger.info("[%s] Resolving page context for pathname: %s", body.session_id, body.page_pathname)
                from agent.page_context import resolve_page_context
                stage_started = time.perf_counter()
                page_ctx = await resolve_page_context(body.page_pathname, pool)
                page_context_ms = (time.perf_counter() - stage_started) * 1000
                if page_ctx.get("page_university_slug"):
                    resolved_page_university_slug = page_ctx["page_university_slug"]
                logger.info(
                    "[%s] Page context resolved: uni=%s (%s) course=%s (%s) spec=%s (%s)",
                    body.session_id,
                    page_ctx.get("page_university_name"), page_ctx.get("page_university_slug"),
                    page_ctx.get("page_course_name"), page_ctx.get("page_course_slug"),
                    page_ctx.get("page_spec_name"), page_ctx.get("page_spec_slug"),
                )
            else:
                page_ctx = {}

            logger.info(
                "[%s] Dispatching to LangGraph agent | uni_slug=%s",
                body.session_id, resolved_page_university_slug,
            )
            token_count = 0
            first_sse_event_at: float | None = None
            agent_turn_started = time.perf_counter()
            async for event in run_chat_turn(
                session_id=body.session_id,
                site_id=body.site_key,
                message=body.message,
                page_university_slug=resolved_page_university_slug,
                page_context=page_ctx,
                ip_address=client_ip,
                user_agent=client_ua,
                request_started_at=request_started,
            ):
                if event["event"] == "token":
                    token_count += 1
                    if first_sse_event_at is None:
                        first_sse_event_at = time.perf_counter()
                elif event["event"] == "final":
                    metrics = event["data"].get("metrics", {})
                    agent_turn_ms = (time.perf_counter() - agent_turn_started) * 1000
                    request_total_ms = (time.perf_counter() - request_started) * 1000
                    request_ttft_ms = (
                        (first_sse_event_at - request_started) * 1000
                        if first_sse_event_at is not None
                        else request_total_ms
                    )
                    request_accounted_ms = prompt_guard_ms + policy_ms + page_context_ms + agent_turn_ms
                    request_unaccounted_ms = max(request_total_ms - request_accounted_ms, 0.0)
                    metrics["request_timing_tree"] = {
                        "prompt_guard_ms": round(prompt_guard_ms, 1),
                        "policy_ms": round(policy_ms, 1),
                        "page_context_ms": round(page_context_ms, 1),
                        "agent_turn_ms": round(agent_turn_ms, 1),
                        "request_accounted_ms": round(request_accounted_ms, 1),
                        "request_unaccounted_ms": round(request_unaccounted_ms, 1),
                        "request_total_ms": round(request_total_ms, 1),
                        "request_ttft_ms": round(request_ttft_ms, 1),
                    }
                    logger.info(
                        "[%s] REQUEST TIMING TREE | prompt_guard_ms=%.1f policy_ms=%.1f "
                        "page_context_ms=%.1f agent_turn_ms=%.1f accounted_ms=%.1f "
                        "total_ms=%.1f unaccounted_ms=%.1f ttft_first_sse_ms=%.1f",
                        body.session_id,
                        prompt_guard_ms,
                        policy_ms,
                        page_context_ms,
                        agent_turn_ms,
                        request_accounted_ms,
                        request_total_ms,
                        request_unaccounted_ms,
                        request_ttft_ms,
                    )
                    logger.info(
                        "[%s] CHAT COMPLETE | tokens_streamed=%d response_time=%dms ttft=%dms "
                        "request_ttft=%dms request_total=%dms input_tok=%d output_tok=%d cost_usd=%.6f model=%s",
                        body.session_id, token_count,
                        metrics.get("response_time_ms", 0), metrics.get("ttft_ms", 0),
                        request_ttft_ms, request_total_ms,
                        metrics.get("input_tokens", 0), metrics.get("output_tokens", 0),
                        metrics.get("estimated_cost_usd", 0.0), metrics.get("model_name", "?"),
                    )
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
    client_ip: str | None = request.client.host if request.client else None
    if client_ip:
        pool = await get_pool()
        if await queries.is_ip_blocked(pool, client_ip):
            raise HTTPException(status_code=403, detail="Your access has been restricted due to suspicious activity.")

    validate_site_request(body.site_key, request.headers.get("origin"), request.headers.get("referer"))
    await capture_lead(
        body.session_id,
        body.name,
        body.phone,
        str(body.email) if body.email else None,
        body.course_interest,
        "widget_form",
        body.site_key,
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
    limit: int | None = None,
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
    """Extended security summary: event counts, blocked IPs, by-layer breakdown."""
    pool = await get_pool()
    return await queries.get_security_events_summary(pool)


@app.get("/api/admin/security/attacks")
async def admin_security_attacks(
    _: Annotated[None, Depends(check_admin_auth)],
    limit: int = 20,
) -> list[dict]:
    """Top attack patterns — most frequent blocked messages grouped by reason."""
    pool = await get_pool()
    return await queries.get_top_attack_patterns(pool, limit)


@app.get("/api/admin/security/events")
async def admin_security_events(
    _: Annotated[None, Depends(check_admin_auth)],
    limit: int = 100,
    offset: int = 0,
    event_type: str | None = None,
    severity: str | None = None,
    ip_address: str | None = None,
) -> list[dict]:
    """Paginated security event log with optional filters."""
    pool = await get_pool()
    return await queries.get_security_events(pool, limit=limit, offset=offset,
                                             event_type=event_type, severity=severity,
                                             ip_address=ip_address)


@app.get("/api/admin/security/timeline")
async def admin_security_timeline(
    _: Annotated[None, Depends(check_admin_auth)],
    hours: int = 24,
) -> list[dict]:
    """Hourly security event counts for the last N hours."""
    pool = await get_pool()
    return await queries.get_security_timeline(pool, hours=hours)


@app.get("/api/admin/security/top-ips")
async def admin_top_attacking_ips(
    _: Annotated[None, Depends(check_admin_auth)],
    limit: int = 20,
) -> list[dict]:
    """Top attacking IPs with attack count and block status."""
    pool = await get_pool()
    return await queries.get_top_attacking_ips(pool, limit)


# ── Blocked IPs management ──

class BlockIpRequest(BaseModel):
    ip_address: str
    reason: str | None = None
    block_type: str = "temporary"   # temporary | permanent
    expires_hours: int | None = 24  # Only used for temporary blocks


@app.get("/api/admin/security/blocked-ips")
async def admin_list_blocked_ips(
    _: Annotated[None, Depends(check_admin_auth)],
    include_inactive: bool = False,
) -> list[dict]:
    """List all blocked IPs."""
    pool = await get_pool()
    return await queries.list_blocked_ips(pool, include_inactive=include_inactive)


@app.post("/api/admin/security/blocked-ips")
async def admin_block_ip(
    body: BlockIpRequest,
    _: Annotated[None, Depends(check_admin_auth)] = None,
) -> dict:
    """Manually block an IP address."""
    from datetime import datetime, timezone, timedelta
    pool = await get_pool()
    expires_at = None
    if body.block_type == "temporary" and body.expires_hours:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=body.expires_hours)
    result = await queries.upsert_blocked_ip(
        pool,
        ip_address=body.ip_address,
        reason=body.reason or "Manually blocked by admin",
        blocked_by="admin",
        block_type=body.block_type,
        expires_at=expires_at,
    )
    # Record admin action in security events
    await queries.insert_security_event(
        pool,
        ip_address=body.ip_address,
        user_agent=None,
        session_id=None,
        event_type="suspicious_activity",
        severity="high",
        payload=None,
        source="admin",
        action_taken="auto_banned",
        blocked=True,
        metadata={"reason": body.reason, "block_type": body.block_type, "blocked_by": "admin"},
    )
    return result


@app.delete("/api/admin/security/blocked-ips/{ip_address}")
async def admin_unblock_ip(
    ip_address: str,
    _: Annotated[None, Depends(check_admin_auth)] = None,
) -> dict:
    """Unblock an IP address."""
    pool = await get_pool()
    cleared = await queries.unblock_ip(pool, ip_address)
    if not cleared:
        raise HTTPException(status_code=404, detail="No active block found for this IP")
    return {"ok": True, "ip_address": ip_address, "unblocked": True}

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


@app.post("/api/admin/cache/refresh")
async def admin_refresh_entity_cache(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Reload the in-memory entity cache from Postgres.

    Call this after ingesting new universities or courses so the entity
    resolver picks them up immediately without a server restart.
    """
    from agent.resolve import load_entity_cache, ENTITY_CACHE
    await load_entity_cache()
    return {
        "ok": True,
        "counts": {etype: len(rows) for etype, rows in ENTITY_CACHE.items()},
    }


@app.get("/api/admin/settings/site-domains")
async def admin_site_domains(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Return configured site keys and their allowed domains."""
    return {"site_domains": settings.site_domains}



@app.get("/api/admin/widget-settings")
async def admin_list_widget_settings(_: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Get the global widget settings."""
    pool = await get_pool()
    return await queries.get_widget_settings(pool)


@app.get("/api/admin/widget-settings/{site_id}")
async def admin_get_widget_settings(site_id: str, _: Annotated[None, Depends(check_admin_auth)]) -> dict:
    """Get the global widget settings (site_id ignored)."""
    pool = await get_pool()
    return await queries.get_widget_settings(pool)


@app.put("/api/admin/widget-settings/{site_id}")
async def admin_update_widget_settings(
    site_id: str,
    body: WidgetSettingsUpdate = Body(...),
    _: Annotated[None, Depends(check_admin_auth)] = None,
) -> dict:
    """Update global widget settings (site_id ignored)."""
    pool = await get_pool()
    update = {k: v for k, v in body.model_dump().items() if v is not None}
    return await queries.upsert_widget_settings(pool, "default", update)


@app.get("/widget/config")
@limiter.limit("60/minute")
async def get_widget_config(request: Request) -> dict:
    """Public endpoint for the widget to fetch its runtime configuration.

    Validates that the Origin/Referer header matches configured site domains.
    Returns nested branding, behavior, and lead capture settings.
    """
    client_ip: str | None = request.client.host if request.client else None
    if client_ip:
        pool = await get_pool()
        if await queries.is_ip_blocked(pool, client_ip):
            raise HTTPException(status_code=403, detail="Your access has been restricted due to suspicious activity.")

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    
    # Validate origin/referer against allowed site domains
    from auth import _host, is_domain_allowed
    host = _host(origin) or _host(referer)
    if host is not None and not is_domain_allowed(host):
        raise HTTPException(status_code=403, detail="Origin not allowed")

    pool = await get_pool()
    row = await queries.get_widget_settings(pool)

    return {
        "branding": {
            "primary_color": row.get("primary_color") or "#135d66",
            "widget_title": row.get("widget_title") or "DegreeBaba Assistant",
            "bot_name": row.get("bot_name") or "DegreeBaba Assistant",
            "welcome_message": row.get("welcome_message") or "Hello! Ask me about colleges, courses, admissions and fees.",
            "logo_url": row.get("logo_url")
        },
        "behavior": {
            "show_on_mobile": row.get("show_on_mobile") if row.get("show_on_mobile") is not None else True,
            "show_on_desktop": row.get("show_on_desktop") if row.get("show_on_desktop") is not None else True
        },
        "lead_capture": {
            "lead_capture_enabled": row.get("lead_capture_enabled") if row.get("lead_capture_enabled") is not None else True,
            "capture_name": row.get("capture_name") if row.get("capture_name") is not None else True,
            "capture_email": row.get("capture_email") if row.get("capture_email") is not None else True,
            "capture_phone": row.get("capture_phone") if row.get("capture_phone") is not None else True,
            "lead_trigger": row.get("lead_trigger") or "during_chat",
            "lead_form_title": row.get("lead_form_title") or "Request callback",
            "lead_form_description": row.get("lead_form_description") or "A counsellor can follow up with you."
        }
    }


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
