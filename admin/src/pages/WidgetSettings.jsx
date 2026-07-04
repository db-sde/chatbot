import { useEffect, useState } from "react";
import { Globe, LayoutTemplate, CheckCircle } from "lucide-react";
import { api } from "../services/api";
import WidgetSettingsForm from "../components/WidgetSettingsForm";

export default function WidgetSettingsPage() {
  const [sites, setSites] = useState([]);
  const [selectedSite, setSelectedSite] = useState("");
  const [loadingSites, setLoadingSites] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    async function load() {
      try {
        // Derive sites from existing widget settings rows + settings config.
        const [widgetRows, config] = await Promise.all([
          api.listWidgetSettings(),
          fetch("/api/admin/settings/site-domains", { headers: { Authorization: `Bearer ${api.getToken()}` } }).then((r) => r.json()).catch(() => ({})),
        ]);

        const configuredSites = Object.keys(config.site_domains || {});
        const existingSites = widgetRows.map((row) => row.site_id);
        const allSites = Array.from(new Set([...configuredSites, ...existingSites])).sort();
        setSites(allSites);
        if (allSites.length > 0 && !selectedSite) {
          setSelectedSite(allSites[0]);
        }
      } catch (err) {
        setError(err.message || "Failed to load sites.");
      } finally {
        setLoadingSites(false);
      }
    }
    load();
  }, [selectedSite]);

  const handleSaved = () => {
    setSuccess("Widget settings saved and active for new sessions.");
    setTimeout(() => setSuccess(""), 4000);
  };

  return (
    <div className="space-y-6 text-left max-w-5xl">
      <div>
        <h2 className="text-base font-bold text-gray-200 flex items-center gap-2">
          <LayoutTemplate size={18} className="text-blue-500" />
          Widget Settings
        </h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Control widget behavior per site. Changes take effect immediately for all websites using the widget.
        </p>
      </div>

      {success && (
        <div className="p-4 bg-emerald-950/20 border border-emerald-900/50 rounded-xl flex items-center space-x-3 text-xs text-emerald-400">
          <CheckCircle size={16} className="text-emerald-500 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-950/20 border border-red-900/50 rounded-xl text-xs text-red-400">
          {error}
        </div>
      )}

      <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-[#1F2937] bg-[#0E131F]/30 flex flex-col md:flex-row md:items-center gap-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-gray-200">
            <Globe size={16} className="text-gray-400" />
            Select Site
          </div>
          <select
            value={selectedSite}
            onChange={(e) => setSelectedSite(e.target.value)}
            className="md:w-72 px-3 py-2 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
          >
            <option value="">{loadingSites ? "Loading sites..." : "Select a site"}</option>
            {sites.map((site) => (
              <option key={site} value={site}>{site}</option>
            ))}
          </select>
        </div>

        <div className="p-6">
          <WidgetSettingsForm siteId={selectedSite} onSaved={handleSaved} />
        </div>
      </div>
    </div>
  );
}
