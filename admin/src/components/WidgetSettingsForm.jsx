import { useEffect, useState, startTransition } from "react";
import { api } from "../services/api";
import {
  Palette,
  Eye,
  UserCheck,
  Code,
  Copy,
  CheckCircle,
  AlertCircle
} from "lucide-react";

function Toggle({ checked, onChange, label, description }) {
  return (
    <label className="flex items-start justify-between p-4 bg-[#0E131F]/40 border border-[#1F2937] rounded-lg cursor-pointer hover:border-[#2D3748] transition-colors">
      <div className="pr-4">
        <div className="text-sm font-semibold text-gray-200">{label}</div>
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

const EMBED_SCRIPT = `<script\n  src="https://widget.degreebaba.com/widget.js"\n  defer>\n</script>`;

export default function WidgetSettingsForm() {
  const [settings, setSettings] = useState({
    // Branding
    primary_color: "#135d66",
    widget_title: "DegreeBaba Assistant",
    bot_name: "DegreeBaba Assistant",
    welcome_message: "Hello! Ask me about colleges, courses, admissions and fees.",
    logo_url: "",

    // Behavior
    show_on_mobile: true,
    show_on_desktop: true,

    // Lead capture
    lead_capture_enabled: true,
    capture_name: true,
    capture_email: true,
    capture_phone: true,
    lead_trigger: "during_chat",
    lead_form_title: "Request callback",
    lead_form_description: "A counsellor can follow up with you."
  });

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [copySuccess, setCopySuccess] = useState(false);

  useEffect(() => {
    let cancelled = false;
    startTransition(() => {
      setLoading(true);
      setError("");
    });
    api
      .getWidgetSettings("default")
      .then((data) => {
        if (cancelled) return;
        setSettings((prev) => ({ ...prev, ...data }));
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message || "Failed to load widget settings.");
      })
      .finally(() => setLoading(false));
    return () => { cancelled = true; };
  }, []);

  const handleChange = (key, value) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      await api.updateWidgetSettings("default", settings);
      setSuccess("Widget settings saved successfully. Changes take effect immediately.");
    } catch (err) {
      setError(err.message || "Failed to save widget settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(EMBED_SCRIPT);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  if (loading) {
    return <div className="text-xs text-gray-500 animate-pulse">Loading settings...</div>;
  }

  return (
    <form onSubmit={handleSave} className="space-y-8">
      {error && (
        <div className="p-4 bg-red-955/20 border border-red-900/50 rounded-xl flex items-center space-x-3 text-xs text-red-400">
          <AlertCircle size={16} className="text-red-500 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="p-4 bg-emerald-950/20 border border-emerald-900/50 rounded-xl flex items-center space-x-3 text-xs text-emerald-400">
          <CheckCircle size={16} className="text-emerald-500 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* SECTION 1: Branding */}
      <div className="bg-[#0E131F]/20 border border-[#1F2937] rounded-xl p-5 md:p-6 space-y-4">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2 border-b border-[#1F2937] pb-3">
          <Palette size={16} className="text-blue-500" />
          Branding
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Primary Color</label>
            <div className="flex gap-2">
              <input
                type="color"
                value={settings.primary_color}
                onChange={(e) => handleChange("primary_color", e.target.value)}
                className="h-8 w-8 rounded bg-transparent border-0 cursor-pointer outline-none shrink-0"
              />
              <input
                type="text"
                value={settings.primary_color}
                onChange={(e) => handleChange("primary_color", e.target.value)}
                className="flex-1 px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Widget Title</label>
            <input
              type="text"
              value={settings.widget_title}
              onChange={(e) => handleChange("widget_title", e.target.value)}
              className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Bot Name</label>
            <input
              type="text"
              value={settings.bot_name}
              onChange={(e) => handleChange("bot_name", e.target.value)}
              className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Welcome Message</label>
            <input
              type="text"
              value={settings.welcome_message}
              onChange={(e) => handleChange("welcome_message", e.target.value)}
              className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div className="space-y-1.5 md:col-span-2">
            <label className="text-[10px] font-bold text-gray-400 uppercase">Logo Image URL</label>
            <input
              type="text"
              value={settings.logo_url || ""}
              onChange={(e) => handleChange("logo_url", e.target.value)}
              placeholder="https://example.com/logo.png"
              className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      {/* SECTION 2: Widget Behavior */}
      <div className="bg-[#0E131F]/20 border border-[#1F2937] rounded-xl p-5 md:p-6 space-y-4">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2 border-b border-[#1F2937] pb-3">
          <Eye size={16} className="text-purple-500" />
          Widget Behavior
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Toggle
            label="Show on Desktop"
            checked={settings.show_on_desktop}
            onChange={(val) => handleChange("show_on_desktop", val)}
          />
          <Toggle
            label="Show on Mobile"
            checked={settings.show_on_mobile}
            onChange={(val) => handleChange("show_on_mobile", val)}
          />
        </div>
      </div>

      {/* SECTION 3: Lead Capture */}
      <div className="bg-[#0E131F]/20 border border-[#1F2937] rounded-xl p-5 md:p-6 space-y-4">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2 border-b border-[#1F2937] pb-3">
          <UserCheck size={16} className="text-emerald-500" />
          Lead Capture
        </h3>
        
        <div className="space-y-4">
          <Toggle
            label="Enable Lead Collection"
            description="If active, shows a contact callback request form in the chat widget"
            checked={settings.lead_capture_enabled}
            onChange={(val) => handleChange("lead_capture_enabled", val)}
          />

          {settings.lead_capture_enabled && (
            <div className="p-5 bg-[#0E131F]/50 border border-[#1F2937] rounded-lg grid grid-cols-1 md:grid-cols-2 gap-4 animate-fadeIn">
              <div className="space-y-1.5 md:col-span-2">
                <label className="text-[10px] font-bold text-gray-400 uppercase">Fields to Collect</label>
                <div className="grid grid-cols-3 gap-2">
                  <label className="flex items-center gap-1.5 p-2 bg-[#1F2937] rounded-lg border border-[#2D3748] cursor-pointer text-xs">
                    <input
                      type="checkbox"
                      checked={settings.capture_name}
                      onChange={(e) => handleChange("capture_name", e.target.checked)}
                      className="rounded border-gray-700 bg-gray-800 text-blue-500"
                    />
                    <span>Name</span>
                  </label>
                  <label className="flex items-center gap-1.5 p-2 bg-[#1F2937] rounded-lg border border-[#2D3748] cursor-pointer text-xs">
                    <input
                      type="checkbox"
                      checked={settings.capture_phone}
                      onChange={(e) => handleChange("capture_phone", e.target.checked)}
                      className="rounded border-gray-700 bg-gray-800 text-blue-500"
                    />
                    <span>Phone</span>
                  </label>
                  <label className="flex items-center gap-1.5 p-2 bg-[#1F2937] rounded-lg border border-[#2D3748] cursor-pointer text-xs">
                    <input
                      type="checkbox"
                      checked={settings.capture_email}
                      onChange={(e) => handleChange("capture_email", e.target.checked)}
                      className="rounded border-gray-700 bg-gray-800 text-blue-500"
                    />
                    <span>Email</span>
                  </label>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-gray-400 uppercase">Lead Form Title</label>
                <input
                  type="text"
                  value={settings.lead_form_title}
                  onChange={(e) => handleChange("lead_form_title", e.target.value)}
                  className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[10px] font-bold text-gray-400 uppercase">Lead Trigger Strategy</label>
                <select
                  value={settings.lead_trigger}
                  onChange={(e) => handleChange("lead_trigger", e.target.value)}
                  className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                >
                  <option value="before_chat">Before Chat (First Action)</option>
                  <option value="during_chat">During Chat (On Request / Intent)</option>
                  <option value="after_qualification">After Qualification (AI Discretion)</option>
                </select>
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <label className="text-[10px] font-bold text-gray-400 uppercase">Lead Form Description</label>
                <input
                  type="text"
                  value={settings.lead_form_description}
                  onChange={(e) => handleChange("lead_form_description", e.target.value)}
                  className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* SECTION 4: Installation */}
      <div className="bg-[#0E131F]/20 border border-[#1F2937] rounded-xl p-5 md:p-6 space-y-4">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2 border-b border-[#1F2937] pb-3">
          <Code size={16} className="text-amber-500" />
          Installation
        </h3>
        
        <div className="space-y-4 text-xs text-gray-400">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-[#0E131F]/40 p-4 rounded-lg border border-[#1F2937]">
            <div>
              <span className="text-[10px] uppercase font-bold text-gray-500">Widget Status</span>
              <div className="text-emerald-400 font-semibold mt-0.5">Active</div>
            </div>
            <div>
              <span className="text-[10px] uppercase font-bold text-gray-500">Widget Version</span>
              <div className="text-gray-200 font-mono mt-0.5">v1.0.0</div>
            </div>
          </div>

          <div className="space-y-2">
            <span className="text-[10px] uppercase font-bold text-gray-500">Embed Script</span>
            <div className="relative">
              <pre className="bg-[#0E131F] border border-[#1F2937] p-4 rounded-lg overflow-x-auto text-[11px] text-gray-300 font-mono">
                {EMBED_SCRIPT}
              </pre>
              <button
                type="button"
                onClick={handleCopy}
                className="absolute top-2.5 right-2.5 p-1.5 bg-[#1F2937] hover:bg-gray-800 border border-[#2D3748] text-gray-300 rounded-lg transition-colors flex items-center gap-1.5 text-[10px] font-semibold"
              >
                {copySuccess ? (
                  <span className="text-emerald-400">Copied!</span>
                ) : (
                  <>
                    <Copy size={12} />
                    <span>Copy Script</span>
                  </>
                )}
              </button>
            </div>
          </div>

          <div className="space-y-2">
            <span className="text-[10px] uppercase font-bold text-gray-500">WordPress Installation</span>
            <ol className="list-decimal pl-5 space-y-1 text-gray-500 leading-relaxed">
              <li>Open your WordPress Admin Dashboard.</li>
              <li>Install and activate the <em>Insert Headers and Footers</em> plugin.</li>
              <li>Paste the script into the Footer section and save.</li>
              <li>Done — branding and lead settings update automatically from this dashboard.</li>
            </ol>
          </div>
        </div>
      </div>

      <div className="border-t border-[#1F2937] pt-6 flex justify-end">
        <button
          type="submit"
          disabled={saving}
          className="px-6 py-3 bg-[#3B82F6] hover:bg-blue-600 disabled:opacity-60 text-white rounded-lg text-xs font-semibold tracking-wider transition-all shadow-md"
        >
          {saving ? "Saving Changes..." : "Save Widget Configuration"}
        </button>
      </div>
    </form>
  );
}
