-- Migration 0010: Security events and IP blocking system
-- Creates persistent security_events and blocked_ips tables.

CREATE TABLE IF NOT EXISTS security_events (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    ip_address      TEXT,
    user_agent      TEXT,
    session_id      TEXT,

    event_type      TEXT NOT NULL,   -- prompt_injection | policy_violation | output_scan_violation | rate_limit | blocked_ip_access | suspicious_activity
    severity        TEXT NOT NULL DEFAULT 'medium', -- low | medium | high | critical

    payload         TEXT,            -- truncated user message / attack payload
    source          TEXT,            -- prompt_guard_2 | heuristic | policy | output_scan | system
    action_taken    TEXT,            -- blocked | logged | auto_banned
    blocked         BOOLEAN NOT NULL DEFAULT FALSE,

    metadata_json   JSONB
);

CREATE INDEX IF NOT EXISTS idx_security_events_created_at ON security_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_events_ip_address ON security_events(ip_address);
CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_severity   ON security_events(severity);
CREATE INDEX IF NOT EXISTS idx_security_events_blocked    ON security_events(blocked);


CREATE TABLE IF NOT EXISTS blocked_ips (
    id          BIGSERIAL PRIMARY KEY,
    ip_address  TEXT NOT NULL UNIQUE,
    reason      TEXT,
    blocked_by  TEXT NOT NULL DEFAULT 'system',   -- 'system' | 'admin'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ,                       -- NULL means permanent
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    block_type  TEXT NOT NULL DEFAULT 'temporary'  -- temporary | permanent
);

CREATE INDEX IF NOT EXISTS idx_blocked_ips_ip_address  ON blocked_ips(ip_address);
CREATE INDEX IF NOT EXISTS idx_blocked_ips_is_active   ON blocked_ips(is_active);
CREATE INDEX IF NOT EXISTS idx_blocked_ips_expires_at  ON blocked_ips(expires_at);
