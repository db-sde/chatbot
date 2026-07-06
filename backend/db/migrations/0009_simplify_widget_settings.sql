-- Add simplified widget settings columns
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

-- Pre-populate default settings row if not present
INSERT INTO widget_settings (site_id) VALUES ('default') ON CONFLICT (site_id) DO NOTHING;
