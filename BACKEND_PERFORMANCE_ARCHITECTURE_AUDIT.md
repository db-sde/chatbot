# DegreeBaba Backend Performance & Architecture Audit

## Executive summary

The observed 18-second comparison path is structurally dominated by two sequential, tool-enabled LLM calls plus serial database round trips. The highest-confidence opportunity is to stop using an LLM to plan deterministic catalog reads that the resolver already identifies. The next is to remove redundant validation reads from the Neon request path.

No production behavior was changed by this audit. Where production query plans, row counts, or cache hit rates are required, the recommendation is explicitly marked as requiring measurement.

## Evidence and current cost map

The production path is:

```
HTTP admission checks
  -> Prompt Guard (~1 s reported)
  -> policy
  -> session/history/context DB work
  -> resolver
  -> LLM planner
  -> ToolNode / catalog reads
  -> LLM synthesis
  -> assistant persistence
  -> background lead qualification
```

For a comparison, the supplied measurements attribute approximately 1 s resolver, 3 s planner, 3 s tools, and 4 s synthesis. This produces a minimum visible path of about 11 seconds before database/session setup and Prompt Guard. The prior timing tree now records those previously unaccounted stages separately.

### Measured prompt payload

Local schema serialization measured the 11 tool definitions at **10,875 bytes / 2,486 GPT-compatible tokens**. The system prompt is **109 tokens**. A normal tool turn binds all tools for planning and binds them again for final synthesis, so it sends approximately **4,972 tool-schema input tokens** before history, user text, resolved context, and tool results.

At the checked-in GPT-4.1 mini input price ($0.40/M), the duplicate schema alone is approximately **$0.00199 per two-call turn**. It also increases provider processing time.

### Request-type paths

| Request | Current LLM calls | Deterministic data already available | Main avoidable work |
|---|---:|---|---|
| Fee | Usually 2 | Resolver + fee query | Planner and templated synthesis |
| Eligibility | Usually 2 | Resolver + eligibility query | Planner and templated synthesis |
| Comparison | Usually 2 | Resolver targets + comparison query | Planner; often synthesis can be tabular |
| Programs / specializations | Usually 2 | Resolver + list query | Planner; rendering can be deterministic |
| University overview / placement | Usually 2 | Resolver + overview query | Planner can be bypassed; narrative synthesis may retain LLM |
| Lead/contact | 0 foreground, 1 background | Rule match exists | Background semantic classification runs for every completed turn |
| Broad catalog discovery | 1–2 | Partial | Keep LLM routing until evaluated |

## Top opportunities, ranked

1. **Deterministic routes for high-confidence fee, eligibility, programs, specializations, and two-target comparisons.**  
   Impact: highest; removes one or both visible LLM calls.  
   Quality: improves factuality because output is rendered from canonical rows.  
   Risk: medium; route only when resolver confidence and required slugs are complete. Shadow-test first.

2. **Do not bind all tools for final synthesis when a completed tool batch is sufficient.**  
   Evidence: 2,486 tool-schema tokens are supplied each binding; current agent binds tools on both planner and synthesis calls.  
   Impact: saves roughly 2.5k input tokens and prevents unnecessary second-round tool calls.  
   Risk: medium; permit a second planning round only when a tool returned an explicit incomplete/not-found signal.

3. **Eliminate redundant canonical-slug validation reads.**  
   Evidence: canonical university validation can query the same slug in both `normalize_university_slug` and `validate_university_slug`. Course/spec validation adds another serial existence query before the actual catalog read.  
   Impact: 1–3 serial Neon round trips per simple tool; higher for comparisons.  
   Risk: low to medium; preserve cache invalidation/ingestion semantics and retain validation.

4. **Batch comparison validation.**  
   Evidence: `compare_entities_tool` validates each slug serially, then runs the comparison query.  
   Impact: two-target comparison can replace several round trips with one batched existence lookup plus one comparison query.  
   Risk: low; return the same invalid-slug envelope.

5. **Keep course and specialization slugs in the entity cache.**  
   Evidence: course/spec cache rows contain IDs but not slugs; `_to_slug` performs a database lookup for non-university matches.  
   Impact: removes one resolver DB trip for each snapped course/spec; moves a warm resolver toward sub-200ms CPU-only work.  
   Risk: low; update cache-refresh and ingestion tests together.

6. **Remove the no-op session-context insert from steady-state turns.**  
   Evidence: `ensure_session` unconditionally performs `INSERT ... ON CONFLICT DO NOTHING` for `session_context`; later context writes already use upserts and reads safely return an empty object.  
   Impact: one DB write/round trip per chat.  
   Risk: low after verifying no code requires a blank row.

7. **Move anonymous fee/eligibility signals off the foreground path.**  
   Evidence: resolver awaits `log_anonymous_signal` before LLM planning, even though the write does not affect the current answer.  
   Impact: one DB round trip from visible latency.  
   Risk: low; use a bounded background queue and monitor loss/failure.

8. **Gate background lead-intent LLM classification.**  
   Evidence: every completed turn invokes `lead_intent_classifier` after response generation, including factual chats; it has a separate LLM prompt and recent history.  
   Impact: material throughput and cost reduction, though not first-response latency.  
   Risk: medium; invoke only after deterministic lead/interest signals or use a sampled shadow evaluation to measure recall.

9. **Combine page-context reads when pathname context is used.**  
   Evidence: page resolution can make three sequential DB queries for university, course, and specialization.  
   Impact: one to two DB trips on page-specific requests.  
   Risk: low; a single join query must preserve the current verified hierarchy.

10. **Use a versioned catalog read cache only after measuring repeat rate.**  
    Evidence: fee, eligibility, overview, and programs are stable catalog reads; no hit-rate data exists in this audit.  
    Impact: potentially large for popular universities; zero if traffic is long-tail.  
    Risk: medium; key by entity slug and catalog version, invalidate on ingestion, and require a measured hit rate before rollout.

## LLM audit

| Call | Purpose | Current value | Recommendation |
|---|---|---|---|
| Prompt Guard | attack detection | Security-critical; ~1s | Retain. Its local heuristic and shortened outage path are appropriate. |
| Planner | choose catalog tool and arguments | Low for fully resolved factual routes; high for broad discovery | Bypass for explicit deterministic routes. |
| Final synthesis | convert tool rows to an answer | Moderate for narrative questions; low for fee/eligibility/tables | Template structured factual answers; use no-tools synthesis when narrative is needed. |
| Lead classifier | background lead qualification | Useful only for ambiguous intent | Gate by deterministic interest signals; measure missed-lead recall. |

## Tool and database audit

### Serial round trips

A normal turn makes multiple sequential DB calls before the model:
- IP block and daily-cap checks;
- session upsert plus unconditional context-row upsert;
- history read;
- user-message insert plus session update;
- context read;
- resolver context persistence and signal write.

A canonical fee lookup can then perform university validation reads, course validation, and the actual fee query. Comparison validation repeats this per target before the comparison query. This pattern is consistent with a high-latency Neon deployment even when each SQL statement itself is efficient.

### Query-plan boundary

The local database was unavailable, so no `EXPLAIN (ANALYZE, BUFFERS)`, row scans, or production frequency could be collected. The schema includes relevant equality and trigram indexes, including course/university/session/message indexes. Do not add indexes until these hot-query plans are captured against production-shaped data.

Required production capture:
```sql
EXPLAIN (ANALYZE, BUFFERS) -- session history
EXPLAIN (ANALYZE, BUFFERS) -- fee/eligibility
EXPLAIN (ANALYZE, BUFFERS) -- comparison validation/query
EXPLAIN (ANALYZE, BUFFERS) -- daily site cap
```

## Resolver and context audit

University aliases are already memory-resident after startup. The measurable resolver avoidable work is course/spec slug lookup by ID because those cache rows omit slugs. Comparison behavior is correct: it records both `comparison_targets` while retaining the first university/course only as primary context. Tool argument merge preserves target lists for comparison queries.

History is capped at eight stored messages (about four turns), which is reasonable for quality. The larger token waste is the tool schema duplicated on every tool-enabled LLM call, not the 109-token system prompt. The `sessions.summary` column is not used in the chat path; do not build summarization until history usage demonstrates a need.

## Recommended request paths

### Deterministic factual route

```
guard -> policy -> resolver -> one validated/batched catalog read -> template -> persist
```

Apply only to explicit, complete, non-ambiguous fee, eligibility, programs, specializations, and two-target comparisons. This removes 1–2 LLM calls and cannot hallucinate catalog values.

### Narrative route

```
guard -> policy -> resolver -> one planned catalog read -> no-tools synthesis -> persist
```

The synthesis call receives only the system prompt, relevant history, resolved context, and tool result—not the full tool catalog. Escalate to another tool-planning pass only for an explicit incomplete result.

## Roadmap

### Quick wins (1–2 days)

1. Instrument DB query spans inside the new timing tree.
2. Cache course/spec slugs in the resolver cache.
3. Collapse duplicate canonical-university validation.
4. Move anonymous signals to a bounded background worker.
5. Add production query-plan capture.

Expected visible gain: 1–3 database round trips; exact milliseconds depend on Neon RTT.

### Medium changes (one week)

1. Add deterministic fee/eligibility/list/comparison routes behind metrics and shadow answers.
2. Batch comparison validation.
3. Use no-tools final synthesis after a successful tool batch.
4. Gate lead-intent classification and measure recall/cost.

Expected visible gain: 30–55% for deterministic factual traffic; 10–25% for narrative traffic. Expected tool-schema savings: about 2,486 input tokens for every retained one-LLM narrative tool turn.

### Major improvements (2–4 weeks)

1. Versioned catalog read cache with measured hit-rate threshold.
2. Background job queue/semaphore for lead scoring and analytics.
3. Catalog projection/materialized read model if `EXPLAIN` identifies join or remote-read hotspots.
4. Evaluation harness comparing deterministic templates against current LLM answers by route.

Expected gain: 50%+ blended latency only if deterministic factual routes cover a meaningful share of traffic. Do not claim this outcome before route-mix telemetry exists.

## Quality safeguards

- Route only on canonical resolver output; otherwise retain the current agent.
- Render exact database fields; never infer eligibility, fees, or accreditation.
- Keep comparison target lists intact and evaluate table parity before rollout.
- Use shadow mode and answer-quality review before enabling a route.
- Treat lead-classifier gating as a recall experiment, not a pure cost cut.

