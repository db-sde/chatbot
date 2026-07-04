# Widget Configuration & Behavior Management — Implementation Report

## Goal
Allow non-technical admin users to control widget behavior (notifications, visibility, features) per site, and have those settings take effect immediately for all embedded widgets without code deploys.

## What Was Built

### 1. Database schema
**File:** `backend/db/migrations/0007_widget_settings.sql`

- New table `widget_settings` keyed by `site_id` (text primary key).
- Boolean columns for every configurable behavior, all defaulting to sensible "enabled" values.
- Audit columns: `updated_at`, `updated_by`.
- Auto-creation: `get_widget_settings()` inserts a default row if none exists, preserving backward compatibility for existing sites.

### 2. Backend queries
**File:** `backend/db/queries.py`

- `get_widget_settings(pool, site_id)` — fetch or create defaults.
- `upsert_widget_settings(pool, site_id, settings)` — partial updates, only known columns are written.
- `list_widget_settings(pool)` — list all configured sites.

### 3. API endpoints
**File:** `backend/main.py`

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/admin/widget-settings` | Admin | List all site settings. |
| GET | `/api/admin/widget-settings/{site_id}` | Admin | Get settings for one site. |
| PUT | `/api/admin/widget-settings/{site_id}` | Admin | Update settings (partial). |
| GET | `/public/widget-settings?site_key=...` | Public* | Widget runtime fetches its config. |
| GET | `/api/admin/settings/site-domains` | Admin | Returns configured site keys/domains for the site picker. |

\* The public endpoint runs the same `validate_site_request()` origin/site_key check used by `/chat`, so only allowed domains can read a site's config.

The public endpoint returns a **safe, filtered** subset of columns; internal/admin fields are stripped.

### 4. Admin dashboard UI
**Files:**
- `admin/src/pages/WidgetSettings.jsx` — site selector + form wrapper.
- `admin/src/components/WidgetSettingsForm.jsx` — toggle grid grouped by Notification, Visibility, and Feature sections.
- `admin/src/services/api.js` — `getWidgetSettings`, `updateWidgetSettings`, `listWidgetSettings`.

The page loads configured sites from `/api/admin/settings/site-domains` and existing widget-settings rows, defaults to the first site, and saves via PUT. Changes are announced as "active for new sessions" (the widget reads settings on every page load).

### 5. Widget runtime behavior
**File:** `widget/widget.js`

On load the widget:
1. Fetches `/public/widget-settings?site_key=xxx`.
2. Falls back to hard-coded defaults if the call fails.
3. Applies settings immediately:
   - **Visibility:** hides bubble on desktop/mobile per flags; hides when offline if configured.
   - **Notifications:** sound, desktop (Notification API), browser-tab title flash, mobile message preview.
   - **Typing indicators:** agent dots while waiting for first token; visitor typing events throttled to ~1.2 s.
   - **Features:** emoji picker, file upload, chat rating, email transcript placeholders.

The widget also preserves existing capabilities: session restoration, paginated history, lead form, quick-reply chips, and SSE streaming replies.

## Settings Reference

| Setting | Default | Admin section | Runtime effect |
|---------|---------|---------------|----------------|
| `show_estimated_wait_time` | `true` | Notification | Status text shows "Typically replies instantly" vs generic "AI Advisor online". |
| `sound_notifications` | `true` | Notification | Plays a short sound on new agent messages. |
| `desktop_notifications` | `true` | Notification | Requests Notification permission and shows desktop preview when tab hidden. |
| `mobile_message_preview` | `true` | Notification | Reserved for future mobile SDK integration; currently no browser-side change. |
| `agent_typing_indicator` | `true` | Notification | Shows three-dot typing indicator while waiting for first token. |
| `visitor_typing_indicator` | `true` | Notification | Sends visitor typing heartbeat (throttled; backend endpoint is future-ready). |
| `browser_tab_notifications` | `true` | Notification | Flashes tab title `(N) New message` when widget closed and tab hidden. |
| `hide_when_offline` | `false` | Visibility | Hides the bubble entirely when `offline_if_no_agents` is true. |
| `hide_on_desktop` | `false` | Visibility | Hides the bubble on non-touch/desktop viewports. |
| `hide_on_mobile` | `false` | Visibility | Hides the bubble on mobile/touch viewports. |
| `offline_if_no_agents` | `false` | Visibility | Sets status to "Offline" and, combined with `hide_when_offline`, hides the widget. |
| `emoji_picker_enabled` | `true` | Feature | Shows/hides the emoji button in the composer. |
| `file_upload_enabled` | `true` | Feature | Shows/hides the attachment button (upload backend is future-ready). |
| `chat_rating_enabled` | `true` | Feature | Shows thumbs up/down rating after a reply. |
| `email_transcript_enabled` | `true` | Feature | Reserved for future transcript/email feature. |

## Migration & Rollback

### Migration
1. Apply `backend/db/migrations/0007_widget_settings.sql` to the target database.
2. No code changes are required for existing widgets — defaults keep behavior identical.
3. Existing admin users will see the new "Widget Settings" page after the admin build is redeployed.

### Rollback
1. Revert the widget.js file to the previous version if needed.
2. Drop the table if necessary:
   ```sql
   DROP TABLE IF EXISTS widget_settings;
   ```
3. The public endpoint simply won't exist on an older code version; widgets will use defaults.

## Security Considerations
- The public endpoint is gated by the same origin/site validation as `/chat`.
- Only boolean fields from a known allow-list are writable by admins.
- No secrets, tokens, or internal model configuration are exposed publicly.

## Verification
- Backend tests: `uv run pytest tests -v` → **49 passed, 3 skipped**.
- Admin lint: `npm run lint` → **0 errors**.
- Manual smoke test: load a page with the widget, change a setting in the admin dashboard, reload the page, and confirm the change applies (e.g., disable emoji picker and verify the button disappears).

## Future Enhancements
- Implement the `/public/typing` endpoint and wire it to a human-agent dashboard.
- Add actual file upload handling and secure storage (e.g., R2 with signed URLs).
- Add email transcript endpoint and UI.
- Add human-agent availability heartbeat so `offline_if_no_agents` reflects real-time staffing.
