-- Migration 0003: Session metadata — ip_address and user_agent capture
-- Safe to run on existing databases. Uses ADD COLUMN IF NOT EXISTS.

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS ip_address INET,
    ADD COLUMN IF NOT EXISTS user_agent TEXT;

-- Index for admin filtering/sorting by IP (useful for abuse detection)
CREATE INDEX IF NOT EXISTS idx_sessions_ip ON sessions(ip_address);
