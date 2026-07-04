-- Widget settings table: per-site configuration for widget behavior.
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
    updated_by TEXT
);

-- Ensure every existing site gets a default row when referenced.
-- Applications should call upsert_widget_settings to create initial rows.
