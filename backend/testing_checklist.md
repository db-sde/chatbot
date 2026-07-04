# AI Observability & Cost Analytics — Testing & Validation Checklist

This checklist defines the validation protocol to ensure performance metrics, token usage tracking, LLM pricing calculations, and frontend rendering metrics are correct.

---

## 1. Response Timing & Latency Accuracy
- [ ] **Request Start**: Verify `started_at` in the database matches the actual HTTP request timestamp.
- [ ] **Completion Time**: Verify `completed_at` reflects the moment the final token is generated and the database write completes.
- [ ] **End-to-End Latency (`response_time_ms`)**:
  - Run a query manually and capture time elapsed in the terminal/browser.
  - Verify `response_time_ms` in the database is within ±50ms of the actual network turnaround time.
- [ ] **Verification Query**:
  ```sql
  SELECT content, response_time_ms, started_at, completed_at FROM messages WHERE role = 'assistant' ORDER BY id DESC LIMIT 1;
  ```

## 2. TTFT (Time to First Token) Accuracy
- [ ] **First Token Event**: Verify `t_first_token` is recorded immediately after the planning LLM node completes.
- [ ] **TTFT calculation**:
  - Verify `ttft_ms` is strictly less than `response_time_ms` for all turns.
  - For direct replies (no tools), verify `ttft_ms` matches the generation start.
- [ ] **Verification Query**:
  ```sql
  SELECT content, ttft_ms, response_time_ms FROM messages WHERE role = 'assistant' AND ttft_ms > response_time_ms; -- Should return 0 rows
  ```

## 3. Tool Timing & Execution Latency
- [ ] **Execution Decorator**: Verify that `@timed_tool_execution` captures individual call durations.
- [ ] **JSONB Observability Fields**:
  - Perform a query that executes multiple tools (e.g. comparing NMIMS with Amity).
  - Verify that `tool_calls` in the database contains `started_at`, `completed_at`, `duration_ms`, and `status`.
- [ ] **Verification Query**:
  ```sql
  SELECT tool_calls FROM messages WHERE role = 'assistant' AND tool_calls IS NOT NULL ORDER BY id DESC LIMIT 1;
  ```
  *Ensure output matches format:*
  ```json
  [{"name": "...", "args": {}, "status": "SUCCESS", "duration_ms": 120, "started_at": "...", "completed_at": "...", "result_summary": "..."}]
  ```

## 4. Token Counting & Provider Extraction
- [ ] **Groq Tokens**: Verify token extraction from `prompt_tokens` and `completion_tokens` maps to `input_tokens` and `output_tokens` correctly.
- [ ] **Gemini Tokens**: Verify token extraction from `input_tokens` and `output_tokens` inside `response_metadata`.
- [ ] **Verification**: Query database to confirm non-zero integers are stored in `input_tokens`, `output_tokens`, and `total_tokens` for all processed turns.

## 5. Cost Engine & Pricing Calculations
- [ ] **Central Configuration**: Verify `pricing_config.py` is the single source of truth for pricing constants.
- [ ] **Cost logic**:
  - Gemini Flash: $0.075 / million input, $0.30 / million output.
  - Llama 3.3 70B: $0.59 / million input, $0.79 / million output.
  - Perform manual calculation for a response:
    - Input: 1,000 tokens ($0.000075 on Gemini)
    - Output: 200 tokens ($0.000060 on Gemini)
    - Total: $0.000135
  - Verify `estimated_cost_usd` in the database matches this value exactly.

## 6. Null Metadata & Provider Fallback
- [ ] **Missing Token Stats**: Mock `response_metadata` to be empty or missing `"token_usage"`.
  - Verify that the chat turn still succeeds (zero failures or user-visible exceptions).
  - Verify `input_tokens`, `output_tokens`, and `estimated_cost_usd` default gracefully to `NULL` or `0` in the database.
- [ ] **Invalid/Unknown Model**: Send a request using a custom model name.
  - Verify cost calculation defaults cleanly to the `default` fallback configuration in `MODEL_PRICING` without crashing.

## 7. Analytics Endpoints & API Responses
- [ ] **API Overview**: Fetch `/api/admin/analytics/overview`. Verify it returns avg response, avg TTFT, tokens today, cost today, leads count, cost per lead.
- [ ] **API Models**: Fetch `/api/admin/analytics/models`. Verify stats group by model correctly.
- [ ] **API Tools**: Fetch `/api/admin/analytics/tools`. Verify it aggregates and calculates success rates, max duration, average duration, and failures.
- [ ] **API Universities**: Fetch `/api/admin/analytics/universities`. Verify conversion rates are calculated.
- [ ] **API Costs**: Fetch `/api/admin/analytics/costs`. Verify cost totals (today, week, month) and top 10 most expensive chats list.
- [ ] **API Funnel**: Fetch `/api/admin/analytics/funnel`. Verify conversion funnel stages.

## 8. Dashboard & Conversation Timeline UI Rendering
- [ ] **Admin Cards**: Verify Dashboard displays the 6 new cards (Avg Response, TTFT, Tokens Today, Cost Today, Leads, Cost Per Lead) correctly.
- [ ] **Advisor Response Info**: Open a conversation and verify the grey monospace metadata block shows correct values for Model, Response time, TTFT, Token counts, and Cost.
- [ ] **Tool Timeline**: Verify the right-hand tool execution sidebar shows durations (e.g. `45ms`) and green/red status badges (`SUCCESS` / `FAILURE`).
