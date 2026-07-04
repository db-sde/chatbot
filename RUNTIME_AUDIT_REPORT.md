# Runtime Execution Audit — DegreeBaba AI Advisor

**Scope:** trace actual code paths for a single chat turn, measure backend/DB/LangGraph/LLM behavior, assess provider abstraction, and identify the highest-impact runtime bottlenecks.  
**Date:** 2026-07-04  
**Auditor:** Principal Software Engineer review  
**Codebase state:** post-refactor (37 tests passing, 3 skipped; admin lint clean)

---

## 1. Executive Summary

A single user message currently triggers **3–5+ LLM calls** and **~10–20 database round-trips**.  Most LLM calls are sequential.  **The agent now has bounded cross-turn memory**, and **a unified, config-driven LLM layer** supports seven providers with fallback chains.  The runtime is functional but will benefit from further caching of entity resolution and vector search to bound cost and latency.

| Area | Status | Top Risk |
|---|---|---|
| DB query volume | Medium | N+1 patterns inside tools |
| LangGraph state | High | Agent is stateless across turns; only slug context survives |
| LLM architecture | ✅ Resolved | Unified provider abstraction with 7 adapters + task registry + fallback chains |
| Tool execution | Medium | Validation adds DB hits; structured data returned to synthesize node |
| Observability | Medium | Token/cost tracking exists but has blind spots |
| Failover / resilience | ✅ Improved | Retries + fallback chains per task; circuit breaker still needed |

---

## 2. End-to-End Request Flow (one chat turn)

```
POST /chat
│
├─ main.py
│  ├─ validate_site_request()          # in-memory settings check
│  ├─ SlowAPI rate limit               # Redis/memory store
│  ├─ get_or_create_user_by_session()  # SELECT → possible INSERT
│  ├─ get_session_history()              # SELECT recent messages (widget only; agent ignores history)
│  ├─ INSERT user message
│  ├─ check_blocked_terms()            # cached list scan
│  ├─ log_analytics_event("user_message")
│  └─ init_observability_context()
│
├─ agent/graph.py: chat_agent.astream(state, config)
│  ├─ node: resolve_entities
│  │   ├─ Gemini embedding call        # models/text-embedding-004
│  │   ├─ vector_search()              # pgvector <=> query, LIMIT 5
│  │   └─ Gemini JSON LLM call         # classify/resolve entities
│  ├─ node: agent_decide
│  │   └─ Groq tool-call LLM           # llama-3.3-70b-versatile, streaming=True internally
│  ├─ [edge] tool_call → execute_tools
│  │   └─ 1..n tools (DB + optional vector search, e.g. recommend_university)
│  ├─ loop back to agent_decide (with tool results)
│  ├─ [edge] respond → synthesize_reply
│  │   └─ Groq/Gemini LLM           # final answer (full response, then word-SSE)
│  └─ node: update_lead_score
│     ├─ lead_intent_classifier()      # Gemini JSON LLM
│     ├─ log_score_events()            # INSERT signals + SELECT total score
│     ├─ should_append_lead_ask()      # SELECT + possible INSERT
│     └─ optional CRM webhook POST
│
└─ main.py (after graph)
   ├─ stream reply words via SSE       # NOT real LLM token streaming
   ├─ INSERT assistant message
   ├─ log_analytics_event("assistant_message")
   └─ yield final metrics event
```

**Result:** the critical path is dominated by LLM latency; DB latency is secondary but becomes material under concurrent load because of query count.

---

## 3. Database Query Audit (per turn)

| # | Query / Operation | File | Cost Driver |
|---|---|---|---|
| 1 | `SELECT` user by session id | `queries.py:get_or_create_user_by_session` | 1 RT |
| 2 | `INSERT` user if missing | same | 1 RT |
| 3 | `SELECT` recent messages (widget/audit) | `queries.py:get_session_history` | bounded by LIMIT 20–50; **not used by agent** |
| 4 | `INSERT` user message | `queries.py:save_message` | 1 RT |
| 5 | `SELECT` blocked terms list | cached in `check_blocked_terms` | 1 RT per worker, then cache |
| 6 | `INSERT` analytics event | `queries.py:log_analytics_event` | 1 RT |
| 7 | `SELECT` vector search CTE | `queries.py:vector_search` | pgvector, **~1-5 ms + index** |
| 8 | Tool validation `SELECT 1` | `tool_validator.py` | 1 RT per validated slug |
| 9 | Tool data `SELECT` | `queries.py:get_*_by_slug`, `get_*_with_relations` | 1-3 RT per tool |
| 10 | `INSERT` score signal(s) | `queries.py:log_signal` | 1 RT per event |
| 11 | `SELECT` total lead score | `queries.py:total_lead_score` | 1 RT |
| 12 | `SELECT` lead ask exists | `queries.py:lead_ask_exists` | 1 RT |
| 13 | `INSERT` lead ask marker | `queries.py:mark_lead_ask` | optional 1 RT |
| 14 | `INSERT` assistant message | `queries.py:save_message` | 1 RT |
| 15 | `INSERT` analytics event | `queries.py:log_analytics_event` | 1 RT |

**Typical total: 10–20 DB round-trips per turn.**  The biggest wins are:
1. Load a bounded history window into the agent state (currently none).
2. Remove per-tool existence checks if the tool already receives validated slugs (or batch them).
3. Cache entity resolution across turns to avoid redundant vector search + LLM.

---

## 4. LLM Call Inventory (per turn)

| Call | Task | Configurable Provider/Model | Purpose | When |
|---|---|---|---|---|
| Embedding | `embedding` | Gemini `models/text-embedding-004` (default) | Embed user message for vector search | Every turn |
| Entity resolution | `entity_resolution` | Gemini `gemini-2.5-flash` (default) | JSON extraction of university/course/specialization | Every turn |
| Agent decision | `agent_decide` | Groq `llama-3.3-70b-versatile` → Gemini fallback (default) | Tool selection / respond routing | Every turn |
| Synthesize reply | `synthesize` | Groq `llama-3.3-70b-versatile` → Gemini fallback (default) | Final answer generation | Every turn |
| Lead intent | `lead_intent` | Gemini `gemini-2.5-flash` (default) | Classify lead intent | Every turn |

**Exactly 4 paid LLM calls per turn.**  All providers and models are now swappable via the `LLM_TASKS` JSON configuration without code changes.  The manager retries each provider and walks the configured fallback chain automatically.

### 4.1 Provider split is accidental, not architectural
- `resolve_entities` and `lead_intent_classifier` use Gemini because they call `llm_client.generate_json()`.
- `agent_decide`, `synthesize_reply`, and tool summaries use Groq because they call `llm_client.generate()`.
- There is no business reason the agent cannot run entirely on one provider; the split is an implementation artifact.

---

## 5. LangGraph Execution Analysis

### 5.1 Graph structure (`backend/agent/graph.py`)

```
resolve_entities
      ↓
agent_decide
      ↓
   [conditional]
   ├─ tool_call  → execute_tools → agent_decide (loop)
   ├─ respond    → synthesize_reply
   └─ end        → END

synthesize_reply
      ↓
update_lead_score
      ↓
     END
```

### 5.2 State schema

- `messages`: list of LangChain `BaseMessage` objects (grows with full history).
- `entities`: resolved university/course/specialization slugs.
- `agent_action`: last action chosen by the agent.
- `tool_results`: accumulated tool outputs.
- `final_response`: streaming text accumulator.
- `lead_score_metadata`: intent classification result.

### 5.3 State-growth / memory problem

`run_chat_turn()` does **not** load prior messages from the database.  The initial state is built with only:
- the system prompt,
- the current user message, and
- `session_context` (last known university/course/specialization slugs).

Within a single turn, `messages` grows as the agent adds `AIMessage` tool-call and `ToolMessage` results, but **no data from previous turns is visible to the LLM**.  This means:
- Follow-up questions like "What about fees?" or "Compare it with Amity" are answered without the context of what "it" refers to.
- The widget restores history for the user, but the AI behaves as if each turn is the first turn.
- `session_context` slugs provide partial continuity, but only for catalog slugs, not for the actual conversation thread.

The `lead_intent_classifier` receives a `history` list built from `state["messages"]` — i.e. only the current turn — so its "history" context is also minimal.

**Impact:** degraded user experience on multi-turn conversations; higher reliance on entity resolution every turn.

### 5.4 Routing quirks

- `agent_decide` returns `{"agent_action": "tool_call"}` or `{"agent_action": "respond"}`.  If the LLM returns anything else, the conditional edge falls through to `END`, which is an unhandled exit.  Recommend adding an explicit `unknown` branch that re-prompts.
- The tool loop can theoretically run forever; there is no max-iteration guard in `execute_tools` → `agent_decide` loop.

---

## 6. Tool Execution Analysis

| Tool | DB Calls | LLM Calls | Validation | Notes |
|---|---|---|---|---|
| `search_universities` | `vector_search` | None | None | Returns top-5 matches |
| `university_details` | `validate_university_slug` + `get_university_with_relations` | None | 1 RT | Heavy query with courses/specializations |
| `course_details` | `validate_course_slug` + `get_course_with_relations` | None | 1 RT | Heavy query |
| `specialization_details` | `validate_specialization_slug` + `SELECT` | None | 1 RT | Lightweight |
| `university_courses` | validation + `get_university_courses` | None | 1 RT | List query |
| `course_specializations` | validation + `get_course_specializations` | None | 1 RT | List query |
| `compare_universities` | validation (×2) + `compare_universities_data` | None | 2 RT | Heavy multi-row fetch |
| `recommend_university` | validation + `find_similar_courses` (vector) + `SELECT` | None | 1 RT + vector | Returns ranked matches |

### 6.1 Tool validation doubles DB load

Every tool that takes a slug first validates it with a `SELECT 1` in `security/tool_validator.py`, then the tool itself runs another `SELECT`.  These could be collapsed into the tool query by returning `NULL` when the slug does not exist.

### 6.2 Tools do not call the LLM

Unlike the initial audit assumption, `compare_universities` and `recommend_university` return structured catalog data.  The final narrative is produced once by the `synthesize_reply` node.  This is the correct design — do not move summarization into tools.

---

## 7. LLM / Provider Architecture Audit

### 7.1 Status after Phase B

A unified LLM abstraction layer now lives in `backend/llm/`:

- **Adapter protocol** (`LLMProvider`) with `generate`, `stream`, `embed`, `get_chat_model`.
- **Seven provider adapters:** Groq, Gemini, OpenAI, OpenRouter, Anthropic, DeepSeek, Kimi.
- **Capability flags** (`TEXT`, `JSON`, `TOOLS`, `STREAM`, `EMBEDDINGS`) used to skip unsuitable providers.
- **Task registry** (`LLM_TASKS` JSON or defaults) assigns provider/model per task.
- **Fallback chains** with exponential-backoff retries inside `LLMManager`.
- **Graph nodes** are provider-agnostic: they call `llm_client.generate("agent_decide", ...)` and `llm_client.generate("synthesize", ...)`.

### 7.2 Pre-Phase-B issues (resolved)

1. ✅ **No adapter interface.**  Now every provider implements `LLMProvider`.
2. ✅ **Tool schemas were OpenAI-format only and hard-coded.**  Now converted from LangChain tools to `ToolSpec` and adapted per provider by each adapter.
3. ✅ **Embedding was Gemini-only at call sites.**  Now accessed through `llm_client.embed()` / `manager.embed()`; any adapter declaring `EMBEDDINGS` can serve it.
4. ✅ **JSON mode was prompt-based for Gemini.**  Adapters use native JSON mode when supported; fallback to prompt instruction + parser otherwise.
5. ✅ **No failover or retries.**  `LLMManager` retries 3× per provider and walks the fallback chain.

### 7.3 Configuration surface

All provider/model selection is now in `settings.py` / `.env`:

- Provider API keys: `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `KIMI_API_KEY`.
- Default model names: `GROQ_MODEL_NAME`, `GEMINI_MODEL_NAME`, etc.
- Task registry: `LLM_TASKS` JSON.

Changing `LLM_TASKS` is sufficient to move any task between providers/models without modifying LangGraph nodes, tools, business logic, or routes.

---

## 9. Pricing & Observability Verification

### 9.1 `pricing_config.py`

- Covers Gemini 2.5 Flash, Gemini 1.5 Flash, Llama 3.3 70B on Groq, OpenAI GPT-4o / GPT-4o mini, Anthropic Claude 3.5 Sonnet, DeepSeek Chat, Kimi Moonshot, and a default fallback.
- Used by `observability.record_llm_call()` after every chat LLM response.
- Uses partial substring matching (e.g. `gemini-2.5-flash` matches `gemini-2.5-flash-latest`).

### 9.2 Gaps

1. **Embedding cost is not tracked.**  `record_llm_call()` only sees chat response metadata; embedding calls are invisible to cost accounting.
2. **Tool LLM calls are tracked correctly**, but per-tool cost attribution is not surfaced separately.
3. ✅ **`t_first_token` is now populated** by the LLM manager when the first successful response arrives.
4. ✅ **Per-call LLM wall time is now accumulated** via `record_llm_call_duration()`.

### 9.3 Recommendations

- Add `record_embedding_call(tokens, model)` to track vector-search costs.
- Emit a structured observability event at the end of each turn for dashboards.

---

## 10. Failover & Resilience

### 10.1 Current state

- ✅ Per-provider retries with exponential backoff (up to 3 attempts).
- ✅ Configurable fallback chains per task via `LLM_TASKS`.
- ❌ No circuit breaker yet.
- ✅ If the primary provider for a task is down, the manager walks the fallback chain.
- ❌ Entity resolution failure would still bubble up; graceful degradation should be added.
- ✅ Lead intent failure returns `lead_intent=False`.
- ✅ Final synthesis failure returns a static apology and logs the error.

### 10.2 Required resilience patterns

1. ✅ Retry with exponential backoff on transient 5xx/rate-limit errors (max 3 attempts).
2. ✅ Fallback model/provider per task in config.
3. **Circuit breaker** for failing providers (e.g. after 10 consecutive failures, short-circuit for 30 s).
4. **Graceful degradation:**
   - Entity resolution failure → continue with no entities.
   - Lead intent failure → return `lead_intent=False` (already done).
   - Final synthesis failure → return a static apology and log the error.

---

## 11. Top 10 Runtime Bottlenecks

| Rank | Bottleneck | Impact | Evidence | Status / Suggested Fix |
|---|---|---|---|---|
| 1 | **Agent has no cross-turn conversation memory** | Follow-ups lose context; user experience degrades after first turn | `run_chat_turn()` builds state from only system prompt + current message; prior DB messages ignored | ✅ Fixed: bounded recent history loaded into initial state |
| 2 | **No unified LLM abstraction / hard-coded provider split** | Cannot switch models/providers without code edits; no failover | `llm_client.py` directly imported Groq/Gemini SDKs | ✅ Fixed: unified `llm/` adapter layer + task registry |
| 3 | **No provider failover or retries** | Single provider outage = full outage | No retry/fallback logic in any LLM call | ✅ Fixed: manager retries 3× and walks fallback chain |
| 4 | **Entity resolution runs every turn** | Redundant Gemini embedding + LLM call | `resolve_entities` is first node, no cache | Cache when entities unchanged + TTL cache |
| 5 | **Lead intent classifier runs every turn** | Extra Gemini LLM call even on low-score sessions | Called inside `update_lead_score` unconditionally | Only run when score is near threshold or every K turns |
| 6 | **Vector search runs every turn** | DB + embedding cost even for follow-ups | Called in `resolve_entities` unconditionally | Cache embeddings/entities; skip on short follow-ups |
| 7 | **Double DB hits per tool (validation + fetch)** | ~2× tool DB round-trips | `tool_validator.py` runs `SELECT 1`, then tool runs full query | Merge validation into tool query or validate once at agent boundary |
| 8 | **SSE "tokens" are words, not LLM tokens; no real streaming** | TTFT metrics are misleading; UX is buffered | `_stream_text()` splits a fully-generated reply by spaces | Implement true LLM streaming for synthesize_reply (optional) |
| 9 | **Embedding cost not tracked** | Vector search costs invisible | `record_llm_call()` only sees chat metadata | Add `record_embedding_call()` |
| 10 | **No circuit breaker for failing providers** | Repeated failing calls waste latency/budget | Manager retries but never short-circuits | Add circuit breaker after N consecutive failures |

---

## 12. Risk Matrix

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Agent forgets prior turns / poor follow-up experience | High | High | Load bounded recent history into agent state |
| Provider outage halts chat | Medium | Critical | ✅ Fallback provider + retries implemented |
| Token cost scales super-linearly | High | High | Bound history, cache entity resolution, reduce lead-intent frequency |
| LLM returns malformed JSON in entity/intent | Medium | Medium | Use native JSON mode + Pydantic validation |
| Vector search slows under load | Medium | Medium | Add `ivfflat`/`hnsw` index tuning; cache embeddings |
| Tool hallucinated slugs reaching DB | Low | Medium | Keep `tool_validator.py`; consolidate query |

---

## 13. Implemented Fixes (this audit)

| Fix | Files | Notes |
|---|---|---|
| Bounded cross-turn memory | `backend/agent/graph.py` | `run_chat_turn()` now loads the last 20 user/assistant turns from `get_session_history()` and prepends them to the agent prompt. |
| First-token timing | `backend/observability.py`, `backend/agent/graph.py`, `backend/agent/llm_client.py` | `mark_first_token()` records the first successful LLM response; `record_llm_call_duration()` accumulates total LLM wall time. |
| Exponential-backoff retries | `backend/agent/llm_client.py`, `backend/agent/graph.py` | `generate_text()` retries each provider up to 3×; LangGraph `ainvoke()` chains use `.with_retry(stop_after_attempt=3)`. |
| Metrics in final SSE | `backend/agent/graph.py` | Final event now includes `metrics` with `response_time_ms`, `ttft_ms`, `llm_duration_ms`, token counts, cost, and model name. |
| Unified LLM layer | `backend/llm/` (new package) | Adapters for 7 providers, task registry, fallback chains, capability detection. |
| Provider-agnostic graph nodes | `backend/agent/graph.py` | `node_agent_decide` and `node_synthesize_reply` call `llm_client.generate(task, ...)` only. |
| Configuration-only provider switching | `backend/settings.py`, `.env.example` | `LLM_TASKS` JSON controls every task/provider/model. |

Validation: `uv run pytest tests -v` → 49 passed, 3 skipped; `npm run lint` → 0 errors.

---

## 14. Recommended Action Plan

### Phase A — Quick wins (completed)
1. ✅ Loaded bounded recent conversation history (last 20 turns) into the agent's initial state (`backend/agent/graph.py`).
2. ✅ Added `mark_first_token()` and `record_llm_call_duration()` to observability; populated them after every LLM response.
3. ✅ Added per-provider exponential backoff retries (up to 3 attempts) to `LLMClient.generate_text()` and LangGraph `ainvoke()` calls.
4. ✅ Exposed turn-level metrics in the final SSE event (`metrics` field).

### Phase B — Architecture (completed)
5. ✅ Designed and implemented unified LLM adapter layer + task-based config (`backend/llm/`).
6. ✅ Moved provider/model selection into `settings.py` with env overrides (`LLM_TASKS` JSON).
7. ✅ Added fallback provider support for every task; manager walks fallback chain with retries.
8. ✅ Removed provider-specific logic from `agent/graph.py` nodes; graph calls `llm_client.generate(task, ...)` only.
9. ✅ Implemented adapters: Groq, Gemini, OpenAI, OpenRouter, Anthropic, DeepSeek, Kimi.
10. ✅ Added provider capability detection (`ProviderCapability` flags) and capability-based routing.

Artifacts produced:
- `docs/PHASE_B_ARCHITECTURE.md`
- `docs/PHASE_B_MIGRATION_REPORT.md`
- `docs/PHASE_B_COMPATIBILITY_REPORT.md`
- `docs/PHASE_B_ROLLBACK_PLAN.md`

### Phase C — Scalability (1–2 weeks)
1. Cache entity resolution across turns (TTL by session).
2. Reduce lead-intent classification frequency.
3. Cache vector-search results for unchanged session context / user query.
4. Consolidate tool validation into tool queries.
5. Add embedding-cost tracking.

### Phase D — Hardening
13. ✅ Max-iteration guard already exists (`MAX_TOOL_ITERATIONS = 4`).
14. Add structured end-of-turn observability event (e.g. OpenTelemetry / webhook).
15. Load-test with 100+ turn conversations and measure p95 latency.

---

## 15. Conclusion

Phase A and Phase B are complete.  The application now has:

1. **Bounded cross-turn conversation memory** so follow-ups retain context.
2. **A production-grade, vendor-independent LLM layer** with 7 provider adapters, a task-based registry, configurable fallback chains, and capability-aware routing.

Any model or provider can now be switched from configuration alone (`LLM_TASKS` JSON and provider API keys) without modifying LangGraph nodes, tools, business logic, or routes.  The highest-leverage remaining work is caching entity resolution/vector search and reducing lead-intent frequency to bound cost and latency as conversations grow.
