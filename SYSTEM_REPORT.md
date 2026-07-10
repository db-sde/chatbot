# DegreeBaba Chatbot — Technical Backend & Architecture Specification

This report outlines the structural architecture of the DegreeBaba AI Chatbot backend. It details request orchestration, database schemas, local entity resolution mechanics, progressive profiling, deterministic routing shortcuts, and state-machine execution flows.

---

## 1. Request Pipeline & Gating Middleware

The chatbot uses FastAPI to coordinate incoming requests. When a request hits `/chat`, it passes through several concurrent validation layers to reduce response time and filter out unsafe messages.

```
Incoming Request (main.py /chat)
   │
   ├─► validate_site_request (Origin/Referer Check)
   │
   ├─► Concurrent Pre-checks (asyncio.gather):
   │     ├── IP Block Check (is_ip_blocked)
   │     ├── Rate Limits & Caps Check (count_site_messages_today)
   │     └── Prompt Guard Task Launch (check_prompt_safety)
   │
   ├─► Local Heuristic Check (check_policy)
   │
   ▼
Event Stream Initialization
```

### 1.1 Parallelized Pre-checks
To prevent bottlenecks, the backend performs DB checks and Prompt Guard safety scanning in parallel.
* **IP and Rate Gating**: The database checks `is_ip_blocked` and counts today's message volume via `count_site_messages_today`.
* **Prompt Guard Task**: The input safety classification (`check_prompt_safety`) is launched as a background task. If any prior DB check fails (e.g. the IP is blocked or rate limits are exceeded), the safety task is cancelled immediately to save resources.
* **Local Heuristic Policies**: While remote checks are pending, local regular expression checks scan for identity drift, instruction extraction, and competitor impersonation.

### 1.2 Cross-Site Gating
The database constraints link each session ID to a specific site key. If a session UUID is reused with a different site key, `ensure_session` throws a `SessionSiteMismatchError`. The entry endpoints catch this and return a `403 Forbidden` response to prevent unauthorized session sharing.

---

## 2. Database Schema & State Context

DegreeBaba stores its catalog and operational logs in a PostgreSQL database (supporting `pgvector`).

### 2.1 Core Schema Components
* **`universities` / `courses` / `specializations`**: The catalog hierarchy. Courses reference universities, and specializations map to both, with cascade deletion enabled.
* **`entity_search`**: A search-optimized trigram index table storing names, slugs, and a `VECTOR(768)` column for semantic searches.
* **`session_context`**: Tracks active slugs (`current_university_slug`, `current_course_slug`, `current_specialization_slug`), a `comparison_context` JSONB for comparisons, and a `profile_context` JSONB for subjective recommendation flows.

### 2.2 Atomic Updates
The query engine uses common table expressions (CTEs) to bundle database writes. For example, when logging a message:
```sql
WITH inserted AS (
    INSERT INTO messages(...) VALUES(...) RETURNING id
), touched_session AS (
    UPDATE sessions SET message_count = message_count + 1, last_active_at = now() WHERE id = $1 RETURNING id
)
SELECT inserted.id FROM inserted JOIN touched_session ON TRUE;
```
This CTE updates session metrics and records history in a single query, reducing connection overhead.

---

## 3. Entity Resolution & Memory Snapping

The entity resolution engine in `resolve.py` matches user queries to catalog database items without using an LLM.

### 3.1 Startup Warm Caching
At startup, `resolve.py` loads universities, courses, and specializations into an in-memory `ENTITY_CACHE`.
* **Zero-Round-Trip Snapping**: The cache stores canonical slugs and display names. This allows snapping functions (`snap_course`, `snap_specialization`) to run locally without hitting the database.

### 3.2 Parsing and Matching Pipeline
1. **Keyword Cleanup**: Removes stop words, factual terms, and query-control terms (e.g., "ignore previous instructions") to isolate brand terms.
2. **Catalog Scan**: Scans the cleaned string against sorted catalog aliases to find exact matches.
3. **Fuzzy Snapping**: If the catalog scan misses, it runs a fuzzy check:
   - Filters out terms matching `GENERIC_NON_ENTITY_TERMS`.
   - Requires a token prefix match of at least 3 characters (`_has_token_overlap`) to prevent false-positives (e.g., matching "admission" to "vinayaka-mission").
4. **Comparison Follow-ups**: If the user asks a follow-up question (e.g., "Which is cheaper?"), it detects the pattern using `_is_comparison_follow_up` and loads the stored comparison slugs from the session database.

---

## 4. State-Based Recommendations & Progressive Leads

For subjective queries (e.g., "Recommend the best MBA"), the chatbot uses a step-by-step questionnaire rather than open-ended model planning.

### 4.1 Recommendation State Machine
If a recommendation intent is identified, the backend steps through a series of questions:
* **Cadence**: Course Type `->` Maximum Budget `->` Study Mode `->` Specialization.
* **State Updates**: The user's replies are stored in `profile_context.qualification`.
* **Completion**: Once all options are collected, it runs a catalog query (`list_courses` with specialization filters) and displays the top matching programs.

### 4.2 Progressive Lead Cadence
To gather user details without blocking the conversation, the chatbot uses a progressive lead system:
* **Turn Counter**: Counts factual turns since the last lead prompt.
* **Fields**: Prompts for one missing field at a time (Name `->` Phone `->` Email) every 2 turns.
* **Lead Creation**: Once all three values are collected, the backend automatically registers the lead in the database and triggers the CRM webhook.
* **Endpoint**: The `/webhook/lead/progressive` endpoint validates and saves individual inputs, and returns the next required field.

---

## 5. Deterministic Routing Framework

To reduce LLM latency and API costs, common factual queries are routed to deterministic SQL functions via `deterministic.py` and `v2_routes.py`.

```
User Query
   │
   ▼
[detect_route] (v2_routes.py)
   │
   ├─► Matches Deterministic Route (fee, eligibility, etc.) ──► Run SQL query & return formatting
   │
   └─► General Intent ──► Route to LangGraph Agent
```

### 5.1 Route Categories
* **`ROUTE_FEE`**: Queries the database directly for program fee figures. If no university context is active, it runs `list_courses` to display matching options from across the catalog.
* **`ROUTE_ELIGIBILITY`**: Checks eligibility rules for the active university and course.
* **`ROUTE_ACCREDITATION`**: Returns UGC and NAAC status details.
* **`ROUTE_SPECIALIZATIONS`**: Fetches specializations for the active course.
* **`ROUTE_REVIEWS` / `ROUTE_RATINGS`**: Retrieves student reviews from the `reviews` table.

### 5.2 Context Tuning
`v2_routes.py` dynamically adjusts the conversation history length based on the identified route type:
- **Class A (Deterministic)**: Sets history size to `0` (bypasses history loading since context is resolved).
- **Class B (Comparison/General)**: Restricts history to `6` turns.
- **Class C (Recommendations)**: Loads the full history window (`8` turns).

---

## 6. LangGraph State Machine Execution

For open-ended queries, the backend uses a compiled LangGraph `StateGraph`.

### 6.1 State and Nodes
* **`node_triage`**: Intercepts greetings and routing requests.
* **`node_resolve_entities`**: Runs entity resolution and updates session context in the database.
* **`node_agent`**: Binds tools to the model and determines the next step.
* **`node_execute_tools`**: Runs tool queries against the database.

### 6.2 Optimization Rules
* **Tool Loop Constraints**: Limits tool calls to `MAX_TOOL_CALLS_PER_TURN = 8` to prevent infinite loops.
* **Bypassing Redundant Tool Binding**: If a tool run returns all necessary facts, the agent skips binding tools in subsequent loops to save tokens.
* **Session Locking**: A locking pool (`_SESSION_LOCKS`) serializes requests for each session ID, protecting against race conditions from double-clicks or rapid inputs.

---

## 7. Token Streaming & Output Guardrails

The chatbot streams tokens to the client while running security checks on the outgoing text.

```
LangGraph Stream Events (astream_events)
   │
   ├─► Buffer chunk text
   │
   ├─► Outbound Guardrail Check (scan_output on trailing window)
   │     ├── Clean ──► Emit text chunk (`event: token`)
   │     └── Leak Detected ──► Replace with safe fallback (`event: replace`)
   │
   ▼
Final Response Sanitization
```

### 7.1 Real-Time Streaming
The `astream_events(version="v2")` loop captures model chunks in real time.
* **Outbound Guardrails**: Before sending each chunk, it checks the text window using `scan_output` to detect system prompt leaks or competitor name drift.
* **Replacement Event**: If a leak is detected, the stream emits an `event: replace` event containing a safe fallback message, replacing the text in the client UI.

---

## 8. Profiling & Observability

### 8.1 Performance Timing Tree
The backend logs execution timing details for each request stage to help identify performance issues.
```
timing_tree
├── pool_ms (DB connection checkout)
├── pre_graph_setup_ms (History, Session, Context loads)
├── resolver_ms (Entity resolution)
├── llm_ms_total (Total LLM API duration)
├── tool_ms_total (Total tool query execution)
└── assistant_persist_ms (DB write time)
```

### 8.2 Background Task Registry
To prevent Python's garbage collector from reclaiming background tasks (like lead scoring or signal logging) mid-execution, all background tasks are registered in a strong-reference set (`_BACKGROUND_TASKS`) and cleaned up only upon completion.
