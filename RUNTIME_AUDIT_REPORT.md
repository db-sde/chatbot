# Runtime Execution Audit — DegreeBaba AI Advisor

**Scope:** trace actual code paths for a single chat turn, measure backend/DB/LangGraph/LLM behavior, assess provider abstraction, and identify the highest-impact runtime bottlenecks.  
**Date:** 2026-07-04  
**Auditor:** Principal Software Engineer review  
**Codebase state:** post-refactor (37 tests passing, 3 skipped; admin lint clean)

---

## 1. Executive Summary

A single user message currently triggers **3–5+ LLM calls** and **~10–20 database round-trips**.  Most LLM calls are provider-specific and sequential.  There is no unified model abstraction, no provider failover, and **the agent has no cross-turn conversation memory** — it only persists resolved slugs in `session_context`.  The runtime is functional but produces context-less follow-ups and will degrade under load because of redundant LLM/DB work.

| Area | Status | Top Risk |
|---|---|---|
| DB query volume | Medium | N+1 patterns inside tools |
| LangGraph state | High | Agent is stateless across turns; only slug context survives |
| LLM architecture | High | Hard-coded Groq + Gemini split; no provider swap/failover |
| Tool execution | Medium | Some tools call LLMs again; validation adds DB hits |
| Observability | Medium | Token/cost tracking exists but has blind spots |
| Failover / resilience | Critical | Single provider per call site; no retries/fallback |

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

| Call | Provider | Model | Purpose | When |
|---|---|---|---|---|
| Embedding | Gemini | `models/text-embedding-004` | Embed user message for vector search | Every turn |
| Entity resolution | Gemini | `gemini-2.5-flash` | JSON extraction of university/course/specialization | Every turn |
| Agent decision | Groq → Gemini fallback | `llama-3.3-70b-versatile` / `gemini-2.5-flash` | Tool selection / respond routing | Every turn |
| Synthesize reply | Groq → Gemini fallback | same | Final answer generation | Every turn |
| Lead intent | Gemini | `gemini-2.5-flash` | Classify lead intent | Every turn |

**Exactly 4 paid LLM calls per turn.**  Tools do not call the LLM; they return structured data that the synthesize step narrates.  All calls are sequential on the critical path.

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

### 7.1 Current design (`backend/agent/llm_client.py`)

- `llm_client.generate_json(prompt)` → `google.generativeai.GenerativeModel` (`gemini-2.5-flash`).
- `llm_client.generate(prompt, tool_specs=None, stream=False)` → LangChain `ChatGroq` (`llama-3.3-70b-versatile`).
- Direct imports of `AsyncGroq`, `ChatGroq`, `ChatGoogleGenerativeAI`, `google.generativeai`.
- Provider choice is **hard-coded by method**, not by configuration.

### 7.2 Vendor lock-in symptoms

1. **No adapter interface.**  Swapping Groq for OpenAI/Anthropic requires editing `llm_client.py`.
2. **Tool schemas are OpenAI-format only.**  Gemini function-calling uses a different schema shape; the current code cannot bind tools to Gemini without translation.
3. **Embedding is Gemini-only.**  No abstraction for `text-embedding-3-small`, Cohere, etc.
4. **JSON mode is prompt-based for Gemini.**  Native `response_mime_type=application/json` is not used, so output parsing can fail.
5. **Async Groq client is initialized but only used for `moderation`.**  It is dead weight in normal chat flow.

### 7.3 Configuration is half-done

`settings.py` now exposes:
- `GROQ_MODEL_NAME`
- `GEMINI_MODEL_NAME`
- `GEMINI_EMBEDDING_MODEL`

But there is no setting for:
- Which provider drives `agent_decide` / `synthesize_reply`.
- Which provider drives `resolve_entities` / `lead_intent`.
- Temperature, max_tokens, top_p per task.
- Fallback provider/model.

---

## 8. Proposed Unified Model Layer

### 8.1 Design goals

1. One configuration surface controls provider + model per task.
2. A single runtime interface: `generate()`, `generate_json()`, `embed()`, `bind_tools()`.
3. Provider adapters translate between the unified interface and vendor SDKs.
4. Tool schemas are normalized once and adapted per provider.
5. Optional fallback adapter per task for resilience.

### 8.2 Suggested configuration schema

```python
# settings.py
class LLMTaskConfig(BaseModel):
    provider: str               # "groq" | "gemini" | "openai" | ...
    model: str
    temperature: float = 0.0
    max_tokens: int | None = None
    json_mode: bool = False     # adapter uses native JSON if available
    timeout_seconds: float = 30.0
    fallback: LLMTaskConfig | None = None

class Settings(BaseSettings):
    ...
    llm_tasks: dict[str, LLMTaskConfig] = {
        "embedding":          LLMTaskConfig(provider="gemini", model="models/text-embedding-004"),
        "entity_resolution":  LLMTaskConfig(provider="gemini", model="gemini-2.5-flash", json_mode=True),
        "agent_decide":       LLMTaskConfig(provider="groq",   model="llama-3.3-70b-versatile", json_mode=True),
        "synthesize":         LLMTaskConfig(provider="groq",   model="llama-3.3-70b-versatile"),
        "lead_intent":        LLMTaskConfig(provider="gemini", model="gemini-2.5-flash", json_mode=True),
        "tool_summarize":     LLMTaskConfig(provider="groq",   model="llama-3.3-70b-versatile"),
    }
```

### 8.3 Adapter interface

```python
class LLMProvider(Protocol):
    async def generate(self, prompt: str, *, tools: list[ToolSpec] | None = None, stream: bool = False, **kwargs) -> LLMResponse:
        ...

    async def generate_json(self, prompt: str, *, schema: type[BaseModel] | None = None, **kwargs) -> dict:
        ...

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        ...
```

### 8.4 Call-site refactor

```python
# Replace:
await llm_client.generate_json(prompt)

# With:
await llm.generate("entity_resolution", prompt)
```

This gives the team a **single config-switch** to move any task between providers/models without touching agent logic.

---

## 9. Pricing & Observability Verification

### 9.1 `pricing_config.py`

- Covers Gemini 2.5 Flash, Gemini 1.5 Flash, Llama 3.3 70B on Groq, and a default fallback.
- Used by `observability.record_llm_call()` after every LLM response.
- Uses partial substring matching (e.g. `gemini-2.5-flash` matches `gemini-2.5-flash-latest`).

### 9.2 Gaps

1. **Embedding cost is not tracked.**  `record_llm_call()` only sees chat response metadata; embedding calls are invisible to cost accounting.
2. **Tool LLM calls are tracked as additional `record_llm_call()` events**, which is correct, but the per-tool attribution is only timing/status, not cost.
3. **`t_first_token` is set but never used.**  The metadata key exists in `init_observability_context()` but nothing populates it.  For streaming `synthesize_reply`, first-token latency is a critical UX metric; it should be captured when the first chunk is yielded.
4. **No per-call latency metrics.**  `record_llm_call()` records tokens/cost but not wall time per LLM invocation.

### 9.3 Recommendations

- Add `record_embedding_call(tokens, model)` to track vector-search costs.
- Capture `t_first_token` in `llm_client.generate(stream=True)` on first chunk.
- Add `duration_ms` per LLM call.
- Emit a structured observability event at the end of each turn for dashboards.

---

## 10. Failover & Resilience

### 10.1 Current state

- No retries on LLM calls.
- No fallback provider.
- No circuit breaker.
- If Groq is down, the entire agent stops.
- If Gemini is down, entity resolution and lead intent fail (the latter is caught and returns a safe default; the former is not).

### 10.2 Required resilience patterns

1. **Retry with exponential backoff** on transient 5xx/rate-limit errors (max 3 attempts).
2. **Fallback model/provider** per task in config.
3. **Circuit breaker** for failing providers (e.g. after 10 consecutive failures, short-circuit for 30 s).
4. **Graceful degradation:**
   - Entity resolution failure → continue with no entities.
   - Lead intent failure → return `lead_intent=False` (already done).
   - Final synthesis failure → return a static apology and log the error.

---

## 11. Top 10 Runtime Bottlenecks

| Rank | Bottleneck | Impact | Evidence | Suggested Fix |
|---|---|---|---|---|
| 1 | **Agent has no cross-turn conversation memory** | Follow-ups lose context; user experience degrades after first turn | `run_chat_turn()` builds state from only system prompt + current message; prior DB messages ignored | Load bounded recent history (last N turns) into initial graph state |
| 2 | **No unified LLM abstraction / hard-coded provider split** | Cannot switch models/providers without code edits; no failover | `llm_client.py` directly imports Groq/Gemini SDKs | Implement adapter layer + task-based config |
| 3 | **No provider failover or retries** | Single provider outage = full outage | No retry/fallback logic in any LLM call | Add retry decorator + fallback config per task |
| 4 | **Entity resolution runs every turn** | Redundant Gemini embedding + LLM call | `resolve_entities` is first node, no cache | Skip when entities unchanged + TTL cache |
| 5 | **Lead intent classifier runs every turn** | Extra Gemini LLM call even on low-score sessions | Called inside `update_lead_score` unconditionally | Only run when score is near threshold or every K turns |
| 6 | **Vector search runs every turn** | DB + embedding cost even for follow-ups | Called in `resolve_entities` unconditionally | Cache last turn's embeddings/entities; skip on short follow-ups |
| 7 | **Vector search in recommend_university and resolve_entities** | DB + embedding cost on every factual turn | `find_similar_courses` and `vector_search` invoked inside nodes | Cache embeddings/results when query/session context unchanged |
| 8 | **Double DB hits per tool (validation + fetch)** | ~2× tool DB round-trips | `tool_validator.py` runs `SELECT 1`, then tool runs full query | Merge validation into tool query or validate once at agent boundary |
| 9 | **SSE "tokens" are words, not LLM tokens; no real streaming** | TTFT metrics are misleading; UX is buffered | `_stream_text()` splits a fully-generated reply by spaces | Implement true LLM streaming for synthesize_reply (optional) |
| 10 | **No per-call latency metrics and `t_first_token` is unpopulated** | Blind to real UX regressions | `t_first_token` never populated; `record_llm_call()` lacks duration | Capture first-LLM-response time and per-call latency |

---

## 12. Risk Matrix

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Agent forgets prior turns / poor follow-up experience | High | High | Load bounded recent history into agent state |
| Provider outage halts chat | Medium | Critical | Add fallback provider + retries |
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

Validation: `uv run pytest tests -v` → 37 passed, 3 skipped; `npm run lint` → 0 errors.

---

## 14. Recommended Action Plan

### Phase A — Quick wins (completed)
1. ✅ Loaded bounded recent conversation history (last 20 turns) into the agent's initial state (`backend/agent/graph.py`).
2. ✅ Added `mark_first_token()` and `record_llm_call_duration()` to observability; populated them after every LLM response.
3. ✅ Added per-provider exponential backoff retries (up to 3 attempts) to `LLMClient.generate_text()` and LangGraph `ainvoke()` calls.
4. ✅ Exposed turn-level metrics in the final SSE event (`metrics` field).

### Phase B — Architecture (1 week)
5. Design and implement unified LLM adapter layer + task-based config.
6. Move provider/model selection into `settings.py` with env overrides.
7. Add fallback provider support for critical tasks (`synthesize`, `agent_decide`).

### Phase C — Scalability (1–2 weeks)
8. Cache entity resolution across turns (TTL by session).
9. Reduce lead-intent classification frequency.
10. Cache vector-search results for unchanged session context / user query.
11. Consolidate tool validation into tool queries.
12. Add embedding-cost tracking.

### Phase D — Hardening
13. ✅ Max-iteration guard already exists (`MAX_TOOL_ITERATIONS = 4`).
14. Add structured end-of-turn observability event (e.g. OpenTelemetry / webhook).
15. Load-test with 100+ turn conversations and measure p95 latency.

---

## 15. Conclusion

The application runs correctly for single-turn questions, but multi-turn conversations are effectively stateless.  The two highest-leverage changes are:

1. **Load bounded conversation history into the agent** so follow-ups have context and the AI behaves like a real conversational advisor.
2. **Introduce a unified, config-driven LLM layer with provider fallback** so the team can switch models/providers and survive outages without code changes.

Together these changes transform the system from "works at small scale" to "production-grade and vendor-independent."
