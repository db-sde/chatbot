-- Migration 0004: performance indexes for hot query paths.
-- Safe to run on existing databases — IF NOT EXISTS makes this idempotent.

-- count_site_messages_today() joins messages -> sessions on sessions.site_id
-- and filters messages.created_at on every single /chat request.
CREATE INDEX IF NOT EXISTS idx_sessions_site_id ON sessions(site_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);
