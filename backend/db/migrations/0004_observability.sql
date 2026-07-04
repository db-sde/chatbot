-- Migration 0004: Observability & Cost Analytics Schema Upgrades
-- Adds performance, token usage, and cost tracking columns to the messages table.
-- Fully backward compatible. Existing rows remain valid with NULL values.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS response_time_ms INTEGER,
    ADD COLUMN IF NOT EXISTS ttft_ms INTEGER,
    ADD COLUMN IF NOT EXISTS model_name TEXT,
    ADD COLUMN IF NOT EXISTS input_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS total_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS estimated_cost_usd NUMERIC(12,8),
    ADD COLUMN IF NOT EXISTS tool_execution_time_ms INTEGER,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

-- Add index on session_id and created_at/id for analytics queries
CREATE INDEX IF NOT EXISTS idx_messages_observability ON messages(session_id, created_at DESC);
