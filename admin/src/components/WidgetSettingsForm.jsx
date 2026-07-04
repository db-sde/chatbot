import { useEffect, useState, startTransition } from "react";
import { api } from "../services/api";

const SETTING_KEYS = [
  { key: "show_estimated_wait_time", label: "Show Estimated Wait Time", section: "notification" },
  { key: "sound_notifications", label: "Sound Notifications", section: "notification" },
  { key: "desktop_notifications", label: "Desktop Message Preview", section: "notification" },
  { key: "mobile_message_preview", label: "Mobile Message Preview", section: "notification" },
  { key: "agent_typing_indicator", label: "Agent Typing Indicator", section: "notification" },
  { key: "visitor_typing_indicator", label: "Visitor Typing Indicator", section: "notification" },
  { key: "browser_tab_notifications", label: "Browser Tab Notifications", section: "notification" },

  { key: "hide_when_offline", label: "Hide Widget When Offline", section: "visibility" },
  { key: "hide_on_desktop", label: "Hide Widget On Desktop", section: "visibility" },
  { key: "hide_on_mobile", label: "Hide Widget On Mobile", section: "visibility" },
  { key: "offline_if_no_agents", label: "Widget Offline When No Agents Available", section: "visibility" },

  { key: "emoji_picker_enabled", label: "Emoji Picker", section: "feature" },
  { key: "file_upload_enabled", label: "File Upload", section: "feature" },
  { key: "chat_rating_enabled", label: "Chat Rating", section: "feature" },
  { key: "email_transcript_enabled", label: "Email Transcript", section: "feature" },
];

const DEFAULT_SETTINGS = {
  show_estimated_wait_time: true,
  sound_notifications: true,
  desktop_notifications: true,
  mobile_message_preview: true,
  agent_typing_indicator: true,
  visitor_typing_indicator: true,
  browser_tab_notifications: true,
  hide_when_offline: false,
  hide_on_desktop: false,
  hide_on_mobile: false,
  offline_if_no_agents: false,
  emoji_picker_enabled: true,
  file_upload_enabled: true,
  chat_rating_enabled: true,
  email_transcript_enabled: true,
};

function Toggle({ checked, onChange, label, description }) {
  return (
    <label className="flex items-start justify-between p-4 bg-[#0E131F]/40 border border-[#1F2937] rounded-lg cursor-pointer hover:border-[#2D3748] transition-colors">
      <div className="pr-4">
        <div className="text-sm font-medium text-gray-200">{label}</div>
        {description && <div className="text-xs text-gray-500 mt-0.5">{description}</div>}
      </div>
      <div className="relative inline-flex h-5 w-9 items-center rounded-full bg-[#1F2937] transition-colors shrink-0" style={{ backgroundColor: checked ? "#3B82F6" : "#1F2937" }}>
        <input
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span
          className="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform"
          style={{ transform: checked ? "translateX(18px)" : "translateX(2px)" }}
        />
      </div>
    </label>
  );
}

export default function WidgetSettingsForm({ siteId, onSaved }) {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    if (!siteId) return;
    let cancelled = false;
    startTransition(() => {
      setLoading(true);
      setError("");
    });
    api
      .getWidgetSettings(siteId)
      .then((data) => {
        if (cancelled) return;
        setSettings({ ...DEFAULT_SETTINGS, ...data });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || "Failed to load widget settings.");
      })
      .finally(() => setLoading(false));
    return () => { cancelled = true; };
  }, [siteId]);

  const handleToggle = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    if (!siteId) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const payload = {};
      SETTING_KEYS.forEach(({ key }) => { payload[key] = settings[key]; });
      await api.updateWidgetSettings(siteId, payload);
      setSuccess("Widget settings saved. Changes apply immediately.");
      if (onSaved) onSaved();
    } catch (err) {
      setError(err.message || "Failed to save widget settings.");
    } finally {
      setSaving(false);
    }
  };

  const notificationItems = SETTING_KEYS.filter((s) => s.section === "notification");
  const visibilityItems = SETTING_KEYS.filter((s) => s.section === "visibility");
  const featureItems = SETTING_KEYS.filter((s) => s.section === "feature");

  if (!siteId) {
    return (
      <div className="p-6 bg-[#0E131F]/40 border border-[#1F2937] rounded-lg text-sm text-gray-500">
        Select a site to configure its widget settings.
      </div>
    );
  }

  return (
    <form onSubmit={handleSave} className="space-y-6">
      {error && (
        <div className="p-3 bg-red-950/20 border border-red-900/50 rounded-lg text-xs text-red-400">
          {error}
        </div>
      )}
      {success && (
        <div className="p-3 bg-emerald-950/20 border border-emerald-900/50 rounded-lg text-xs text-emerald-400">
          {success}
        </div>
      )}

      {loading ? (
        <div className="text-xs text-gray-500">Loading settings...</div>
      ) : (
        <>
          <div>
            <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-blue-500"></span>
              Notification Settings
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {notificationItems.map(({ key, label }) => (
                <Toggle
                  key={key}
                  label={label}
                  checked={!!settings[key]}
                  onChange={(v) => handleToggle(key, v)}
                />
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-purple-500"></span>
              Visibility Settings
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {visibilityItems.map(({ key, label }) => (
                <Toggle
                  key={key}
                  label={label}
                  checked={!!settings[key]}
                  onChange={(v) => handleToggle(key, v)}
                />
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
              Feature Settings
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {featureItems.map(({ key, label }) => (
                <Toggle
                  key={key}
                  label={label}
                  checked={!!settings[key]}
                  onChange={(v) => handleToggle(key, v)}
                />
              ))}
            </div>
          </div>

          <div className="border-t border-[#1F2937] pt-6 flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2.5 bg-[#3B82F6] hover:bg-blue-600 disabled:opacity-60 text-white rounded-lg text-xs font-semibold tracking-wider transition-all shadow-md"
            >
              {saving ? "Saving..." : "Save Widget Settings"}
            </button>
          </div>
        </>
      )}
    </form>
  );
}
