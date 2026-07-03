# DegreeBaba AI Chatbot

Production-oriented FastAPI scaffold for the DegreeBaba WordPress chatbot. It uses a single PostgreSQL database with `pgvector`, async `asyncpg` queries, a LangGraph agent powered by **Groq (llama-3.3-70b-versatile)**, SSE streaming, and a vanilla Shadow DOM widget.

## Setup

```bash
cp .env.example .env
```

For local Docker, keep `DATABASE_URL=postgresql://postgres:postgres@db:5432/degreebaba_ai`. For running scripts directly from your host, use `localhost` instead of `db`.

Required values:

```text
DATABASE_URL=
GROQ_API_KEY=          # get a free key at https://console.groq.com
ALLOWED_SITE_KEYS=
ALLOWED_ORIGINS=
CRM_WEBHOOK_URL=
ADMIN_AUTH_TOKEN=
RATE_LIMIT_PER_MINUTE=10
DAILY_MESSAGE_CAP_PER_SITE=2000
POSTGRES_PASSWORD=
```

## Run With Docker

```bash
docker compose up --build
```

In another shell:

```bash
docker compose exec api python -m db.migrate
docker compose exec api python -m ingestion.microapp_to_db /ingestion/fixtures/sample_university.json
docker compose exec api python -m ingestion.microapp_to_db /ingestion/fixtures/sample_course.json
docker compose exec api python -m ingestion.microapp_to_db /ingestion/fixtures/sample_specialization.json
```

The compose file mounts `./ingestion` at `/ingestion` and sets `PYTHONPATH=/app:/` so the CLI can import both backend settings and the ingestion module.

## Run Locally (with uv Workspace)

```bash
# Sync and set up the local workspace virtual environment (installs all packages)
uv sync --all-packages

# Run the database migrations from the root folder
uv run python -m db.migrate

# Seed the sample database fixtures
uv run python -m ingestion.microapp_to_db ingestion/fixtures/sample_university.json
uv run python -m ingestion.microapp_to_db ingestion/fixtures/sample_course.json
uv run                python -m ingestion.microapp_to_db ingestion/fixtures/sample_specialization.json

# Start the FastAPI server
cd backend
uv run uvicorn main:app --reload
```

## Chat API

`POST /chat` returns `text/event-stream`:

```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "site_key": "degreebaba_dev",
  "message": "What's the MBA fee at NMIMS?",
  "page_university_slug": "nmims"
}
```

Requests must include an allowed `Origin` or `Referer` header matching `ALLOWED_SITE_KEYS`.

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
GET /admin/conversations
GET /admin/conversations/{session_id}
GET /admin/leads
GET /admin/unanswered
GET /admin/analytics
```

`/admin` provides a minimal JSON viewer for quick internal inspection.

## Tests

```bash
uv run pytest tests -v
```

The unit tests monkeypatch the async pool with fixture-like in-memory rows, so they validate tool behavior without requiring a Groq API key or a live database.
