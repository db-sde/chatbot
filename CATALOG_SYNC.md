# DegreeBaba Parser connection

The chatbot side is implemented locally, and the matching sender code is now present in the local DEGREEBABA PARSER app (contract checked 2026-10-17). Deployment/activation has not been verified. Use [LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md) for the coordinated rollout; [PARSER_CONNECTION_PROMPT.md](PARSER_CONNECTION_PROMPT.md) remains the original sender implementation specification.

## Activate

1. Deploy this chatbot code with its additive `0003_catalog_sync.sql` migration (normal app startup applies migrations).
2. Generate a new random shared secret, distinct from widget site keys, WordPress credentials and `ADMIN_AUTH_TOKEN`: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
3. Set chatbot `CATALOG_WEBHOOK_SECRET` and parser `CHATBOT_CATALOG_WEBHOOK_SECRET` to that same value. Configure parser `CHATBOT_BASE_URL` with the deployed chatbot origin. Do not commit secrets or expose them in the browser.
4. Chatbot `CATALOG_SOURCE_HOSTS` defaults to `degreebaba.com,www.degreebaba.com`; set the exact canonical content hosts if different. Restart the chatbot after configuration.
5. Implement the parser sender using the prompt, review links to existing catalog entries, test on staging, and backfill published parents before their children. 202 means durably queued, not imported; check event status before showing “synced”.

When the secret is absent/shorter than 32 characters, catalog endpoints return 503 and catalog background workers remain disabled. Existing chat, CRM, widget and recommendation behavior remain available. No new third-party service, embeddings or model training is required.

## Wire contract, version 1

`POST /webhook/catalog` accepts one event, maximum 2 MiB. Content is a UTF-8 JSON object matching `backend/catalog/schema.py`; extra top-level fields are rejected.

Required fields: `schema_version: 1`, UUID `event_id`, `source: "degreebaba-parser"`, `entity_type` (university/course/specialization), string `source_id` (WordPress post ID), positive integer `version`, `publication_status: "publish"`, public HTTPS `source_url`, and object `data` (original approved ACF content).

Course events require string `university_source_id`. Specializations require string `university_source_id` and `course_source_id`. Universities have no parents. Relationship names are never guessed. `source_url` must be canonical, without credentials, query or fragment, and on a configured source host. URLs are stored for attribution; the receiver does not fetch them.

Optional `catalog_slug` explicitly adopts a reviewed existing record, or specifies a new unique slug. Otherwise the receiver generates a stable ID-based slug. Existing mappings cannot change slug/parent automatically. The original URL path resolves to the internal catalog slugs for widget page context, so the generated internal slugs need not match WordPress paths.

The signing contract is shared by POST and `GET /webhook/catalog/{event_id}`:

```text
X-Catalog-Timestamp: <Unix seconds>
X-Catalog-Signature: sha256=<lowercase HMAC-SHA256 hex>

message = UTF8(timestamp + "." + method + "." + path + ".") + exact_body_bytes
signature = HMAC_SHA256(shared_secret, message)
```

Method is uppercase; path includes `/webhook/catalog` and the event UUID for GET, without a query string or trailing slash. GET signs an empty body. Headers/signatures expire after 300 seconds. Retry the same event/version/content with a fresh timestamp/signature. Use the exact bytes sent, not HTTP client's independently serialized JSON. HTTPS is required for production transport.

Response fields: `ok`, `event_id`, `status`, `attempts`, `last_error`, `warnings`, `entity_slug`. A new receipt returns 202; identical retries return 200 with current status. Reusing an event ID for different content, or allocating another event ID for an existing source/type/id/version, returns 409.

Statuses:

| Status | Meaning |
|---|---|
| queued | Durably stored, waiting for import or retry |
| applied | Catalog, source reference and section index committed together |
| ignored | Equal/newer source version already applied |
| failed | Needs operator correction or retry; current catalog transaction was rolled back |

Only `applied` means this snapshot was imported. Preserve event IDs and source versions in the sender database. Correct a failed payload by sending a new event/version. Receiver missing-parent/transient errors retry with backoff, up to ten attempts. Other validation/linking failures stop immediately. Admin can retry unchanged failed events after resolving their dependency/configuration.

## Preservation and field mapping

The original received ACF object is saved separately for provenance. The importer snapshot merges new values with current SQL values and related records, including reviewed adoption of old rows without `raw_json`.

- `university_name` → `name`; `university_full_name` → `full_name`; `course_name` → `program_name`; `specialization_name` → `spec_name`; `program_validity` → `validity`.
- Course/specialization `university_name` does not become the entity's own name; parent IDs control its university.
- Eligibility arrays become readable TEXT for existing tools; extra ACF fields are retained in the merged snapshot and indexed as page sections.
- Numeric fees accept a single rupee amount, including commas/lakh units. Ranges/per-period descriptions are not guessed into totals: existing numeric values are preserved and warnings returned; the description remains available as source text. Review these warnings when published fees change.
- Omitted/null/empty fields preserve existing knowledge. A nonempty repeater is a complete replacement of that repeater, so the sender must send the complete reviewed list. Incomplete FAQs reject the update.
- Explicit `clear_fields` removes named scalar/repeater values. It cannot clear names, slugs, IDs or relationships. Extraction gaps must not automatically generate clears.
- Moving an existing course/specialization between parents, claiming an already-linked row, or using an already-linked canonical URL path fails rather than moving/overwriting unrelated catalog records.

## Query behavior and performance

No parser/WordPress requests or indexing run in the chat request. Existing fee/eligibility/recommendation tools continue to query the structured catalog. When integration is enabled, the additional `search_page_details_tool` uses scoped PostgreSQL full-text search for detailed page questions. It returns up to four excerpts of at most 1,600 characters each, with source URL, version and update timestamp. It requires resolved university/course/specialization context and cannot search another university's content through a mismatched parent.

HTML is converted to text for indexing; scripts/styles and media fields are excluded. This searches imported text, not PDF contents, images or unprovided page sections. Retrieval is lexical with English stemming, not semantic embeddings. Synonyms without matching indexed terms may need another keyword; live-model tool selection and answer quality still need staging verification. Retrieved text is explicitly treated as reference data, not instructions.

All app processes may run a catalog worker, but a PostgreSQL advisory transaction lock permits one import at a time across processes. Work uses one pooled connection, statement/lock timeouts and a 15-second import timeout, and rolls back on process interruption. Cache revision polling batches refreshes per process every two seconds; no revision read is added to each chat. Imports may be visible in SQL before all caches refresh. Configured deployments add one indexed page-path lookup when resolving widget page context. Imports share CPU/database resources with chats; production performance must still be measured.

Local synthetic check (2026-10-10): 800 pages (1 university + 799 courses), 7,999 indexed sections, 300 probes at concurrency 5. Each probe performed an existing fee lookup and a scoped section search. Median/p95 were 1.44/1.93 ms without imports and 1.63/4.61 ms during 100 background updates. Initial enqueue + import took 9.33 seconds. This was local Docker PostgreSQL with synthetic text, warmed queries, and no HTTP, resolver, guard or LLM; these numbers do **not** predict deployed chatbot response time. Reproduce with `TEST_DATABASE_URL=<disposable *_test database> .venv/bin/python tests/benchmark_catalog.py`.

## Operator APIs

All require existing chatbot `Authorization: Bearer <ADMIN_AUTH_TOKEN>`:

- `GET /api/admin/catalog/events?limit=50`: recent receipt status, safe errors and warnings; no raw payloads.
- `POST /api/admin/catalog/events/{event_id}/retry`: requeue a failed event after resolving its issue.
- `GET /api/admin/catalog/entities?entity_type=university&limit=100&offset=0`: review existing rows before adoption/backfill. Also supports course/specialization, with parent IDs. Maximum 200 rows per page.

There is no new chatbot admin UI panel; these controls are API endpoints. The parser prompt requests its own sync UI.

## Current boundaries

Version 1 supports published upserts for one configured WordPress site. It does not synchronize deletions/unpublishing, direct WordPress edits, blogs/categories, or automatically crawl/backfill pages absent from the parser. Do not use draft/private/deleted changes as a withdrawal mechanism: existing chatbot records remain until separately handled. Report those operations as unsupported, not synced. A coordinated withdrawal extension is required before a workflow relying on automatic withdrawal goes live.

Events are retained as an audit trail; plan database retention/backup policy before sustained production use. Disabling the secret stops new receipts/imports and page-path integration, but does not remove imported catalog knowledge or queued events. Roll back the deployment only with awareness that imported SQL catalog updates persist; take normal DB backups before bulk imports.

Validation: unit tests cover signatures, schema, preservation, fee ambiguity and text bounds; real PostgreSQL tests exercise signed HTTP receipts/status, imports, structured tools, page context, retrieval scoping, concurrency, retries, versions, adopted legacy rows and rollback. No live WordPress, parser, production database or model request is part of those checks.

Final local verification: 215 Python tests passed against the isolated PostgreSQL test container. Startup, signed receipt/status, real background import, cache refresh and shutdown passed using the cached chatbot container runtime with the updated source mounted read-only. A fresh Docker build was attempted but Docker Hub timed out fetching base-image metadata; a fresh image build remains to be verified when registry access is available. No dependencies or Dockerfile changes were required for this integration.
