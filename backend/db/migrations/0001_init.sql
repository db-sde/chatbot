CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE universities (
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

CREATE TABLE courses (
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

CREATE TABLE specializations (
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

CREATE TABLE faqs (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL
);

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    review_text TEXT,
    reviewer_name TEXT,
    reviewer_label TEXT
);

CREATE TABLE job_profiles (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    job_title TEXT,
    avg_salary TEXT
);

CREATE TABLE highlights (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    highlight_title TEXT,
    highlight_description TEXT
);

CREATE TABLE fee_plans (
    id SERIAL PRIMARY KEY,
    course_id INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    plan_name TEXT,
    plan_amount TEXT,
    plan_total TEXT
);

CREATE TABLE faculty_members (
    id SERIAL PRIMARY KEY,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    member_name TEXT,
    member_program TEXT,
    member_designation TEXT,
    member_qualification TEXT
);

CREATE TABLE accreditations (
    id SERIAL PRIMARY KEY,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    body_name TEXT,
    body_descriptor TEXT,
    body_detail TEXT
);

CREATE TABLE facts (
    id SERIAL PRIMARY KEY,
    university_id INTEGER REFERENCES universities(id) ON DELETE CASCADE,
    fact_title TEXT,
    fact_description TEXT
);

CREATE TABLE other_specs (
    id SERIAL PRIMARY KEY,
    specialization_id INTEGER REFERENCES specializations(id) ON DELETE CASCADE,
    other_spec_name TEXT,
    other_spec_fee TEXT
);

CREATE TABLE entity_search (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    search_text TEXT NOT NULL,
    embedding VECTOR(768)
);
CREATE INDEX idx_entity_search_type ON entity_search(entity_type);
CREATE UNIQUE INDEX idx_entity_search_entity ON entity_search(entity_type, entity_id);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id TEXT NOT NULL,
    page_university_slug TEXT,
    summary TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    last_active_at TIMESTAMPTZ DEFAULT now(),
    message_count INTEGER DEFAULT 0
);

CREATE TABLE session_context (
    session_id UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    current_university_slug TEXT,
    current_course_slug TEXT,
    current_specialization_slug TEXT,
    last_updated TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE leads (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id),
    name TEXT,
    phone TEXT,
    email TEXT,
    course_interest TEXT,
    trigger_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE lead_score_events (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    points INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE lead_asks (
    session_id UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    asked_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE unanswered_questions (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    session_id UUID REFERENCES sessions(id),
    university_slug TEXT,
    course_slug TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE content_chunks (
    id SERIAL PRIMARY KEY,
    source_url TEXT,
    chunk_text TEXT,
    embedding VECTOR(768),
    updated_at TIMESTAMPTZ DEFAULT now()
);
