# Prompt to give the coding agent working on DEGREEBABA PARSER

Implement the parser side of the DegreeBaba chatbot integration in this app. The chatbot receiver is already implemented in `/Users/ishanmaheshwari1/Desktop/Chatbot DB`. Read that repository's `CATALOG_SYNC.md`, `backend/catalog/schema.py`, and `backend/catalog/routes.py` as the exact contract before coding. Work in the parser app; preserve its current extraction, editing, image/brochure, bulk-processing and WordPress publishing behavior. Do not push or deploy automatically. Test with mocked WordPress/chatbot requests and an isolated test database, not production credentials or paid AI calls.

## What to build

1. Add server-only configuration:
   - `CHATBOT_BASE_URL`: the chatbot origin, e.g. `https://your-chatbot-host` (no path prefix).
   - `CHATBOT_CATALOG_WEBHOOK_SECRET`: the same separate random secret configured as `CATALOG_WEBHOOK_SECRET` in the chatbot, at least 32 characters. Never expose it in frontend code, responses or logs.
   - Leave integration disabled when these are absent, preserving the existing publish behavior. Use HTTPS in production; permit localhost HTTP only for development. Do not allow browser callers to supply arbitrary webhook destinations.

2. Add a durable SQLAlchemy outbox and per-WordPress-post sync state using additive migrations compatible with the parser's existing database initialization. Do not use FastAPI BackgroundTasks or an in-memory queue as the sole durable record. Key identity by `(WordPress site, page_type, wp_post_id)`, not upload ID or document filename; two uploads updating the same WordPress post must share the version counter. Allocate increasing integer versions atomically under a database lock. Use a UUID event ID and persist the exact serialized UTF-8 request bytes before sending; retries must reuse the same event ID, version and content. Store only references/IDs in logs.

3. Integrate at `backend/main.py`'s `publish_to_wordpress` after `wordpress_client.publish_payload` succeeds. Save the outbox job in the same local DB transaction as the saved WordPress references. Do not make a chatbot HTTP call inside the WordPress publishing request. WordPress success must remain success when the chatbot is offline. Provide reconciliation/retry for a local outbox enqueue failure after a successful remote WordPress operation, without creating another WordPress post.

4. Send only published (`result['status'] == 'publish'`) university, course and specialization pages. Drafts, private posts, failed publications, blogs and category pages do not qualify for this version of the integration. If relationship IDs or the canonical URL cannot be resolved, show an actionable sync error and keep WordPress publication successful; do not guess a parent.

5. Return and persist the real resolved `linked_university` / `linked_course` WordPress IDs already calculated inside `backend/pipeline/wordpress_client.py`'s `publish_payload`. Its current return object does not include them. Add return metadata while preserving existing keys, the create-then-ACF-update flow, taxonomy behavior and warnings. Do not rely on the original payload's relationship fields: `formatter.py` deliberately sets them to null and stores friendly-name hints in `_meta.relationship_hints`. Friendly names are not stable IDs.

6. Construct the following event using the approved original ACF payload, before WordPress-specific renaming/dropping/coercion. Send complete repeater arrays, not partial repeater patches. The chatbot maps the supported fields and indexes extra page text. Do not send document binary data, private upload metadata, access tokens or application passwords. `source_id` and parent IDs are strings containing WordPress post IDs. `version` is a positive integer. `source_url` is the final public HTTPS canonical URL, on an allowed chatbot source host, without credentials, query string or fragment.

```json
{
  "schema_version": 1,
  "event_id": "622049bd-6927-4b5a-9bd6-df5a44f49cf5",
  "source": "degreebaba-parser",
  "entity_type": "course",
  "source_id": "202",
  "version": 1,
  "publication_status": "publish",
  "source_url": "https://degreebaba.com/colleges/example/online-mba/",
  "university_source_id": "101",
  "data": {
    "program_name": "Online MBA",
    "duration": "2 years",
    "total_fee": "₹1,20,000",
    "eligibility_content": [
      {"eligibility_title": "Qualification", "eligibility_description": "Graduation from a recognized university"}
    ],
    "exam_content": "Published exam details",
    "faqs": [{"question": "How are exams conducted?", "answer": "Published answer"}]
  },
  "clear_fields": []
}
```

University events omit both parent IDs. Course events require `university_source_id` and omit `course_source_id`. Specialization events require both `university_source_id` and `course_source_id`; both must resolve to the same university. Never substitute upload IDs, friendly names, taxonomy IDs or chatbot database IDs for WordPress IDs.

Omitted fields, nulls, empty strings and empty arrays preserve existing chatbot values. A nonempty repeater replaces that whole repeater, so send its complete reviewed list. Only explicit user-approved removals go in `clear_fields`, e.g. `["about_content", "faqs"]`. Never automatically infer removals from extraction gaps. Entity names, IDs, slugs and relationships cannot be cleared. Never place routing fields inside `data` expecting them to control identity.

Optional `catalog_slug` links an existing chatbot record, e.g. `"nmims"`, after manual review. Provide a per-post configuration/UI field for this. Leave it absent for new entities; the receiver generates a stable unique slug and returns it in status. Do not invent slugs from names to adopt existing records. Before the initial backfill, review mappings to existing universities/courses to avoid parallel duplicate catalog entries. Existing records can be listed with the chatbot's admin-authenticated `GET /api/admin/catalog/entities?entity_type=university&limit=100&offset=0` (course/specialization also supported); use an operator's admin session for this review, not an admin token embedded in the parser frontend or runtime sender.

7. Implement signing exactly:
   - POST destination path: `/webhook/catalog` (no trailing slash).
   - `X-Catalog-Timestamp`: current Unix seconds as a decimal string.
   - `X-Catalog-Signature`: `sha256=` plus lowercase HMAC-SHA256 hex.
   - Signed bytes: `timestamp + '.' + UPPERCASE_HTTP_METHOD + '.' + URL_PATH + '.'`, UTF-8 encoded, followed by the exact raw request-body bytes.
   - `Content-Type: application/json`.
   - On each retry generate a fresh timestamp/signature, reusing the stored request bytes.
   - The receiver permits at most 2 MiB per event and a 300-second timestamp skew. Keep machine clocks synchronized. The signature covers the method and path; do not let redirects change either. Use timeouts and do not follow redirects silently.

Example signing helper (adapt to the project's conventions):

```python
import hashlib
import hmac
import time

def signed_headers(secret, method, path, body=b''):
    timestamp = str(int(time.time()))
    message = f'{timestamp}.{method.upper()}.{path}.'.encode('utf-8') + body
    signature = hmac.new(secret.encode('utf-8'), message, hashlib.sha256).hexdigest()
    return {
        'Content-Type': 'application/json',
        'X-Catalog-Timestamp': timestamp,
        'X-Catalog-Signature': 'sha256=' + signature,
    }
```

8. Worker behavior:
   - Use database locking/leases to avoid concurrent sends of the same job. Recover abandoned jobs after restarts. Bound concurrency (start with one sender) and use exponential backoff with jitter for network failures, 429 and 5xx responses.
   - POST returns 202 for a new durable receipt or 200 for an identical duplicate. Neither alone means the content is synced. Persist the event ID and poll `GET /webhook/catalog/{event_id}` with the same signing scheme, GET method and empty body.
   - `queued`: poll later, with bounded backoff, without blocking the UI. Receiver import retries missing parents/transient errors up to ten times.
   - `applied`: mark synced, record `entity_slug`, show any `warnings` (e.g. a fee description couldn't be safely converted to a numeric total).
   - `ignored`: a newer/equal source version is already stored; mark this job superseded and verify the latest version is synced. Do not create another event to force an older snapshot over it.
   - `failed`: show `last_error`, allow correction and a NEW version/event. Do not mark synced or mutate/resend conflicting old event content.
   - 401: configuration/signature/clock error; 409: event/version conflict; 413: payload too large; 422: schema/source-host error. Surface these for correction, do not retry aggressively.
   - For receipt status 404, resend the SAME stored POST event and resume polling. Keep delivery and applied status distinct.
   - Admin retry for an unchanged failed receiver job exists at `/api/admin/catalog/events/{event_id}/retry`, protected by chatbot admin auth. The parser worker must not require or store that admin token.

9. Add parser UI status for each upload/post: not configured, not eligible/draft, queued, syncing, synced, superseded, or failed, with last safe error and retry action. Preserve existing WordPress success/error presentation. Provide a bulk backfill with preview/dry-run, counts and resumable progress: published universities first, then courses, then specializations. Wait for parent application before sending dependent records. Deduplicate by WordPress post ID, preserve version ordering across imports/restarts, and do not republish WordPress just to backfill the chatbot. Identify missing parent records and offer importing/syncing them first. The parser does not necessarily contain all previously published WordPress pages; report coverage accurately.

10. Contract limits to show clearly: this receiver currently supports published upserts only. It does not automatically withdraw/delete records when WordPress content becomes draft/private/deleted, nor observe direct edits in WordPress. Do not claim those are supported or silently mark such operations as synced. Flag these cases for operator action; a withdrawal/reconciliation extension needs coordinated receiver support before release if the publishing workflow depends on it. It is one configured WordPress site per chatbot source; do not combine unrelated sites whose post IDs overlap.

## Validation and delivery

Add meaningful tests for successful publication enqueue, disabled config, drafts/failure not enqueued, chatbot downtime preserving WordPress success, atomic outbox/version allocation, duplicate/restarted delivery, fresh signatures over unchanged bytes, UTF-8 payloads, method/path binding, status polling, parent ordering/mismatches, optional reviewed catalog_slug, bulk backfill resumption and frontend sync errors. Mock all external HTTP. Run the existing parser tests and frontend build/lint checks as appropriate. Document configuration and activation steps, schema migration/rollback limits, and changes made. Do not print real secrets, send to live WordPress/chatbot, push or deploy automatically.
