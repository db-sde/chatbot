# DegreeBaba Backend Production Audit

## Executive summary

Two proven defects were fixed: request validation now verifies a configured site key against its own domain list, and direct lead capture preserves the request site when it creates a session. The highest remaining risks are unbounded per-round tool calls, a 16.5-second Prompt Guard outage path, misleading TTFT/tool-success metrics, and a non-green test suite.

## Critical and high findings

### Fixed: site-key authorization bypass

Previously, `validate_site_request` checked a host against every configured domain, did not verify the requested site key, and allowed absent Origin/Referer headers. A caller could create arbitrary daily-cap buckets or submit a key from another configured site. `backend/auth.py` now rejects unknown keys and missing provenance headers, then checks the host only against that key's domains.

Residual risk: Origin/Referer are browser provenance signals, not credentials; scripted callers can forge them. Production bot-abuse protection needs an edge-control design such as WAF/bot controls and signed short-lived widget tokens.

### High: graph cap limits rounds, not tool calls

`backend/agent/graph.py:567-609` executes every tool call in an AI message and increments `tool_call_count` only once. `MAX_TOOL_ITERATIONS=4` limits loop rounds, not calls; one model response can request all eleven tools and repeat over four rounds. Define a per-turn cap and an excess-call behavior before changing this.

### High: Prompt Guard fallback may add 16.5 seconds

`backend/security/scanner.py:377-433` makes three five-second attempts with 0.5 and 1.0-second backoffs. A timing-out service delays fallback by 16.5 seconds; the circuit opens only after five full scan failures. Reducing retries or failing closed is a deliberate security/availability decision.

### High: known admin bearer-token default

`backend/settings.py:25` defaults the admin token to `change-me`. If production misses the environment override, admin data and controls are exposed. Reject this placeholder at startup.

### High: lead CRM delivery can be silently lost

`/webhook/lead` ignores the `capture_lead` envelope and does not call `raise_for_status` on CRM responses (`backend/main.py:379-390`), yet returns `{"ok": true}`. Use an idempotent outbox keyed by persisted lead ID; do not add naive retries.

## Security, correctness, and observability

- **Streaming/TTFT:** the agent uses `model.ainvoke()` (`graph.py:449`). When no stream event is produced, the whole reply is emitted only after graph completion and TTFT is marked then (`lines 769-800`). Dashboard TTFT is therefore normally full-generation latency, not first-token latency.
- **Latent streaming disclosure:** output scanning begins after token emission (`graph.py:780` vs. `844`). Actual streaming must buffer/scan before each emitted segment.
- **Tool success rate is misleading:** the documented `{"not_found": true, "reason": "internal_error"}` envelope is recorded as SUCCESS because the decorator only flags raised exceptions. Direct reproduction produced exactly that envelope with `status: SUCCESS`.
- **Output-scan dashboard is always zero:** the scanner writes `flagged_messages`, while the security summary returns `output_scan_blocks: 0` literally.
- **Concurrent session turns race:** history/context are read and later written without session serialization (`graph.py:740-753`); overlapping turns can plan from stale state and last-writer-wins context.
- **Lead scoring is incomplete:** `classify_score_events(message)` is called without `message_count`, so `three_plus_turns` is unreachable.
- **Session history is bearer-by-UUID:** history is not principal-bound. UUID entropy limits enumeration, but a leaked ID grants read access.
- **Logging retains user content:** request and security paths persist message content; establish redaction, retention, and access controls.
- **NAAC filtering is lexicographic:** `c.naac_grade >= $4` is text comparison. Confirm stored grade vocabulary and map to explicit ordinals.

## Database and resolver assessment

No SQL-injection path was found: query values are parameterized and dynamic columns/tables are allowlisted. Catalog search has a trigram index, and session/catalog indexes cover the principal lookups. No missing-index claim is made without production-shaped `EXPLAIN (ANALYZE, BUFFERS)`.

Verified existing safeguards: catalog-first resolution, scoped course/specialization snapping, comparison persistence, stale dependent clearing, canonical tool-argument merging, and four-round graph termination.

## Changes and verification

1. **Request authorization** — `backend/auth.py`, plus focused tests. The fix is local and preserves global-domain validation used by public widget configuration.
2. **Lead site attribution** — `backend/agent/tools.py` and `backend/main.py`, plus a focused test. New direct-lead sessions now use the validated request site.

- Focused tests: **6 passed**.
- `python -m compileall -q backend`: **passed**.
- Full suite: **60 passed, 3 skipped, 8 failed**. The failures are existing resolver/graph test drift: tests expect `extract_intent()` to return `university_query`, although the implementation deliberately moved university detection to catalog-first scanning; one graph spy also has the old `update_session_context` signature. They are not caused by these audit changes, but block a green release gate.

