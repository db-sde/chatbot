# Chatbot + Parser launch checklist

Prepared 2026-10-17 from both local codebases. The parser repository documents Render for its backend and Vercel for its frontend; confirm your actual dashboard settings before using these instructions. This is a runbook, not evidence that either deployment has been updated. No deployment, production data changes or live messages were performed while preparing it.

Use this order: prepare/protect/back up → verify code → configure/deploy chatbot → configure/deploy parser → deploy parser frontend → link/review content → test → backfill.

## 1. Record the actual deployments and repositories

Write down:

- Chatbot HTTPS origin, deployment repo/branch, runtime and chatbot PostgreSQL database.
- Parser backend HTTPS origin, deployment repo/branch and parser PostgreSQL database.
- Parser frontend origin and Vercel production branch/root directory.
- The single WordPress site whose post IDs will be used.

Local remotes currently are:

| Checkout | Remote | Repository |
|---|---|---|
| Chatbot DB | origin | db-sde/chatbot |
| DEGREEBABA PARSER | db-sde | db-sde/micro-app |
| DEGREEBABA PARSER | origin | IshanMaheshwari-777/DegreeBaba-parser-project |

Both checkouts are on `main` and contain uncommitted changes. Confirm which parser remote each host deploys; Render and Vercel may be connected to different repos. Pushing only to the other remote will not update them.

Pause new publishing and backfills during initial setup/mapping review. For this rollout, use manual deploys or CI-gated deploys. Render supports Settings → Auto-Deploy → Off / After CI Checks Pass. The parser repo has an optional deploy-hook workflow; do not assume it is active without checking its secrets and the host configuration. [Render deploy documentation](https://render.com/docs/deploys).

## 2. Back up and isolate staging

- Take a restorable backup/snapshot of each app's existing PostgreSQL database.
- Keep original DOCX files and a normal WordPress backup.
- Back up the parser's existing recovery journal if one exists.
- Keep each app on its own intended database; do not point chatbot DATABASE_URL at the parser database to connect them. The webhook connects them.
- For staging, use separate app/database/outbox state and staging-specific secrets. Do not temporarily aim the production parser at a staging chatbot: the parser pins its WordPress site and chatbot destination after activation.
- Never reset/delete production version counters or outbox tables to get past a conflict. Receiver versions survive redeploys.

Success: you can identify and restore the databases, and staging cannot overwrite the production chatbot catalog.

## 3. Protect the parser's operator API

The inspected parser publishing and catalog routes do not enforce application login/authentication. The webhook secret authenticates the parser to the chatbot; it does not protect access to the parser.

Before public operation, use an existing operator-only access layer that protects BOTH frontend and backend, including direct `onrender.com` access, or have the parser coding agent add backend-enforced operator authentication and corresponding frontend session handling. Protecting only the Vercel page or hiding buttons is insufficient. There is no existing parser AUTH_TOKEN environment switch that fixes this.

Engineering prompt if needed:

> Add backend-enforced operator authentication to the parser's upload/edit/publish/history/catalog/backfill/reconciliation APIs and compatible frontend session handling. Protect direct backend-origin access as well as the frontend. Keep public health checks appropriately limited. Use server-validated sessions or our existing identity/access system, explicit allowed origins and secure session behavior. Do not bake a shared administrator secret into Vite assets. Test anonymous refusal, authorized workflows and WordPress/catalog compatibility without live external HTTP. Do not deploy automatically.

Success: an unauthenticated direct request cannot publish, edit, reconcile, retry, backfill or read operator data.

## 4. Set up hosting and durable storage

Use an always-running backend configuration for sustained syncing and predictable first replies. Render Free web services sleep after 15 minutes without inbound traffic and cannot attach a persistent disk; the parser's outbound worker does not provide a guarantee that a sleeping process keeps running. [Render free-service limitations](https://render.com/docs/free).

For the parser on Render:

- Use a paid web service with one instance initially.
- Attach a persistent disk mounted at `/var/data`.
- Set `CATALOG_RECOVERY_DIR=/var/data/catalog-recovery`.
- Keep that directory private and outside `/uploads` or any static directory.
- Keep PostgreSQL as the durable source for publications, events and counters.
- Keep Cloudinary/WordPress media configured; the new journal directory does not make the parser's separate local `/uploads` directory persistent. Do not rely on fallback local image URLs across redeploys.

Render disks are limited to one service instance and remove zero-downtime deploys; schedule parser deploys around bulk processing. Only files under the disk mount persist. [Render persistent disks](https://render.com/docs/disks).

Start the chatbot with one app process/instance too; scale after staging concurrency/latency checks. The chatbot catalog needs PostgreSQL, not a new local recovery disk. The parser and chatbot workers run inside their existing backend services; no separate Redis/Celery service is needed for this integration.

## 5. Generate and store secrets

Run this locally for a new catalog secret. Run it a second time only if you need to configure a new chatbot admin token; an existing strong, separate admin token can remain. Store the values separately in your password manager:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

- Output 1: shared catalog secret, identical on the two backends.
- Optional output 2: chatbot admin token, different from the shared catalog secret.

Keep existing provider, database and WordPress credentials server-only. Do not put the catalog/admin secrets in Vercel frontend variables, Git, browser JavaScript, DOCX content or shared screenshots.

## 6. Validate, commit and push the actual changes

Chatbot, from its repository root:

```bash
cd "/Users/ishanmaheshwari1/Desktop/Chatbot DB"
uv sync --all-packages --frozen
.venv/bin/python -m pytest tests -q
npm ci --prefix admin
npm run lint --prefix admin
npm run build --prefix admin
node --check widget/widget.js
```

The test run above skips real database integration tests unless TEST_DATABASE_URL is supplied. To run the full chatbot suite locally with Docker, create a separate disposable DB (the example port is 25434, not the existing local services' 5433):

```bash
docker run -d --name degreebaba-launch-test -e POSTGRES_DB=degreebaba_ai_test -e POSTGRES_PASSWORD=launch_test_only -p 127.0.0.1:25434:5432 pgvector/pgvector:pg16
docker exec degreebaba-launch-test pg_isready -U postgres -d degreebaba_ai_test
```

Wait until the second command reports accepting connections, then:

```bash
TEST_DATABASE_URL=postgresql://postgres:launch_test_only@127.0.0.1:25434/degreebaba_ai_test .venv/bin/python -m pytest tests -q
docker rm -f -v degreebaba-launch-test
```

Use a free local port if 25434 is occupied. Do not use production DATABASE_URL for tests. The last full verified run here was 215 passing tests. The fresh Docker build previously timed out fetching base-image metadata; require a successful fresh build/deploy for this release.

Parser, from its repository root, using Python 3.12 and a dedicated environment (uv is already used by the chatbot):

```bash
cd "/Users/ishanmaheshwari1/Desktop/DEGREEBABA PARSER"
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r backend/requirements-dev.txt
.venv/bin/python -m pytest -q backend/tests
.venv/bin/ruff check backend
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
```

If an environment already exists, reuse it instead of recreating it. Parser tests scrub credentials and use disposable SQLite; do not bypass their safety fixtures. Its PostgreSQL concurrency behavior still needs a disposable staging PostgreSQL test before bulk activation:

> Add/run integration tests against a disposable PostgreSQL database for concurrent version allocation on the same WordPress post, a single global sender lease across independent sessions/processes, expired-lease recovery, stale sender results, transaction rollback and restart resumption. Mock WordPress/chatbot HTTP and block external calls. Test that failures cannot fall back to a separate SQLite version history. Do not use production DB credentials or reset production counters.

In each checkout, after checks pass:

```bash
git status --short
git diff --check
git add -A
git diff --cached --name-only
git diff --cached --stat
git commit -m "Add durable parser chatbot catalog integration"
```

Review the staged list before committing: include the new catalog modules/migrations and built chatbot admin assets; exclude .env files, database files, journals, caches and node_modules. On chatbot push with `git push origin main`. On parser use `git push REMOTE_NAME main`, replacing REMOTE_NAME with the deployment-connected remote from step 1. If the hosts intentionally use both parser repos, both need the same tested commit; do not force-push.

## 7. Configure and deploy the chatbot first

In the chatbot backend environment, preserve existing valid settings and add/update:

```dotenv
CATALOG_WEBHOOK_SECRET=YOUR_SHARED_CATALOG_SECRET
CATALOG_SOURCE_HOSTS=degreebaba.com,www.degreebaba.com
ADMIN_AUTH_TOKEN=YOUR_SEPARATE_ADMIN_TOKEN
ALLOWED_SITE_KEYS={"degreebaba_prod":["degreebaba.com","www.degreebaba.com"]}
```

These are placeholders, not literal values. Preserve additional site keys/domains already used by working widgets/staging. CATALOG_SOURCE_HOSTS contains public content hosts, not parser/chatbot service hosts.

Also verify:

- DATABASE_URL is the chatbot PostgreSQL DB; the migration user can create required tables/extensions (`vector`, `pgcrypto`, `pg_trgm`).
- PROVIDER and its real corresponding API key remain valid. Default Groq uses GROQ_API_KEY; OpenAI/DeepSeek use their own selected keys.
- TRUSTED_PROXIES names your verified immediate proxy addresses; `*` is rejected. Have your host/operator determine them; do not invent a Render proxy IP. Check two client IPs aren't sharing one rate limit unexpectedly.
- Keep CRM_WEBHOOK_URL only if you use the existing CRM integration; it is unrelated to incoming parser content.

For the supplied Docker deployment: repository root is the build context, Dockerfile path is `backend/Dockerfile`, and the default Docker command handles PORT. Do not use backend/ as the build context. The admin assets must already have been rebuilt and committed. If your service uses an existing native runtime, keep its working setup while ensuring imports, root assets and new modules are included.

Deploy this tested commit with the new environment. Startup applies migrations; confirm `0003_catalog_sync.sql` was applied/already recorded and no DB/worker errors appear. Do not run seed_database.py or sample fixture imports on the live catalog.

Open `https://YOUR_CHATBOT_HOST/health` and `/admin`. Health should respond HTTP 200; admin data should load with your admin token. Health alone does not verify models, migration completeness or imports. An unsigned request to the catalog receiver returning 401 is normal.

Render environment changes only take effect on deploy; use Save and deploy/rebuild as appropriate, not Save only and then assume the running app changed. [Render environment settings](https://render.com/docs/configure-environment-variables).

## 8. Configure/deploy the parser backend, then frontend

Parser backend environment:

```dotenv
CHATBOT_BASE_URL=https://YOUR_CHATBOT_HOST
CHATBOT_CATALOG_WEBHOOK_SECRET=YOUR_SHARED_CATALOG_SECRET
CHATBOT_CATALOG_SOURCE_HOSTS=degreebaba.com,www.degreebaba.com
CATALOG_RECOVERY_DIR=/var/data/catalog-recovery
APP_ENV=production
```

Use the same host list and secret as the chatbot. CHATBOT_BASE_URL is its final HTTPS origin without `/webhook/catalog`, query, fragment or path prefix. Keep it stable after activation: changing destination/site on an existing source requires a planned migration.

Before enabling these variables, inventory existing pending jobs/recovery journals and their reviewed mappings. The worker can resume them immediately on startup. If review is needed, first deploy this parser code/frontend with chatbot delivery variables blank, keep publishing paused, reconcile/review mappings, then enable delivery. Retain journals; do not delete remote-success recovery records.

Preserve the parser's existing correct DATABASE_URL (PostgreSQL), WORDPRESS_SITE_URL, WORDPRESS_APP_USER, WORDPRESS_APP_PASSWORD, OPENAI_API_KEY, ANTHROPIC_API_KEY and media configuration. Do not replace production values with template placeholders. WordPress Application Passwords stay on the parser backend.

For a Python Render service rooted at backend/:

```text
Build: pip install -r requirements.txt
Start: uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1
Health: /health
```

Use a single app process for initial parser table creation; migrations use create_all and are not serialized across multiple starting processes. Start production without --reload. Bind to Render's assigned PORT. [Render web-service requirements](https://render.com/docs/web-services).

Verify backend `/health`, catalog table creation, PostgreSQL connection, worker startup, and disk directory writability/private access. A PostgreSQL connection failure with sync enabled should stop startup; fix it, do not work around it with a fresh SQLite outbox.

Vercel parser frontend:

```dotenv
VITE_API_BASE=https://YOUR_PARSER_BACKEND_HOST
```

Set the appropriate Production environment, root directory `frontend`, build `npm run build`, output `dist`, and deploy the updated frontend commit. VITE_API_BASE is the parser backend, not chatbot and not an extra `/api` prefix unless a verified proxy strips it. The current vercel.json provides SPA fallback, not an API proxy. Redeploy after changing the variable. [Vercel environment variables](https://vercel.com/docs/environment-variables).

Verify the History page shows the chatbot backfill panel and upload validation shows catalog mapping/status. An old frontend build will not show these controls.

## 9. Review/link existing published content before backfill

If existing chatbot rows contain demo/synthetic facts, review them before adopting those rows: omitted/empty values preserve old details, so synthetic leftovers must be overwritten or explicitly cleared under review.

Choose one real published university, one course under it, and one specialization under that course. Prefer already-published, approved pages; linking them does not need another WordPress publication.

For each legacy upload, university first:

1. Open its Validation page → expand “Review mapping, explicit removals and existing WordPress references”.
2. Compare the original DOCX/reviewed upload with the current live page. Direct WordPress edits are not fetched as full content automatically.
3. Enter the existing WordPress post ID (the `post=123` value in the edit URL), not an upload ID or chatbot row ID.
4. Approve the content review and click “Read WordPress references for review”. This reads real IDs/status/canonical URL and relationships; it does not republish or enqueue.
5. Check whether it already exists in the chatbot. From the chatbot /admin page with your admin token set, browser Developer Tools → Console can make the same-origin authenticated request without exposing the token in source:

```javascript
{
  const response = await fetch('/api/admin/catalog/entities?entity_type=university&limit=100&offset=0', {
    headers: { Authorization: 'Bearer ' + localStorage.getItem('db_admin_token') }
  });
  console.table(await response.json());
}
```

Use entity_type=course/specialization for those records, and increment offset to review further pages. Compare names and parent IDs. If no token is saved yet, log in to /admin first. Do not paste untrusted console scripts or share console output containing tokens.

6. If the chatbot already has that same entity, enter its exact reviewed slug in “Reviewed catalog slug”. If it is new, leave the slug empty. Mapping must be set before first delivery to avoid a parallel duplicate entry.
7. Leave “Explicit fields to clear” blank unless you intentionally want to remove those fields; never infer removals from missing extraction. Save per-post settings.
8. Click “Retry catalog sync” and wait for “synced” before doing the dependent course/specialization. Fix warnings/missing parent IDs instead of creating duplicate WordPress pages.

New approved pages follow the normal publish flow: choose actual publish status (draft is the default), review any existing-catalog mapping in the publish modal BEFORE first publication, and publish once. WordPress success and chatbot sync are independent statuses.

## 10. Acceptance checks before all 800 pages

- The three linked pages reach synced; their receiver events show applied. 200/202 acceptance alone is insufficient.
- Ask about total fee, eligibility, exam/syllabus detail and the correct university/course relationship; compare against the reviewed published source.
- Ask the same course name under another university; verify it is not answered with the first university's data.
- Verify source links on answers using page sections and incremental streaming in the browser.
- Save/reload a conversation; check follow-up context, comparison and recommendation behavior.
- On staging, change one published detail, sync a new version and verify the answer changes. Existing empty/unprovided details should remain; explicit clears should remove the intended field.
- On staging, retry a receipt and restart the services while jobs exist; verify no duplicate rows/posts and durable resumption. Keep any WordPress write test on a controlled approved page/environment.
- The parser PostgreSQL lease/version tests pass. The recovery directory persists across parser restart/redeploy.
- Measure first visible text and full answer time before/during imports, including after idle. The earlier 800-page check measured database work only, not complete model response time.
- If you use CRM, send a clearly marked test callback through the widget and confirm lead save/delivery once. The CRM receiver should honor the delivery Idempotency-Key.

A Synced label confirms ingestion, not source accuracy or live-model answer quality. Review unparsed_total_fee/unparsed_starting_fee warnings: a per-semester/range description may leave the previous numeric fee in place. Correct reviewed content and publish a new version rather than treating the warning as harmless.

## 11. Backfill and connect the WordPress widget

History → Chatbot catalog backfill → Preview / dry-run. Review the counts and blocked records, reconcile old content and parents, save mappings, then approve and Start resumable backfill. There is no batch-size picker currently; if you want a selected subset, sync those uploads individually before using the full ready-record backfill. Inspect a small set before starting all ready posts.

The sender waits for universities → courses → specializations to apply. Monitor failures until resolved. Backfill covers local saved publications/reviewed imports only; keep an inventory of the desired 800 WordPress URLs and identify pages/documents not present in the parser. It is not a WordPress crawler. Do not republish merely to retry a chatbot failure.

If the public widget is already installed, verify its source/API/site key instead of adding a duplicate. Otherwise use your normal WordPress footer/header script integration with:

```html
<script
  src="https://YOUR_CHATBOT_HOST/widget.js"
  data-api-base="https://YOUR_CHATBOT_HOST"
  data-site-key="degreebaba_prod"
  defer>
</script>
```

Replace the hostname with your deployment; the site key must exist in ALLOWED_SITE_KEYS for the actual page domain. The key is a public site identifier, not the catalog/admin secret. Clear WordPress/CDN/browser widget caches after updating the script and confirm only one widget loads. Test desktop/mobile on university, course and specialization pages. The current admin embed snippet omits the explicit site key/API base; use the explicit verified version above for this configuration.

## 12. Monitoring, limits and recovery

- Parser History/Validation: queued/syncing/synced/failed, warnings, missing parents.
- Chatbot admin API `/api/admin/catalog/events?limit=50`: import status and safe errors. There is no dedicated chatbot catalog UI panel yet.
- Host/DB dashboard: connection usage, CPU, memory, response latency and errors. Review provider usage and the chatbot's rate/daily message limits against real traffic.
- Schedule backups of both databases and the parser journal; retain source DOCX files. Plan retention for growing receipt history without deleting source version identity/counters.
- Keep one WordPress site and stable chatbot destination per source. Restoring old parser DB state while retaining newer receiver versions requires reconciliation, not resets.
- Published upserts only: draft/private/deleted changes do not withdraw chatbot knowledge; direct WordPress edits are not automatically synced. If withdrawal is part of your workflow, a coordinated receiver/sender change is still engineering work before relying on it. Blogs/categories, image/PDF understanding and automatic model training are not provided by this connection.
- To pause delivery, remove/blank parser chatbot configuration and deploy. Already accepted receiver jobs may still apply. Disabling chatbot CATALOG_WEBHOOK_SECRET and redeploying stops receiver workers/new authenticated receipts too, but does not erase imported content or pending jobs.
- Roll back app code if needed while retaining additive tables, event IDs, counters and backups. A code rollback does not undo catalog data updates; do not run destructive SQL cleanup as a retry mechanism.

Quick diagnosis:

| Symptom | Check/action |
|---|---|
| not configured / receiver 503 | Secret/origin variables present on backend, >=32-character secret, new deployment actually active |
| 401 | Shared secret, current clock, exact method/path and raw bytes; signed requests should come from the sender |
| 403 in widget | Correct public site key and ALLOWED_SITE_KEYS domain |
| POST 404 | Updated receiver code deployed and correct chatbot origin/path |
| 409 | Inspect stable source IDs, versions and reviewed slug/source binding; do not reset tables |
| 422 | Canonical HTTPS URL/allowed content host, schema and required parent fields |
| queued/syncing indefinitely | Parent must apply, worker/process running, backend not sleeping, database healthy |
| failed import | Read safe last_error; correct data/relationships and create a new version through the parser |
| missing page details | Correct entity/page context, imported text actually present, focused keyword retrieval; some facts may not have matching text |

Launch is ready when the deployed commits/configuration are verified, operator access and persistent recovery are in place, database/staging checks pass, reviewed content reaches applied and the real widget answers correctly under expected load.
