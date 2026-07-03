-- Migration 0002: Security layer schema upgrades
-- Adds layer + risk_score to flagged_messages, and reason to unanswered_questions.
-- Safe to run on existing databases — uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.

-- Phase 9: Upgrade flagged_messages to record security layer and risk score
-- First create the table if it doesn't exist yet (fresh installs).
CREATE TABLE IF NOT EXISTS flagged_messages (
    id          SERIAL PRIMARY KEY,
    session_id  UUID REFERENCES sessions(id) ON DELETE CASCADE,
    message     TEXT NOT NULL,
    layer       TEXT NOT NULL DEFAULT 'unknown',
    risk_score  NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    reason      TEXT NOT NULL DEFAULT 'unknown',
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- For databases where the table already existed without the new columns:
ALTER TABLE flagged_messages
    ADD COLUMN IF NOT EXISTS layer      TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS risk_score NUMERIC(5,4) NOT NULL DEFAULT 0.0;

-- Ensure reason column exists (was added previously, but make it idempotent)
ALTER TABLE flagged_messages
    ADD COLUMN IF NOT EXISTS reason TEXT NOT NULL DEFAULT 'unknown';

-- Index for admin queries filtering by layer or session
CREATE INDEX IF NOT EXISTS idx_flagged_messages_layer      ON flagged_messages(layer);
CREATE INDEX IF NOT EXISTS idx_flagged_messages_session    ON flagged_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_flagged_messages_created_at ON flagged_messages(created_at DESC);

-- Phase 10: Add reason column to unanswered_questions
ALTER TABLE unanswered_questions
    ADD COLUMN IF NOT EXISTS reason TEXT;

-- Indexes on unanswered_questions for analytics grouping
CREATE INDEX IF NOT EXISTS idx_unanswered_session    ON unanswered_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_unanswered_created_at ON unanswered_questions(created_at DESC);
