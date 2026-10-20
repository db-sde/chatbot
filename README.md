# DegreeBaba AI Chatbot

Production-oriented FastAPI scaffold for the DegreeBaba WordPress chatbot. It uses a single PostgreSQL database with `pgvector`, async `asyncpg` queries, a LangGraph agent powered by **Groq (llama-3.3-70b-versatile)**, SSE streaming, and a vanilla Shadow DOM widget.

## Setup

```bash
cp .env.example .env
```

For Docker Compose, set `DATABASE_URL=postgresql://postgres:postgres@db:5432/degreebaba_ai` in `.env` (replace the password if changed). For a backend running on your host, use `localhost` instead of `db`. Compose preserves the configured URL, so an external database remains supported.

Set the selected provider's real API key and generate an admin token:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Put the generated value in `ADMIN_AUTH_TOKEN`. Blank tokens and the old `change-me` default disable administration with HTTP 503; chat remains independently configured. Settings read the repository's `.env` consistently from either working directory.

Required values:

```text
DATABASE_URL=
GROQ_API_KEY=          # get a free key at https://console.groq.com
ALLOWED_SITE_KEYS=     # single source of truth for CORS + Origin/Referer validation
CRM_WEBHOOK_URL=
ADMIN_AUTH_TOKEN=
RATE_LIMIT_PER_MINUTE=10
DAILY_MESSAGE_CAP_PER_SITE=2000
POSTGRES_PASSWORD=
TRUSTED_PROXIES=127.0.0.1  # set to your reverse proxy's IP in production
```

> **Deploying behind Nginx/Caddy/Cloudflare?** Set `TRUSTED_PROXIES` to the
> IP(s) of whatever sits directly in front of this app. Without it, SlowAPI's
> rate limiter sees the proxy's IP on every request instead of the visitor's,
> and your per-IP limits silently become one shared limit for the whole site.

## Run With Docker

```bash
docker compose up --build
```

In another shell:

```bash
docker compose exec api python -m db.migrate
docker compose exec api python -m ingestion.microapp_to_db /app/ingestion/fixtures/sample_university.json
docker compose exec api python -m ingestion.microapp_to_db /app/ingestion/fixtures/sample_course.json
docker compose exec api python -m ingestion.microapp_to_db /app/ingestion/fixtures/sample_specialization.json
```

Build from the repository root. The image includes the locked workspace dependencies in `/opt/venv`, backend, ingestion CLI, widget, and committed admin build. Source mounts at `/app/backend` and `/app/ingestion` preserve that environment. Compose waits for database readiness. API startup applies migrations automatically.

Sample fixtures and `seed_database.py` contain demo data. Use reviewed catalog records for student-facing deployments.

## Run Locally (with uv Workspace)

```bash
# Sync and set up the local workspace virtual environment (installs all packages)
uv sync --all-packages --frozen

# Allow root-level commands to import backend modules and ingestion.
export PYTHONPATH="$PWD/backend:$PWD"

# Run the database migrations from the root folder
uv run --all-packages python -m db.migrate

# Seed the sample database fixtures
uv run --all-packages python -m ingestion.microapp_to_db ingestion/fixtures/sample_university.json
uv run --all-packages python -m ingestion.microapp_to_db ingestion/fixtures/sample_course.json
uv run --all-packages python -m ingestion.microapp_to_db ingestion/fixtures/sample_specialization.json

# Start the FastAPI server
uv run --all-packages uvicorn main:app --reload --port 2323
```

## Chat API

`POST /chat` returns `text/event-stream`:

```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "site_key": "degreebaba_dev",
  "message": "What's the MBA fee at NMIMS?",
  "page_university_slug": "nmims",
  "page_pathname": "/colleges/nmims/online-mba"
}
```

Requests must include an allowed `Origin` or `Referer` header matching `ALLOWED_SITE_KEYS`.

The widget sends the pathname automatically. The backend verifies university, course, and specialization paths against the catalog. Explicit message entities take precedence; existing session context retains its current priority over page hints. Catalog-wide requests remain catalog-wide.

## Widget Test

Serve the widget directory from a static server:

```bash
cd widget
python -m http.server 8080
```

Open `http://localhost:8080/test.html`. The test page loads:

```html
<script src="./widget.js" data-site-key="degreebaba_dev" data-university-slug="nmims" data-api-base="http://localhost:2323" defer></script>
```

## Admin

Use `Authorization: Bearer <ADMIN_AUTH_TOKEN>` for:

```text
GET /api/admin/conversations
GET /api/admin/conversations/{session_id}
GET /api/admin/leads
GET /api/admin/unanswered
GET /api/admin/analytics
```

`/admin` serves the React dashboard. Rebuild its committed assets after changing the admin source:

```bash
cd admin
npm ci
npm run lint
npm run build
```

## Lead saves and CRM delivery

Both full forms and progressive contact fields save leads in PostgreSQL. A progressive callback needs a name and phone; email remains optional and can be added later. The widget confirms success after a successful server response and retains entered values when saving fails. Its optional `submission_id` makes retries of one form idempotent, while distinct requests remain supported.

When `CRM_WEBHOOK_URL` is configured, lead saving atomically queues a durable delivery in `crm_deliveries`. A worker sends it outside the visitor's request, checks HTTP failures, retries with backoff, and recovers interrupted claims. The dashboard reports recorded delivery status. CRM delivery is at least once; the receiver should honor the stable `Idempotency-Key` header to prevent duplicates after a network interruption. Queued deliveries retain the webhook URL configured when they were created; the worker runs while CRM delivery is enabled. No historical leads are automatically resent.

Migration `0002_lead_delivery.sql` adds the submission key and outbox without removing existing data. Apply migrations before starting the new code; normal API startup does this automatically. Back up production data as part of your normal release process.

## Tests

```bash
uv run --all-packages pytest tests -v
```

Offline tests use mocks and require no LLM key. Database tests skip unless `TEST_DATABASE_URL` is explicitly set to an isolated database whose name ends in `_test`:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/degreebaba_ai_test uv run --all-packages pytest tests -v
```

CI supplies this URL, so database tests cannot silently skip there. These tests migrate and ingest fixtures into that database and exercise concurrent saves, retries, scoping, and upgrades. Never point them at application data.

The optional browser regression uses Node and Playwright (`node tests/widget_regression.cjs`). Install Playwright and its Chromium browser in your test environment, or set `PLAYWRIGHT_CHANNEL=chrome` to use installed Chrome. It intercepts all HTTP traffic and verifies failed-save retries, idempotency, escaped settings, pathname transmission, and confirmed success.

The uv workspace and `uv.lock` are the dependency source of truth. `backend/requirements.txt` is an export of the same runtime lock. See [FIXES.md](FIXES.md) for the verified fix scope and remaining limitations.

## Parser catalog integration

The chatbot accepts signed, versioned published catalog updates from DegreeBaba Parser and imports them through a durable background queue. See [CATALOG_SYNC.md](CATALOG_SYNC.md) for activation, authentication, field preservation, status endpoints and limits. Give [PARSER_CONNECTION_PROMPT.md](PARSER_CONNECTION_PROMPT.md) to the coding agent working on the parser app to implement the matching sender. Integration is disabled until `CATALOG_WEBHOOK_SECRET` is configured; this local implementation has not been deployed.
