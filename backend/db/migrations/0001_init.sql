-- Consolidated Migration: Final Database Schema
-- Idempotent, safe to initialize from empty or apply on existing schemas.

-- ── Extensions ──
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Universities Table ──
CREATE TABLE IF NOT EXISTS universities (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT,
    established_year TEXT,
    naac_grade TEXT,
    ugc_approved TEXT,
    mode_of_learning TEXT,
    starting_fee NUMERIC,
    num_programs TEXT,
    about_content TEXT,
    why_choose_content TEXT,
    admission_steps TEXT,
    admission_fee_note TEXT,
    emi_content TEXT,
    exam_content TEXT,
    faculty_intro TEXT,
    placement_content TEXT,
    seo_title TEXT,
    meta_description TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Courses Table ──
CREATE TABLE IF NOT EXISTS courses (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    program_name TEXT NOT NULL,
    duration TEXT,
    mode TEXT,
    naac_grade TEXT,
    ugc_status TEXT,
    total_fee NUMERIC,
    starting_fee NUMERIC,
    num_specializations TEXT,
    about_content TEXT,
    eligibility_content TEXT,
    eligibility_summary TEXT,
    admission_steps TEXT,
    admission_fee_note TEXT,
    syllabus_content TEXT,
    placement_content TEXT,
    certificate_description TEXT,
    validity TEXT,
    emi_amount TEXT,
    seo_title TEXT,
    meta_description TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Specializations Table ──
CREATE TABLE IF NOT EXISTS specializations (
    id SERIAL PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    spec_name TEXT NOT NULL,
    duration TEXT,
    mode TEXT,
    naac_grade TEXT,
    ugc_status TEXT,
    total_fee NUMERIC,
    about_content TEXT,
    eligibility_content TEXT,
    eligibility_summary TEXT,
    syllabus_content TEXT,
    exam_content TEXT,
    admission_steps TEXT,
    admission_fee_note TEXT,
    placement_content TEXT,
    certificate_description TEXT,
    emi_amount TEXT,
    seo_title TEXT,
    meta_description TEXT,
    raw_json JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── FAQs Table (Dead) ──
CREATE TABLE IF NOT EXISTS faqs (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL
);

-- ── Reviews Table (Dead) ──
CREATE TABLE IF NOT EXISTS reviews (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    review_text TEXT,
    reviewer_name TEXT,
    reviewer_label TEXT
);

-- ── Job Profiles Table (Dead) ──
CREATE TABLE IF NOT EXISTS job_profiles (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    job_title TEXT,
    avg_salary TEXT
);

-- ── Highlights Table (Dead) ──
CREATE TABLE IF NOT EXISTS highlights (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    highlight_title TEXT,
    highlight_description TEXT
);

-- ── Fee Plans Table (Dead) ──
CREATE TABLE IF NOT EXISTS fee_plans (
    id SERIAL PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    plan_name TEXT,
    plan_amount TEXT,
    plan_total TEXT
);

-- ── Faculty Members Table (Dead) ──
CREATE TABLE IF NOT EXISTS faculty_members (
    id SERIAL PRIMARY KEY,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    member_name TEXT,
    member_program TEXT,
    member_designation TEXT,
    member_qualification TEXT
);

-- ── Accreditations Table (Dead) ──
CREATE TABLE IF NOT EXISTS accreditations (
    id SERIAL PRIMARY KEY,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    body_name TEXT,
    body_descriptor TEXT,
    body_detail TEXT
);

-- ── Facts Table (Dead) ──
CREATE TABLE IF NOT EXISTS facts (
    id SERIAL PRIMARY KEY,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    fact_title TEXT,
    fact_description TEXT
);

-- ── Other Specializations Table (Dead) ──
CREATE TABLE IF NOT EXISTS other_specs (
    id SERIAL PRIMARY KEY,
    specialization_id INTEGER REFERENCES specializations(id) ON DELETE CASCADE,
    other_spec_name TEXT,
    other_spec_fee TEXT
);

-- ── Entity Search Table ──
CREATE TABLE IF NOT EXISTS entity_search (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    search_text TEXT NOT NULL
);

-- ── Sessions Table ──
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id TEXT NOT NULL,
    page_university_slug TEXT,
    summary TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    last_active_at TIMESTAMPTZ DEFAULT now(),
    message_count INTEGER DEFAULT 0,
    ip_address INET,
    user_agent TEXT,
    lead_intent_detected BOOLEAN DEFAULT FALSE,
    lead_intent_type TEXT,
    lead_intent_confidence NUMERIC(4,3),
    lead_intent_reasoning TEXT,
    lead_ask_triggered_by TEXT
);

-- ── Session Context Table ──
CREATE TABLE IF NOT EXISTS session_context (
    session_id UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    current_university_slug TEXT,
    current_course_slug TEXT,
    current_specialization_slug TEXT,
    last_updated TIMESTAMPTZ DEFAULT now()
);

-- ── Messages Table ──
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    response_time_ms INTEGER,
    ttft_ms INTEGER,
    model_name TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost_usd NUMERIC(12,8),
    tool_execution_time_ms INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- ── Leads Table ──
CREATE TABLE IF NOT EXISTS leads (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    name TEXT,
    phone TEXT,
    email TEXT,
    course_interest TEXT,
    trigger_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Lead Score Events Table ──
CREATE TABLE IF NOT EXISTS lead_score_events (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    points INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Lead Asks Table ──
CREATE TABLE IF NOT EXISTS lead_asks (
    session_id UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    asked_at TIMESTAMPTZ DEFAULT now()
);

-- ── Unanswered Questions Table ──
CREATE TABLE IF NOT EXISTS unanswered_questions (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    university_slug TEXT,
    course_slug TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Content Chunks Table (Dead) ──
CREATE TABLE IF NOT EXISTS content_chunks (
    id SERIAL PRIMARY KEY,
    source_url TEXT,
    chunk_text TEXT,
    embedding VECTOR(768),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ── Flagged Messages Table ──
CREATE TABLE IF NOT EXISTS flagged_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    layer TEXT NOT NULL DEFAULT 'unknown',
    risk_score NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    reason TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Widget Settings Table ──
CREATE TABLE IF NOT EXISTS widget_settings (
    site_id TEXT PRIMARY KEY,
    show_estimated_wait_time BOOLEAN DEFAULT true,
    sound_notifications BOOLEAN DEFAULT true,
    desktop_notifications BOOLEAN DEFAULT true,
    mobile_message_preview BOOLEAN DEFAULT true,
    agent_typing_indicator BOOLEAN DEFAULT true,
    visitor_typing_indicator BOOLEAN DEFAULT true,
    browser_tab_notifications BOOLEAN DEFAULT true,
    hide_when_offline BOOLEAN DEFAULT false,
    hide_on_desktop BOOLEAN DEFAULT false,
    hide_on_mobile BOOLEAN DEFAULT false,
    offline_if_no_agents BOOLEAN DEFAULT false,
    emoji_picker_enabled BOOLEAN DEFAULT true,
    file_upload_enabled BOOLEAN DEFAULT true,
    chat_rating_enabled BOOLEAN DEFAULT true,
    email_transcript_enabled BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now(),
    updated_by TEXT,
    primary_color TEXT DEFAULT '#135d66',
    widget_title TEXT DEFAULT 'DegreeBaba Assistant',
    bot_name TEXT DEFAULT 'DegreeBaba Assistant',
    welcome_message TEXT DEFAULT 'Hello! Ask me about colleges, courses, admissions and fees.',
    logo_url TEXT,
    show_on_mobile BOOLEAN DEFAULT true,
    show_on_desktop BOOLEAN DEFAULT true,
    lead_capture_enabled BOOLEAN DEFAULT true,
    capture_name BOOLEAN DEFAULT true,
    capture_email BOOLEAN DEFAULT true,
    capture_phone BOOLEAN DEFAULT true,
    lead_trigger TEXT DEFAULT 'during_chat',
    lead_form_title TEXT DEFAULT 'Request callback',
    lead_form_description TEXT DEFAULT 'A counsellor can follow up with you.'
);

-- ── Security Events Table ──
CREATE TABLE IF NOT EXISTS security_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address TEXT,
    user_agent TEXT,
    session_id TEXT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    payload TEXT,
    source TEXT,
    action_taken TEXT,
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    metadata_json JSONB,
    country TEXT NOT NULL DEFAULT 'India'
);

-- ── Blocked IPs Table ──
CREATE TABLE IF NOT EXISTS blocked_ips (
    id BIGSERIAL PRIMARY KEY,
    ip_address TEXT NOT NULL UNIQUE,
    reason TEXT,
    blocked_by TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    block_type TEXT NOT NULL DEFAULT 'temporary'
);

-- ── Pre-populate default widget settings ──
INSERT INTO widget_settings (site_id) VALUES ('default') ON CONFLICT (site_id) DO NOTHING;


-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_entity_search_type ON entity_search(entity_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_search_entity ON entity_search(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_flagged_messages_layer ON flagged_messages(layer);
CREATE INDEX IF NOT EXISTS idx_flagged_messages_session ON flagged_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_flagged_messages_created_at ON flagged_messages(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_unanswered_session ON unanswered_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_unanswered_created_at ON unanswered_questions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_ip ON sessions(ip_address);

CREATE INDEX IF NOT EXISTS idx_messages_observability ON messages(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_lead_intent ON sessions(lead_intent_detected) WHERE lead_intent_detected = TRUE;

CREATE INDEX IF NOT EXISTS idx_courses_university ON courses(university_id);
CREATE INDEX IF NOT EXISTS idx_courses_fee ON courses(total_fee);
CREATE INDEX IF NOT EXISTS idx_courses_mode ON courses(mode);
CREATE INDEX IF NOT EXISTS idx_specializations_course ON specializations(course_id);
CREATE INDEX IF NOT EXISTS idx_specializations_university ON specializations(university_id);
CREATE INDEX IF NOT EXISTS idx_faqs_entity ON faqs(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_reviews_entity ON reviews(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_sessions_site_id ON sessions(site_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

CREATE INDEX IF NOT EXISTS idx_sessions_university ON sessions(page_university_slug);
CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role_model ON messages(role, model_name);
CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id);
CREATE INDEX IF NOT EXISTS idx_lead_score_events_session ON lead_score_events(session_id);
CREATE INDEX IF NOT EXISTS idx_entity_search_text_trgm ON entity_search USING gin(search_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_security_events_created_at ON security_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_ip_address ON security_events(ip_address);
CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_security_events_blocked ON security_events(blocked);

CREATE INDEX IF NOT EXISTS idx_blocked_ips_ip_address ON blocked_ips(ip_address);
CREATE INDEX IF NOT EXISTS idx_blocked_ips_is_active ON blocked_ips(is_active);
CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires_at ON blocked_ips(expires_at);


-- ── Schema Delta Updates for Existing Databases ──
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ip_address INET;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_agent TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS lead_intent_detected BOOLEAN DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS lead_intent_type TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS lead_intent_confidence NUMERIC(4,3);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS lead_intent_reasoning TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS lead_ask_triggered_by TEXT;

ALTER TABLE messages ADD COLUMN IF NOT EXISTS response_time_ms INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS ttft_ms INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS model_name TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS input_tokens INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS output_tokens INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS total_tokens INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS estimated_cost_usd NUMERIC(12,8);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS tool_execution_time_ms INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE unanswered_questions ADD COLUMN IF NOT EXISTS reason TEXT;

ALTER TABLE flagged_messages ADD COLUMN IF NOT EXISTS layer TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE flagged_messages ADD COLUMN IF NOT EXISTS risk_score NUMERIC(5,4) NOT NULL DEFAULT 0.0;

ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS primary_color TEXT DEFAULT '#135d66';
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS widget_title TEXT DEFAULT 'DegreeBaba Assistant';
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS bot_name TEXT DEFAULT 'DegreeBaba Assistant';
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS welcome_message TEXT DEFAULT 'Hello! Ask me about colleges, courses, admissions and fees.';
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS logo_url TEXT;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS show_on_mobile BOOLEAN DEFAULT true;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS show_on_desktop BOOLEAN DEFAULT true;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS lead_capture_enabled BOOLEAN DEFAULT true;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS capture_name BOOLEAN DEFAULT true;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS capture_email BOOLEAN DEFAULT true;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS capture_phone BOOLEAN DEFAULT true;
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS lead_trigger TEXT DEFAULT 'during_chat';
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS lead_form_title TEXT DEFAULT 'Request callback';
ALTER TABLE widget_settings ADD COLUMN IF NOT EXISTS lead_form_description TEXT DEFAULT 'A counsellor can follow up with you.';

ALTER TABLE security_events ADD COLUMN IF NOT EXISTS country TEXT NOT NULL DEFAULT 'India';

