# Schema Gap Audit Report

This audit report identifies discrepancy zones between the python application code references and the database schema definition.

---

## 1. Discovered Gaps & Analysis

The primary gap identified during runtime was **not** that the previous consolidated migration was missing definitions, but that the existing PostgreSQL database instances already recorded `"0001_init.sql"` in their `schema_migrations` metadata. This caused the migration runner (`migrate.py`) to skip applying the updated consolidated file entirely.

Furthermore, pre-existing tables created under the old `0001_init.sql` schema blocked the application of columns introduced in later migrations, since `CREATE TABLE IF NOT EXISTS` is a no-op if the table exists.

To address this, the true consolidated migration now dynamically updates existing tables by appending delta schema columns.

### Audit Summary:
1. **Missing Tables:** None. All 25 required tables are defined in the consolidated schema.
2. **Missing Columns:** The columns added in later historical migrations (such as `ip_address`, `user_agent`, `lead_intent_detected`, etc. in `sessions`, and `response_time_ms`, `ttft_ms`, etc. in `messages`) were missing on existing databases.
3. **Missing Indexes:** All indexes referenced in hot paths are fully included.
4. **Missing Constraints:** Foreign keys and deletion cascades are validated.
5. **Missing JSONB fields:** `tool_calls` in `messages` and `metadata_json` in `security_events` are correctly preserved as JSONB.
6. **Missing Analytics fields:** Observability metrics (`response_time_ms`, `ttft_ms`, token usage, `estimated_cost_usd`, and `model_name`) are fully tracked.
7. **Missing Security fields:** Security features (`security_events` table, `blocked_ips` table, and the `country` geolocation column) are fully supported.

---

## 2. True Final Schema Definition and Delta Updates

The consolidated migration script was updated to perform the following:
* Create tables/extensions/indexes if not existing (fresh databases).
* Execute `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...` statements for all database columns introduced across historical migrations `0002_*` to `0011_*` (existing databases).

### Consolidated Delta Mapping:

| Table | Added Column | DataType | Description |
| :--- | :--- | :--- | :--- |
| `sessions` | `ip_address` | INET | Geolocation client identifier |
| `sessions` | `user_agent` | TEXT | Client browser metadata |
| `sessions` | `lead_intent_detected` | BOOLEAN | Pre-scored lead intent tag |
| `sessions` | `lead_intent_type` | TEXT | Intent type classifier |
| `sessions` | `lead_intent_confidence` | NUMERIC | Confidence level metric |
| `sessions` | `lead_intent_reasoning` | TEXT | Intent analyzer explanation |
| `sessions` | `lead_ask_triggered_by` | TEXT | Lead CTA context descriptor |
| `messages` | `response_time_ms` | INTEGER | Time until message completion |
| `messages` | `ttft_ms` | INTEGER | Time to first token |
| `messages` | `model_name` | TEXT | Chatbot generator engine model |
| `messages` | `input_tokens` | INTEGER | Model input sequence count |
| `messages` | `output_tokens` | INTEGER | Model output sequence count |
| `messages` | `total_tokens` | INTEGER | Combined token count |
| `messages` | `estimated_cost_usd` | NUMERIC | Calculated model transaction fee |
| `messages` | `tool_execution_time` | INTEGER | Total external system call time |
| `messages` | `started_at` | TIMESTAMPTZ | Start of message generation |
| `messages` | `completed_at` | TIMESTAMPTZ | Complete timestamp |
| `unanswered_questions` | `reason` | TEXT | Reason for lack of matching entity |
| `flagged_messages` | `layer` | TEXT | Threat detection engine layer |
| `flagged_messages` | `risk_score` | NUMERIC | Threat severity metrics |
| `security_events` | `country` | TEXT | Geolocation geoblocking check country |

---

## 3. Migration Runner Verification

The migrations runner in [`migrate.py`](file:///Users/aryankinha/Documents/Degree/chatbot/backend/db/migrate.py) was updated to **always** run the consolidated `0001_init.sql` file. This forces a check and dynamic update of missing columns on existing databases without deleting or rewriting historical database records.
