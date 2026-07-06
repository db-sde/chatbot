import { useEffect, useState, startTransition } from "react";
import {
  Activity,
  Sliders,
  CheckCircle,
  AlertCircle,
  Server,
  User,
  Shield,
  Palette,
  MessageSquareCode
} from "lucide-react";
import { Badge } from "../components/Common";
import { api } from "../services/api";
import WidgetSettingsForm from "../components/WidgetSettingsForm";

export default function Settings() {
  const [activeTab, setActiveTab] = useState("status");
  const [systemStatus, setSystemStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState("");
  
  // Widget Customization state
  const [sites, setSites] = useState([]);
  const [selectedSite, setSelectedSite] = useState("");
  const [loadingSites, setLoadingSites] = useState(true);
  const [widgetError, setWidgetError] = useState("");
  const [widgetSuccess, setWidgetSuccess] = useState("");

  // Mock theme/branding fields preserved as requested
  const [primaryColor, setPrimaryColor] = useState("#3B82F6");
  const [welcomeMessage, setWelcomeMessage] = useState("Hello! Ask me about colleges or courses.");
  const [mockSaved, setMockSaved] = useState(false);

  // Load system status
  useEffect(() => {
    async function fetchStatus() {
      try {
        const data = await api.getSystemStatus();
        setSystemStatus(data);
      } catch (err) {
        setStatusError(err.message || "Failed to load system status.");
      } finally {
        setLoadingStatus(false);
      }
    }
    fetchStatus();
  }, []);

  // Load sites for widget settings
  useEffect(() => {
    if (activeTab !== "widget") return;
    async function loadSites() {
      try {
        const [widgetRows, config] = await Promise.all([
          api.listWidgetSettings(),
          fetch("/api/admin/settings/site-domains", {
            headers: { Authorization: `Bearer ${api.getToken()}` }
          }).then((r) => r.json()).catch(() => ({})),
        ]);

        const configuredSites = Object.keys(config.site_domains || {});
        const existingSites = widgetRows.map((row) => row.site_id);
        const allSites = Array.from(new Set([...configuredSites, ...existingSites])).sort();
        setSites(allSites);
        if (allSites.length > 0 && !selectedSite) {
          setSelectedSite(allSites[0]);
        }
      } catch (err) {
        setWidgetError(err.message || "Failed to load site domains.");
      } finally {
        setLoadingSites(false);
      }
    }
    loadSites();
  }, [activeTab, selectedSite]);

  const handleWidgetSaved = () => {
    setWidgetSuccess("Widget settings saved and active for new sessions.");
    setTimeout(() => setWidgetSuccess(""), 4000);
  };

  const handleSaveMockSettings = (e) => {
    e.preventDefault();
    setMockSaved(true);
    setTimeout(() => setMockSaved(false), 3000);
  };

  const tabs = [
    { id: "status", name: "System Status", icon: Activity },
    { id: "widget", name: "Widget Customization", icon: Sliders },
  ];

  return (
    <div className="space-y-6 text-left max-w-5xl">
      <div>
        <h2 className="text-base font-bold text-gray-200">System Settings</h2>
        <p className="text-xs text-gray-500 mt-0.5">Monitor system configuration health and customize conversational widget behaviors.</p>
      </div>

      <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden flex flex-col md:flex-row shadow-sm">
        {/* Sidebar Tabs */}
        <div className="w-full md:w-60 bg-[#0E131F]/30 border-b md:border-b-0 md:border-r border-[#1F2937] p-4 flex md:flex-col gap-1 shrink-0 overflow-x-auto md:overflow-x-visible">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                flex items-center space-x-2.5 px-4 py-2.5 rounded-lg text-xs font-semibold tracking-wider text-left transition-all shrink-0 w-auto md:w-full
                ${activeTab === tab.id
                  ? "bg-[#3B82F6] text-white"
                  : "text-gray-400 hover:bg-[#1F2937] hover:text-white"
                }
              `}
            >
              <tab.icon size={14} />
              <span>{tab.name}</span>
            </button>
          ))}
        </div>

        {/* Content Area */}
        <div className="flex-1 p-6 md:p-8 space-y-6">
          
          {/* SYSTEM STATUS TAB */}
          {activeTab === "status" && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-200 mb-1 flex items-center gap-2">
                  <Server size={16} className="text-blue-500" />
                  Live System Status
                </h3>
                <p className="text-xs text-gray-500">Read-only overview of the active environment deployment configuration.</p>
              </div>

              {loadingStatus ? (
                <div className="text-xs text-gray-500 animate-pulse">Querying core services...</div>
              ) : statusError ? (
                <div className="p-4 bg-red-950/20 border border-red-900/50 rounded-xl flex items-center space-x-3 text-xs text-red-400">
                  <AlertCircle size={16} className="text-red-500 shrink-0" />
                  <span>{statusError}</span>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {/* AI Provider */}
                  <div className="p-5 bg-[#0E131F]/40 border border-[#1F2937] rounded-xl space-y-3 relative overflow-hidden">
                    <div className="absolute top-4 right-4 text-gray-700">
                      <Shield size={28} opacity={0.1} />
                    </div>
                    <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">AI Provider</span>
                    <div>
                      <div className="text-sm font-bold text-gray-200">{systemStatus.ai_provider.provider}</div>
                      <div className="text-[11px] text-gray-500 font-mono mt-0.5">{systemStatus.ai_provider.model}</div>
                    </div>
                    <div className="pt-2 border-t border-[#1F2937]/50 flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full ${systemStatus.ai_provider.status === "Connected" ? "bg-emerald-500 animate-pulse" : "bg-gray-500"}`}></span>
                      <span className="text-xs text-gray-400 font-semibold">{systemStatus.ai_provider.status}</span>
                    </div>
                  </div>

                  {/* Lead Delivery */}
                  <div className="p-5 bg-[#0E131F]/40 border border-[#1F2937] rounded-xl space-y-3 relative overflow-hidden">
                    <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Lead Delivery</span>
                    <div>
                      <div className="text-sm font-bold text-gray-200">
                        {systemStatus.lead_delivery.enabled ? "Enabled" : "Disabled"}
                      </div>
                      <div className="text-[11px] text-gray-500 mt-0.5">Method: {systemStatus.lead_delivery.delivery_method}</div>
                    </div>
                    <div className="pt-2 border-t border-[#1F2937]/50 flex items-center gap-1.5">
                      <span className="text-xs text-gray-400 font-semibold">
                        Delivery Status: <span className={systemStatus.lead_delivery.enabled ? "text-emerald-400 font-bold" : "text-gray-500"}>{systemStatus.lead_delivery.last_delivery_status}</span>
                      </span>
                    </div>
                  </div>

                  {/* Current Authorized Session */}
                  <div className="p-5 bg-[#0E131F]/40 border border-[#1F2937] rounded-xl space-y-3 relative overflow-hidden">
                    <div className="absolute top-4 right-4 text-gray-700">
                      <User size={28} opacity={0.1} />
                    </div>
                    <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider block">Active Session</span>
                    <div>
                      <div className="text-sm font-bold text-gray-200">{systemStatus.current_user.username}</div>
                      <div className="text-[11px] text-gray-500 mt-0.5">{systemStatus.current_user.role}</div>
                    </div>
                    <div className="pt-2 border-t border-[#1F2937]/50 flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                      <span className="text-xs text-gray-400 font-semibold">Authorized</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* WIDGET CUSTOMIZATION TAB */}
          {activeTab === "widget" && (
            <div className="space-y-6">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#1F2937]/50 pb-4">
                <div>
                  <h3 className="text-sm font-semibold text-gray-200 mb-1 flex items-center gap-2">
                    <Sliders size={16} className="text-purple-500" />
                    Widget Customization
                  </h3>
                  <p className="text-xs text-gray-500">Modify behavioral features, visibilities, and themes for your chat widgets.</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-gray-400 uppercase tracking-wider">Select Site ID:</span>
                  <select
                    value={selectedSite}
                    onChange={(e) => setSelectedSite(e.target.value)}
                    className="px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500 font-semibold"
                  >
                    <option value="">{loadingSites ? "Loading sites..." : "Select a site"}</option>
                    {sites.map((site) => (
                      <option key={site} value={site}>{site}</option>
                    ))}
                  </select>
                </div>
              </div>

              {widgetSuccess && (
                <div className="p-4 bg-emerald-950/20 border border-emerald-900/50 rounded-xl flex items-center space-x-3 text-xs text-emerald-400 animate-fadeIn">
                  <CheckCircle size={16} className="text-emerald-500 shrink-0" />
                  <span>{widgetSuccess}</span>
                </div>
              )}

              {widgetError && (
                <div className="p-4 bg-red-950/20 border border-red-900/50 rounded-xl text-xs text-red-400 animate-fadeIn">
                  {widgetError}
                </div>
              )}

              {/* Theme & Branding Visual Customization (Preserved Mock Fields) */}
              <div className="bg-[#0E131F]/20 border border-[#1F2937] rounded-xl p-5 space-y-4">
                <div>
                  <h4 className="text-xs font-bold text-gray-300 flex items-center gap-1.5 uppercase tracking-wider">
                    <Palette size={14} className="text-blue-400" />
                    Visual Styling & Branding
                  </h4>
                  <p className="text-[11px] text-gray-500">Configure visual themes, brand colors, and greeting placeholders.</p>
                </div>

                <form onSubmit={handleSaveMockSettings} className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Theme Primary Color</label>
                    <div className="flex gap-2">
                      <input
                        type="color"
                        value={primaryColor}
                        onChange={(e) => setPrimaryColor(e.target.value)}
                        className="h-8 w-8 rounded bg-transparent border-0 cursor-pointer outline-none"
                      />
                      <input
                        type="text"
                        value={primaryColor}
                        onChange={(e) => setPrimaryColor(e.target.value)}
                        className="flex-1 px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Welcome Greeting Message</label>
                    <input
                      type="text"
                      value={welcomeMessage}
                      onChange={(e) => setWelcomeMessage(e.target.value)}
                      className="w-full px-3 py-1.5 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  
                  <div className="md:col-span-2 flex items-center justify-between pt-2">
                    <div className="text-[11px] text-gray-500 flex items-center gap-1">
                      <MessageSquareCode size={12} className="text-gray-400" />
                      Visual style values apply globally to site widgets.
                    </div>
                    <button
                      type="submit"
                      className="px-4 py-1.5 bg-[#1F2937] hover:bg-gray-800 border border-[#2D3748] text-gray-300 hover:text-white rounded-lg text-[11px] font-semibold transition-all shadow-sm flex items-center gap-1.5"
                    >
                      {mockSaved ? (
                        <>
                          <CheckCircle size={12} className="text-emerald-400 animate-pulse" />
                          <span className="text-emerald-400">Styling Saved</span>
                        </>
                      ) : (
                        <span>Save Visual Styles</span>
                      )}
                    </button>
                  </div>
                </form>
              </div>

              {/* Behavior Settings Form */}
              <div className="pt-2">
                <WidgetSettingsForm siteId={selectedSite} onSaved={handleWidgetSaved} />
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
