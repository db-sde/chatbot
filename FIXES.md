# Verified local fixes

9 October 2026. Changes are local; nothing has been pushed or deployed. This follows the original [codebase review](CODEBASE_REVIEW.md).

## Changes

- **Admin file serving:** resolve and contain requested paths inside `admin/dist`, including symlinks. Valid assets and SPA navigation still work; encoded traversal returns 404.
- **Admin configuration:** reject blank/default admin tokens while retaining configured-token authentication. Reject wildcard proxy entries even inside a comma-separated list. CORS now matches configured wildcard/subdomain rules and supports authenticated admin PUT/DELETE preflights.
- **Ingestion:** remove the search-index write to the nonexistent embedding column. Repeated inserts and updates work on the actual schema. Share rupee parsing between ingestion and conversational budgets, including commas, decimals, lakh/lac, crore, and k/thousand units.
- **Entity scope:** establish the effective session/page university before course and specialization matching. Scoped misses cannot fall back to another institution. Saved course context scopes specialization follow-ups. The widget sends its pathname, and verified page course/spec context reaches resolution. Existing precedence and catalog-wide behavior are preserved.
- **Answer correctness:** single-university templates defer multi-university requests to the existing agent/tool path. A missing requested course/spec cannot be presented as the university's starting fee. Recommendations retain exact course slugs so “Compare these programs” can use the saved shortlist. The recommendation filters, ordering, and selection algorithm remain unchanged.
- **Contact intent:** negated contact requests and informational counselling questions no longer automatically trigger the contact shortcut; positive requests continue to work.
- **Lead form:** display configured title/description as text; confirm only after a successful save; retain inputs and allow retry on errors; disable duplicate in-flight submissions; reuse a submission ID for retries.
- **Lead storage:** keep optional email optional, create progressive callbacks after name and phone, update later fields on the same progressive lead, and preserve independently submitted full forms. Row locks and JSON merges prevent simultaneous contact saves or stale chat profiles from dropping contact fields.
- **CRM:** atomically queue configured deliveries with the lead save. A PostgreSQL outbox worker checks HTTP errors, retries with backoff, uses stable idempotency headers, claims work safely across workers, and recovers expired claims. Admin status reflects recorded delivery state. Visitor requests no longer wait for CRM network calls.
- **Security audit:** establish a site-scoped session before flagging a blocked first message. Audit failures do not replace guard/policy refusals. Progressive submissions enforce the blocked-IP check.
- **Telemetry:** parallel tools append to a per-turn collector visible to the parent; independent turns remain isolated. Match measurements to tool names/arguments rather than completion order. Record deterministic lookup entries. Background scoring uses a separate metrics context. Greeting/contact TTFT includes pre-graph waiting and is persisted instead of always reporting zero.
- **Knowledge gaps:** record known direct-route misses, unknown/partial entities, and empty recommendation matches without changing successful answers. Replace the admin's claim of a complete database with an accurate empty-log message.
- **Catalog filtering:** compare NAAC grades by explicit rank rather than string order.
- **Deployment:** build the uv workspace from the root, preserve dependencies outside bind mounts, package widget/admin assets, and wait for database health. Keep existing `DATABASE_URL` configuration, including external databases. Load `.env` independently of the working directory. Export runtime requirements from the existing lock without changing model/provider dependencies.
- **Migrations/shutdown:** apply legacy columns before dependent indexes, serialize simultaneous migrations, and drain retained background work before closing the pool. Add an additive lead/outbox migration.
- **Admin/CI/docs:** fix lint errors, cancel stale Security-page fetch updates, rebuild committed dashboard assets, correct setup/API instructions, use frozen dependencies in CI, and explicitly run database tests against the CI test database.

## Verification

| Check | Result |
|---|---|
| Complete Python suite with isolated PostgreSQL database | **191 passed** |
| Fresh schema and repeated catalog ingestion | Passed |
| Existing-schema upgrade with missing columns/indexes | Passed; message data retained |
| Concurrent progressive saves and stale chat-profile write | Passed; all contact fields retained, one progressive lead |
| Full-form retry idempotency and distinct submissions | Passed |
| CRM HTTP 500 retry, successful delivery, concurrent claims, expired claim recovery | Passed with mocked HTTP; no real CRM contacted |
| Browser widget regression in separate headless Chrome | Passed: safe settings rendering, pathname, save failure/retry, stable submission ID, confirmed success |
| Admin ESLint and production build | Passed; committed assets rebuilt |
| Docker image build | Passed with locked runtime dependencies |
| Container startup | Passed against the disposable database |
| Container HTTP smoke checks | Health, widget, admin SPA, authenticated settings, wildcard CORS passed; traversal blocked |
| Compose-style source mounts | Dependencies and packaged static assets remained available |

Python regressions include the original 140 offline cases plus new targeted tests and expanded database coverage. All application/test database activity used synthetic records in a disposable local PostgreSQL 17.6 database with pgvector, pgcrypto and pg_trgm. CI retains PostgreSQL 16. No production data or paid/provider API calls were used.

## Release and delivery semantics

Use a configured non-default `ADMIN_AUTH_TOKEN`. Run migrations before serving the updated backend; API startup already does this. `0002_lead_delivery.sql` adds the outbox and keyed submission index without deleting existing leads. Deploy backend, widget, and rebuilt admin assets together.

A successful lead response confirms durable local saving/queuing. CRM delivery happens asynchronously and is **at least once**, not exactly once. Receivers should honor `Idempotency-Key`; a crash after remote acceptance but before recording success can require a retry. Later progressive field updates can produce another delivery containing the updated contact. Jobs retain their configured destination, and the worker runs when CRM delivery is enabled. Historical leads are not automatically resent.

## Deliberately retained behavior and limitations

The selected providers/models, answer token limits, streaming, tool limits, recommendation funnel, and catalog-selection algorithm were preserved. No shorter-answer shortcut, lower-quality model substitution, reduced retrieval coverage, or new timeout on successful chat work was introduced.

These repairs do not claim zero regression risk or production latency improvements. Real provider answer quality, production throughput, actual student-facing data, and external CRM compatibility were not exercised. The browser test mocks HTTP; the database and container tests cover the server separately.

Remaining review items need broader product or deployment decisions: buffering policy for streamed output, verified catalog provenance and synthetic-data replacement, distributed session/rate-limit/cache coordination, atomic daily-cap semantics, complete persisted end-to-end latency/usage attribution, admin-wide pagination/search, provider readiness probes, and a durable knowledge-approval/learning workflow. The app still retrieves and remembers catalog/context information; these changes do not add model training. Existing graph response-time measurements retain their documented scope and do not include every final persistence/network-delivery step.
