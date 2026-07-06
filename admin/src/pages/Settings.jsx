import { useEffect, useState } from "react";
import {
  Activity,
  Server,
  User,
  Shield,
  AlertCircle,
  HelpCircle,
  Mail
} from "lucide-react";
import { api } from "../services/api";
import WidgetSettingsForm from "../components/WidgetSettingsForm";

export default function Settings() {
  const [systemStatus, setSystemStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [statusError, setStatusError] = useState("");

  // Load system status
  useEffect(() => {
    let cancelled = false;
    async function fetchStatus() {
      try {
        const data = await api.getSystemStatus();
        if (!cancelled) {
          setSystemStatus(data);
        }
      } catch (err) {
        if (!cancelled) {
          setStatusError(err.message || "Failed to load system status.");
        }
      } finally {
        if (!cancelled) {
          setLoadingStatus(false);
        }
      }
    }
    fetchStatus();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="w-full space-y-8 text-left max-w-full">
      {/* Page Title & Intro */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-gray-100 tracking-tight flex items-center gap-2">
            System & Widget Configuration
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Real-time status monitoring and dynamic widget behavior settings.
          </p>
        </div>
      </div>

      {/* Sticky System Status Section */}
      <div className="sticky -mt-4 md:-mt-8 top-0 pt-4 md:pt-8 bg-[#0B1020]/90 backdrop-blur-md z-30 pb-4 border-b border-[#1F2937]/60">
        <div className="bg-[#111827]/40 border border-[#1F2937]/50 rounded-xl p-4 md:p-5 shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
              <Activity size={12} className="text-blue-500 animate-pulse" />
              Live Gateway Status
            </span>
            <span className="text-[9px] px-2 py-0.5 bg-[#1F2937] border border-[#2D3748] rounded text-gray-400 font-mono">
              Auto-Monitoring
            </span>
          </div>

          {loadingStatus ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[1, 2].map((i) => (
                <div key={i} className="h-16 bg-[#1F2937]/30 border border-[#1F2937]/50 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : statusError ? (
            <div className="p-3.5 bg-red-955/20 border border-red-900/30 rounded-lg flex items-center space-x-2.5 text-xs text-red-400">
              <AlertCircle size={14} className="text-red-500 shrink-0" />
              <span>{statusError}</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Card 1: AI Provider Status */}
              <div className="flex items-center justify-between p-3.5 bg-[#0E131F]/60 border border-[#1F2937]/60 rounded-lg transition-all hover:border-[#2D3748]/80">
                <div className="flex items-center space-x-3 min-w-0">
                  <div className="h-8 w-8 rounded-lg bg-blue-500/10 border border-blue-500/25 flex items-center justify-center text-blue-400 shrink-0">
                    <Shield size={16} />
                  </div>
                  <div className="min-w-0">
                    <span className="text-[9px] font-bold text-gray-500 uppercase tracking-wider block">AI Gateway</span>
                    <span className="text-xs font-bold text-gray-200 block truncate">
                      {systemStatus.ai_provider.provider}
                    </span>
                    <span className="text-[10px] text-gray-500 font-mono block truncate">
                      {systemStatus.ai_provider.model}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0 pl-2">
                  <span className={`h-2 w-2 rounded-full ${systemStatus.ai_provider.status === "Connected" ? "bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" : "bg-gray-500"}`}></span>
                  <span className="text-[10px] text-gray-300 font-bold uppercase tracking-wider">
                    {systemStatus.ai_provider.status === "Connected" ? "Live" : "Offline"}
                  </span>
                </div>
              </div>

              {/* Card 2: Lead Routing Status */}
              <div className="flex items-center justify-between p-3.5 bg-[#0E131F]/60 border border-[#1F2937]/60 rounded-lg transition-all hover:border-[#2D3748]/80">
                <div className="flex items-center space-x-3 min-w-0">
                  <div className="h-8 w-8 rounded-lg bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-center text-emerald-400 shrink-0">
                    <Mail size={16} />
                  </div>
                  <div className="min-w-0">
                    <span className="text-[9px] font-bold text-gray-500 uppercase tracking-wider block">Lead Delivery</span>
                    <span className="text-xs font-bold text-gray-200 block">
                      {systemStatus.lead_delivery.enabled ? "Enabled" : "Disabled"}
                    </span>
                    <span className="text-[10px] text-gray-500 block truncate">
                      Method: {systemStatus.lead_delivery.delivery_method}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0 pl-2">
                  <span className={`h-2 w-2 rounded-full ${systemStatus.lead_delivery.enabled ? "bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" : "bg-gray-500"}`}></span>
                  <span className="text-[10px] text-gray-300 font-bold uppercase tracking-wider">
                    {systemStatus.lead_delivery.enabled ? "Active" : "Inactive"}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Widget Customization Content */}
      <div className="w-full">
        <WidgetSettingsForm />
      </div>
    </div>
  );
}
