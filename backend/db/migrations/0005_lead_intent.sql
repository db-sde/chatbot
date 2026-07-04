-- Migration 0005: LLM Lead Intent Triggers and Logging
-- Adds observability and intent classification columns to the sessions table.
-- Fully backward compatible.

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS lead_intent_detected BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS lead_intent_type TEXT,
    ADD COLUMN IF NOT EXISTS lead_intent_confidence NUMERIC(4,3),
    ADD COLUMN IF NOT EXISTS lead_intent_reasoning TEXT,
    ADD COLUMN IF NOT EXISTS lead_ask_triggered_by TEXT;

-- Create index on lead_intent_detected for analytics groupings
CREATE INDEX IF NOT EXISTS idx_sessions_lead_intent ON sessions(lead_intent_detected) WHERE lead_intent_detected = TRUE;
