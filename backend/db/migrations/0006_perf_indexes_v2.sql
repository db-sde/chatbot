-- Migration 0006: Additional performance indexes for hot query paths.
-- Safe to run on existing databases — IF NOT EXISTS makes this idempotent.

-- Enable pg_trgm extension for trigram index
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- list_conversations filters by page_university_slug and sorts by last_active_at
CREATE INDEX IF NOT EXISTS idx_sessions_university ON sessions(page_university_slug);
CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active_at DESC);

-- get_analytics_models filters by role + model_name
CREATE INDEX IF NOT EXISTS idx_messages_role_model ON messages(role, model_name);

-- get_analytics_universities and list_conversations join leads/unanswered by session_id
CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id);
CREATE INDEX IF NOT EXISTS idx_unanswered_session ON unanswered_questions(session_id);

-- lead_score_events is queried by session_id
CREATE INDEX IF NOT EXISTS idx_lead_score_events_session ON lead_score_events(session_id);

-- search_catalog uses ILIKE on entity_search.search_text
CREATE INDEX IF NOT EXISTS idx_entity_search_text_trgm ON entity_search USING gin(search_text gin_trgm_ops);
