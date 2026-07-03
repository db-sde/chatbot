CREATE TABLE flagged_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    reason TEXT NOT NULL,   -- e.g. "off_topic_keyword" | "injection_pattern"
    created_at TIMESTAMPTZ DEFAULT now()
);
