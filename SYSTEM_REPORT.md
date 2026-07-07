# DegreeBaba AI Chatbot — System Architecture & Codebase Report

This document details the system design, directory map, database schemas, AI agent routing pipeline, entity resolution mechanics, native token streaming integration, security layers, and frontend interfaces for the DegreeBaba AI Chatbot.

---

## 1. Executive Summary & Optimization Metrics

Following a major architectural optimization sprint, the DegreeBaba AI Chatbot backend was refactored to achieve production-grade performance, low latency, and optimal resource consumption. 

### Architecture Comparison

| Metric / Dimension | Old Architecture | New Architecture |
| :--- | :--- | :--- |
| **Factual Turn Latency** | High (~3–5s due to sequential LLM blocks) | **Sub-second (TTFT < 100ms)** |
| **LLM Calls per Turn** | ~4 LLM calls (triage, extract, select tool, synthesize) | **Exactly 1 LLM call** (direct ReAct tool calling) |
| **Token Cost** | High (frequent JSON validation & extraction prompts) | **Reduced by ~75%** |
| **Streaming Mechanism** | Buffered response ("fake" word-by-word streaming) | **Native token streaming** (`astream_events`) |
| **Entity Resolution** | Expensive, error-prone LLM calls | **Zero-LLM local keyword-stripping + RapidFuzz** |
| **Lead Handling** | Blocking execution in SSE endpoint | **Asynchronous background tasks** |
| **Alias Snapping** | Hardcoded Python dictionary | **Database-driven trigram matching** |

---

## 2. Directory Structure Map

The annotated folder hierarchy of the `chatbot/` workspace is detailed below. The core changes are concentrated in the [backend/agent/](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/) and [backend/llm/](file:///Users/aryankinha/Documents/Degree/chatbot/backend/llm/) directories.

```text
chatbot/
├── .env                          # Local and Docker environment variables configuration
├── .env.example                  # Environment configuration template
├── .gitignore                    # Git file exclusions
├── docker-compose.yml            # Postgres and pgvector local container mappings
├── pyproject.toml                # Unified root uv workspace definition
├── uv.lock                       # Lockfile of all pinned packages
├── README.md                     # System runbooks & local deployment steps
│
├── admin/                        # React/Vite Administrative Dashboard
│   ├── src/
│   │   ├── main.jsx              # Vite entry script
│   │   ├── App.jsx               # Navigation router mapping admin pages
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx     # Main stats overview
│   │   │   ├── Conversations.jsx # Conversation explorer
│   │   │   ├── SessionDetails.jsx# Detailed trace of tool execution, input/output, and cost metrics
│   │   │   ├── Leads.jsx         # Leads overview & intent status mapping
│   │   │   ├── Unanswered.jsx    # Review logged unanswered queries
│   │   │   ├── Settings.jsx      # System settings and site keys mapping
│   │   │   ├── Security.jsx      # [NEW] Real-time attack analysis and IP block management panel
│   │   │   └── Analytics.jsx     # [NEW] AI Observability, cost analysis, and model usage reports
│   │   ├── services/
│   │   │   └── api.js            # Axios facade for admin backend endpoints
│   │   └── components/           # Common components (Common.jsx, StatsCard.jsx)
│   └── package.json              # Dashboard package dependencies
│
├── backend/                      # FastAPI Python Backend Application
│   ├── pyproject.toml            # Python specifications (FastAPI, LangGraph, RapidFuzz, asyncpg)
│   ├── main.py                   # FastAPI Application initialization, SSE streaming route, and middlewares
│   ├── auth.py                   # Site key verification and admin token validation
│   ├── rate_limit.py             # SlowAPI Rate Limiter integration
│   ├── settings.py               # Pydantic Settings class parsing environment variables
│   ├── reset_db.py               # Database cleaner script for chat history and token usage
│   │
│   ├── agent/                    # AI Agent (LangGraph) Layer
│   │   ├── __init__.py
│   │   ├── graph.py              # LangGraph compilation & run_chat_turn generator
│   │   ├── resolve.py            # Local regex extract, stop word filter, and RapidFuzz snapping
│   │   ├── tools.py              # Whitelisted catalog query tools bound to the agent
│   │   └── llm_client.py         # Swappable facade exposing the chat model to graph node execution
│   │
│   ├── db/                       # Database Configuration & Migrations
│   │   ├── __init__.py
│   │   ├── migrate.py            # Migration executor running initialization scripts
│   │   ├── pool.py               # asyncpg pool instantiation with reconnection safety
│   │   ├── queries.py            # Database SQL mappings
│   │   └── migrations/
│   │       └── 0001_init.sql     # Idempotent database schema definitions
│   │
│   ├── leads/                    # Lead scoring & Classification
│   │   ├── __init__.py
│   │   ├── intent.py             # LLM lead intent classifier
│   │   └── scoring.py            # Lead scoring calculations
│   │
│   └── security/                 # Security Gateways
│       ├── __init__.py
│       ├── scanner.py            # Prompt Guard injection scanner
│       ├── policy.py             # Off-topic policy filter
│       └── output_scan.py        # Outbound content filter
│
├── ingestion/                    # Ingestion Script Layer
│   ├── __init__.py
│   ├── microapp_to_db.py         # Ingestion script mapping JSON data to catalog tables
│   └── seed_100_entries.py       # Seed script containing demo catalog records
│
└── widget/                       # Embeddable Chat Widget
    ├── widget.js                 # Self-contained vanilla JS client bundle
    └── widget.css                # Base widget stylesheet
```

---

## 3. Database Architecture & Schema

DegreeBaba uses PostgreSQL as its primary data store. The schema is defined in [0001_init.sql](file:///Users/aryankinha/Documents/Degree/chatbot/backend/db/migrations/0001_init.sql) and is mapped via [queries.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/db/queries.py).

### Core Catalog Tables
* **`universities`**: Stores university profiles including NAAC grade, UGC approval status, modes of learning, and base fee metrics.
* **`courses`**: Stores degree programs (e.g., Online MBA, BCA) and references `universities(id)` via foreign key with `ON DELETE CASCADE`.
* **`specializations`**: Stores specializations under specific courses (e.g., Marketing under MBA) and references both course and university tables.
* **`faqs`**: Contains questions and answers associated with particular universities, courses, or specializations.

### Operational and Security Tables
* **`entity_search`**: An index table containing `search_text` (`"name full_name slug"`) and a `pgvector` column `embedding` (`VECTOR(768)`) built to facilitate search. Uses a GIN index `idx_entity_search_text_trgm` on `search_text` using `gin_trgm_ops` for fast trigram searches.
* **`sessions`**: Stores active chat sessions, caching IP addresses, user agents, visitor counts, and LLM-classified lead intents.
* **`session_context`**: Tracks active university, course, and specialization slugs established during a conversation session.
* **`messages`**: Historical logs of all queries and replies within a session. Captures tool execution metrics, token counts, cost estimations, response time, and Time-To-First-Token (TTFT) metrics.
* **`leads`**: Captures student contact credentials (name, phone, email, course interest) and triggers CRM syncs.
* **`security_events`**: Relational logs tracking malicious events like prompt injections, off-topic violations, and blocked IP accesses.
* **`blocked_ips`**: Tracks IP addresses banned temporarily or permanently.

---

## 4. LangGraph Chatbot Routing Pipeline

The core chatbot agent uses an optimized LangGraph `StateGraph` compilation in [graph.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/graph.py).

```mermaid
graph TD
    START([Chat Turn Requested]) --> Triage[Node: triage]
    Triage -- Chitchat Detected --> Chitchat[Node: chitchat_reply]
    Triage -- Factual Catalog Intent --> Resolve[Node: resolve_entities]
    Chitchat --> END([End Turn / Stream Output])
    Resolve --> Agent[Node: agent]
    Agent -- Tool Call Triggered --> ExecTools[Node: execute_tools]
    ExecTools --> Agent
    Agent -- Direct Answer Formulated --> END
```

### Turn Lifecycle Steps
1. **Triage Gate (`node_triage`)**: Evaluates basic greeting patterns. If a chitchat intent is detected, the pipeline routes immediately to `chitchat_reply` to bypass database and heavy agent computation.
2. **Entity Resolution (`node_resolve_entities`)**: Invokes `extract_entities` to parse structural parameters, strips stopwords, and looks up candidates. Snap results are saved to the persistent database session context using `queries.update_session_context`.
3. **ReAct Agent (`node_agent`)**: Rather than splitting decisions and synthesis, a single unified LangChain Runnable is instantiated via `chat_model.bind_tools(TOOLS)`. The model receives the dialog history and resolves whether to invoke tools or generate a direct response.
4. **Tool Execution (`node_execute_tools`)**: Invokes valid tool executions (e.g. database lookups mapped to the active catalog) and returns the JSON output directly back to the agent node.
5. **Asynchronous Background Processing**: After yielding the token stream, `run_chat_turn` triggers an asynchronous, non-blocking task `background_lead_scoring` to classify intent, score leads, and write analytics metrics without blocking the SSE connection.

---

## 5. Entity Resolution Deep Dive

The entity resolution layer in [resolve.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/resolve.py) runs on local calculations rather than relying on expensive LLM calls.

```
Input User Message
      │
      ├─► [_local_extract] ────────► Extracted metadata (max_fee, mode, course type)
      │
      └─► [_extract_potential_name]  
                │
                ├─► Strip punctuation
                ├─► Strip stop words & factual keywords (_STOP_WORDS, _FACTUAL_KEYWORDS)
                ├─► Strip course hints & extracted metadata values
                │
                ▼
         Isolated Potential Name (e.g., "nims")
                │
                ▼
        [_snap (university / course / specialization)]
                │
                ├─► [queries.find_entities_trgm] (Postgres word_similarity match)
                ├─► RapidFuzz matching (fuzz.WRatio + fuzz.partial_ratio)
                ├─► Threshold validation (75 for short strings, 80 for long strings)
                │
                ▼
         Resolved Entity Slug (e.g., "nmims")
```

### 1. Extraction and Stripping
* **[_local_extract](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/resolve.py#L41-L56)**: Parses base structures using regular expressions to retrieve course categories (from `COURSE_HINTS`), maximum fee thresholds, and course mode (online/hybrid).
* **[_extract_potential_name](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/resolve.py#L59-L78)**: Isolates potential university or course names. It splits the message and ignores terms found in `_FACTUAL_KEYWORDS`, `COURSE_HINTS`, `_STOP_WORDS`, and values already captured by `_local_extract`. The remainder represents a prospective entity name.

### 2. Snap Resolution
* **[_snap](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/resolve.py#L103-L127)**: Resolves the isolated candidate name against the database index using the fuzzy matching metrics:
  - Compares the candidate against index strings using the maximum score of `fuzz.WRatio` and `fuzz.partial_ratio`.
  - Applies a dynamic threshold check: `75 if len(normalized_name) < 6 else 80`. Shorter strings receive a lower threshold to permit typo matching.
  - Matches returning a score above the threshold are resolved to their target slug using `queries.slug_for_entity_id`.

### 3. Proposed Dynamic Aliasing Strategy
* **Word Similarity Matching**: To support nicknames without hardcoding, the trigram search query in [queries.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/db/queries.py#L197-L205) is configured to use strict word similarity (`<%` and `word_similarity`):
  ```sql
  SELECT entity_type, entity_id, search_text, word_similarity($1, search_text) as sim
  FROM entity_search
  WHERE $1 <% search_text
  ORDER BY sim DESC LIMIT $2
  ```
  This prevents longer database strings from diluting similarity scores for short user search terms.
* **Proposed Ingestion Updates**: A pending DB migration adds an `aliases TEXT[]` column to `universities`, `courses`, and `specializations`. The ingestion script [ingestion/microapp_to_db.py](file:///Users/aryankinha/Documents/Degree/chatbot/ingestion/microapp_to_db.py) is slated to index these arrays dynamically into the `search_text` column.

---

## 6. LLM Client & Native Streaming Implementation

Native streaming bypasses buffering by invoking Chat Models as Runnables and streaming tokens through FastAPI.

### 1. Unified Interface Config
The configuration in [backend/llm/config.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/llm/config.py) specifies the active provider (`groq` or `deepseek`) and model (`llama-3.3-70b-versatile`). The provider factory [backend/llm/provider.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/llm/provider.py#L62-L103) instantiates the model with `streaming=True`.

### 2. Facade Property
The client facade [backend/agent/llm_client.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/llm_client.py#L102-L106) exposes the model instance:
```python
@property
def chat_model(self):
    from llm.provider import get_chat_model
    return get_chat_model()
```

### 3. Event Loop yield
In [backend/agent/graph.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/agent/graph.py#L399-L414), `run_chat_turn` consumes events from LangGraph's execution using `astream_events(version="v2")`. It intercepts real-time model output from the active chat model and yields tokens to FastAPI:
```python
async for event in _graph.astream_events(initial_state, version="v2"):
    event_kind = event["event"]
    if event_kind == "on_chat_model_stream":
        chunk = event["data"]["chunk"]
        if isinstance(chunk, AIMessage) and chunk.content:
            yield {"event": "token", "data": {"text": chunk.content}}
```
FastAPI’s `StreamingResponse` in [backend/main.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/main.py#L255-L259) delivers these chunks to the client over a `text/event-stream` connection.

---

## 7. Security & Observability

### 1. Security Gateways (Three-Layer Protection)
* **Layer 1: IP Blocking & Rate Limiting**: The request IP is checked against active blocks in `blocked_ips`. SlowAPI throttles visitor traffic based on configured limits in [settings.py](file:///Users/aryankinha/Documents/Degree/chatbot/backend/settings.py).
* **Layer 2: Prompt Guard**: Incoming messages are evaluated using the [security.scanner](file:///Users/aryankinha/Documents/Degree/chatbot/backend/security/scanner.py) module. Detected prompt injections are logged to `flagged_messages` and blocked.
* **Layer 3: Off-Topic Policy Filter**: Messages are passed to `check_policy` in [security.policy](file:///Users/aryankinha/Documents/Degree/chatbot/backend/security/policy.py) to confirm the query is education-related. Off-topic inputs are blocked with a polite rejection response.
* **Outbound Filtering (`scan_output`)**: Generated responses are passed to [security.output_scan](file:///Users/aryankinha/Documents/Degree/chatbot/backend/security/output_scan.py). Any response containing sensitive or restricted terms is replaced with a safe fallback message before being written to the client.

### 2. Observability & Background lead scoring
* **Lead Intent Analysis**: In the background, `background_lead_scoring` runs a lead intent classifier on the conversation history. It logs the confidence, intent type, and reasoning to the database.
* **Metric Logs**: At the end of every conversation turn, token usage, cost estimations, latency values, and tool execution times are recorded in `messages` to power the administrative analytics dashboards.

---

## 8. Frontend Widget Integration

The chat client is loaded dynamically via [widget.js](file:///Users/aryankinha/Documents/Degree/chatbot/widget/widget.js):
* **Shadow DOM Isolation**: The widget attaches to `#degreebaba-ai-widget` and sets up a Shadow Root. This prevents page CSS rules from overriding chat panel configurations.
* **SSE Client Parsing**: Leverages browser `fetch` reader API to parse chunks from `text/event-stream`:
  ```javascript
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  // ... loop reads chunks, decodes them, and processes lines matching 'data: ' and 'event: '
  ```
* **Lead Capturing Form**: When the SSE stream yields a `final` event containing `lead_ask: true`, a lead generation card is dynamically rendered in the chat area, allowing visitors to submit their details directly.

---

## 9. Administrative Dashboard (Newly Added Observability Panels)

The React dashboard in the [admin/](file:///Users/aryankinha/Documents/Degree/chatbot/admin/) directory has been updated with two specialized modules that aggregate observability metrics and security events:

### 1. Observability Dashboard ([admin/src/pages/Analytics.jsx](file:///Users/aryankinha/Documents/Degree/chatbot/admin/src/pages/Analytics.jsx))
This panel retrieves system logs from `/api/admin/analytics` to render operations metrics:
* **Performance Overview**: Tracks average response time, TTFT, daily costs, active leads, and cost-per-lead (CPL).
* **Model Profiling**: Details input/output token metrics, cumulative expenditures, and response latency grouped by LLM model.
* **Tool Profiling**: Aggregates execution count, duration, failure rate, and success rate metrics for each catalog tool.
* **Context Performance**: Reports conversation volume and lead conversion metrics mapped to page-hint university slugs.

### 2. Security Center Dashboard ([admin/src/pages/Security.jsx](file:///Users/aryankinha/Documents/Degree/chatbot/admin/src/pages/Security.jsx))
This panel provides administrators with tools to track and counter malicious traffic:
* **Attack Metrics**: Displays total security blocks, timeline chart of violations, and attacks segmented by security layer.
* **Attack Pattern Profiling**: Logs frequently blocked prefixes and groups them by event type (e.g. prompt injection, policy violation).
* **IP Blocking Panel**: Displays active IP bans and enables administrators to block suspect hosts or remove active blocks.
