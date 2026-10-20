CREATE TABLE IF NOT EXISTS catalog_events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL,
    source TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('university','course','specialization')),
    source_id TEXT NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','applied','ignored','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    entity_slug TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(source, entity_type, source_id, version)
);
CREATE INDEX IF NOT EXISTS catalog_events_pending ON catalog_events(next_attempt_at,id) WHERE status='queued';

CREATE TABLE IF NOT EXISTS catalog_sources (
    source TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('university','course','specialization')),
    source_id TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    entity_slug TEXT NOT NULL,
    applied_version BIGINT NOT NULL,
    source_url TEXT NOT NULL,
    source_path TEXT NOT NULL,
    original_payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(source,entity_type,source_id),
    UNIQUE(entity_type,entity_id),
    UNIQUE(source,source_path)
);
CREATE INDEX IF NOT EXISTS catalog_sources_path ON catalog_sources(source_path);

CREATE TABLE IF NOT EXISTS catalog_sections (
    source TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    section_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english',title || ' ' || content)) STORED,
    PRIMARY KEY(source,entity_type,source_id,section_id),
    FOREIGN KEY(source,entity_type,source_id) REFERENCES catalog_sources(source,entity_type,source_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS catalog_sections_search ON catalog_sections USING GIN(search_vector);

CREATE TABLE IF NOT EXISTS catalog_revision (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK(singleton),
    revision BIGINT NOT NULL DEFAULT 0
);
INSERT INTO catalog_revision(singleton) VALUES(TRUE) ON CONFLICT DO NOTHING;
