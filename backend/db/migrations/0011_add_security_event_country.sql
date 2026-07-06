-- Migration 0011: Add country column to security_events table

ALTER TABLE security_events
    ADD COLUMN IF NOT EXISTS country TEXT NOT NULL DEFAULT 'India';
