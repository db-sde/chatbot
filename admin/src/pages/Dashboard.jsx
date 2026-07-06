import { useEffect, useState } from "react";
import {
  Users,
  AlertOctagon,
  HelpCircle,
  TrendingUp,
  School,
  Activity,
  Clock,
  DollarSign,
  BarChart3,
  RefreshCw,
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { LoadingState, ErrorState } from "../components/Common";

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [security, setSecurity] = useState(null);
  const [overview, setOverview] = useState(null);
  const [systemStatus, setSystemStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        const [analyticsData, securityData, overviewData, statusData] = await Promise.all([
          api.getAnalytics(),
          api.getSecuritySummary(),
          api.getAnalyticsOverview(),
          api.getSystemStatus(),
        ]);
        if (cancelled) return;
        setData(analyticsData);
        setSecurity(securityData);
        setOverview(overviewData);
        setSystemStatus(statusData);
      } catch (err) {
        if (cancelled) return;
        setError(err.message || "Failed to load dashboard metrics.");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    run();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  if (loading) return <LoadingState message="Connecting to analytics pipeline..." />;
  if (error) return <ErrorState title="Dashboard connection failed" description={error} retry={() => setRefresh((r) => r + 1)} />;

  // Computed metrics
  const totalSessions = data?.conversation_count || 0;
  const totalMessages = data?.message_count || 0;
  const totalLeads = data?.lead_count || 0;
  const totalBlocks = security?.total_events || security?.total_blocks || 0;
  const unansweredCount = data?.unanswered_count || 0;

  const leadConvRate = totalSessions > 0 ? ((totalLeads / totalSessions) * 100).toFixed(1) : "0.0";

  // Dynamic maximum calculation for perfect auto-scaling
  const maxVal = Math.max(totalSessions, totalMessages, totalLeads, totalBlocks, 1);
  const sessionPct = (totalSessions / maxVal) * 100;
  const messagePct = (totalMessages / maxVal) * 100;
  const leadPct = (totalLeads / maxVal) * 100;
  const blockPct = (totalBlocks / maxVal) * 100;

  // Top list mapping
  const topUniversities = data?.top_universities || [];

  return (
    <div className="space-y-12 text-left">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-100 tracking-tight">Performance Overview</h2>
          <p className="text-xs text-gray-500 mt-0.5 font-medium">Real-time business and system analytics</p>
        </div>
        <button
          onClick={() => setRefresh((r) => r + 1)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[#1F2937] text-xs text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-all self-start sm:self-center"
        >
          <RefreshCw size={12} />
          Refresh Metrics
        </button>
      </div>

      {/* SECTION 1 — BUSINESS METRICS */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">Business Metrics</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
          <StatsCard
            title="Total Conversations"
            value={totalSessions.toLocaleString()}
            subtext="Total unique user chats initialized"
            icon={Activity}
          />
          <StatsCard
            title="Total Leads"
            value={totalLeads.toLocaleString()}
            subtext="Captured forms matching query intent"
            icon={Users}
          />
          <StatsCard
            title="Lead Conversion Rate"
            value={`${leadConvRate}%`}
            subtext="Percentage of sessions turned into leads"
            icon={TrendingUp}
            trend={totalSessions > 0 ? "Active" : null}
            trendType={totalSessions > 0 ? "positive" : "neutral"}
          />
        </div>
      </div>

      {/* SECTION 2 — AI PERFORMANCE */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">AI Performance</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
          <StatsCard
            title="Average Response Time"
            value={`${((overview?.avg_response_time_ms || 0) / 1000).toFixed(2)}s`}
            subtext="E2E message generation latency"
            icon={Clock}
          />
          <StatsCard
            title="Average TTFT"
            value={`${(overview?.avg_ttft_ms || 0).toFixed(0)}ms`}
            subtext="First token/decision latency"
            icon={Activity}
          />
          {/* Current Model Card */}
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 transition-all hover:border-[#2D3748] shadow-sm flex flex-col justify-between min-h-[140px]">
            <div className="flex justify-between items-start">
              <h3 className="text-sm font-medium text-gray-400">Current Model</h3>
              <div className="p-2 bg-[#1F2937] rounded-lg text-gray-300 border border-[#2D3748]">
                <School size={18} />
              </div>
            </div>
            <div className="mt-4 space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 font-medium">Provider</span>
                <span className="text-gray-200 font-bold">{systemStatus?.ai_provider?.provider || "N/A"}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500 font-medium">Model</span>
                <span className="text-gray-200 font-mono text-[10px] truncate max-w-[170px]" title={systemStatus?.ai_provider?.model}>
                  {systemStatus?.ai_provider?.model || "N/A"}
                </span>
              </div>
              <div className="flex justify-between text-xs items-center">
                <span className="text-gray-500 font-medium">Status</span>
                <span className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${systemStatus?.ai_provider?.status === "Connected" ? "bg-emerald-500 animate-pulse" : "bg-red-500"}`}></span>
                  <span className="text-gray-200 font-bold">{systemStatus?.ai_provider?.status || "N/A"}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 3 — OPERATIONS */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">Operations</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
          <StatsCard
            title="Tokens Today"
            value={(overview?.total_tokens_today || 0).toLocaleString()}
            subtext="Prompt + completion tokens today"
            icon={BarChart3}
          />
          <StatsCard
            title="Cost Today"
            value={`$${(overview?.total_cost_today || 0).toFixed(4)}`}
            subtext="Estimated running model cost today"
            icon={DollarSign}
          />
          <StatsCard
            title="Cost Per Lead"
            value={`$${(overview?.cost_per_lead || 0).toFixed(4)}`}
            subtext="Model cost divided by leads count"
            icon={DollarSign}
          />
        </div>
      </div>

      {/* SECTION 4 — SYSTEM HEALTH */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-gray-500">System Health</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-8">
          <StatsCard
            title="Security Events"
            value={totalBlocks.toLocaleString()}
            subtext="Recorded threats and violations"
            icon={AlertOctagon}
          />
          <StatsCard
            title="Unanswered Questions"
            value={unansweredCount.toLocaleString()}
            subtext="Queries flagged for review"
            icon={HelpCircle}
          />
          {/* System Status Card */}
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 transition-all hover:border-[#2D3748] shadow-sm flex flex-col justify-between min-h-[140px]">
            <div className="flex justify-between items-start">
              <h3 className="text-sm font-medium text-gray-400">System Status</h3>
              <div className="p-2 bg-[#1F2937] rounded-lg text-gray-300 border border-[#2D3748]">
                <Activity size={18} />
              </div>
            </div>
            <div className="mt-4 space-y-1.5">
              <div className="flex justify-between text-xs items-center">
                <span className="text-gray-500 font-medium">API Gateway</span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                  <span className="text-gray-200 font-bold">{systemStatus?.api_gateway?.status || "Connected"}</span>
                </span>
              </div>
              <div className="flex justify-between text-xs items-center">
                <span className="text-gray-500 font-medium">Database</span>
                <span className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${systemStatus?.database?.status === "Connected" ? "bg-emerald-500" : "bg-red-500 animate-pulse"}`}></span>
                  <span className="text-gray-200 font-bold">{systemStatus?.database?.status || "N/A"}</span>
                </span>
              </div>
              <div className="flex justify-between text-xs items-center">
                <span className="text-gray-500 font-medium">LLM Provider</span>
                <span className="flex items-center gap-1">
                  <span className={`w-2 h-2 rounded-full ${systemStatus?.ai_provider?.status === "Connected" ? "bg-emerald-500" : "bg-red-500 animate-pulse"}`}></span>
                  <span className="text-gray-200 font-bold">{systemStatus?.ai_provider?.status || "N/A"}</span>
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Visual Trends & Insights */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 pt-4">
        {/* Simple SVG Chart / Trend */}
        <div className="lg:col-span-2 bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">Volume & Traffic Trend</h3>
            <p className="text-xs text-gray-500 mt-1">Relative distribution of sessions, leads, and messages.</p>
          </div>

          <div className="my-8 flex items-stretch h-56 gap-4">
            {/* Y-axis Labels */}
            <div className="flex flex-col justify-between text-[10px] text-gray-500 font-mono select-none h-48 py-1 pr-2 border-r border-[#1F2937]/50 text-right w-12">
              <span>{maxVal}</span>
              <span>{Math.round(maxVal * 0.75)}</span>
              <span>{Math.round(maxVal * 0.5)}</span>
              <span>{Math.round(maxVal * 0.25)}</span>
              <span>0</span>
            </div>

            {/* Chart Area */}
            <div className="flex-1 h-48 relative border-b border-[#1F2937] flex items-end justify-between px-6">
              {/* Horizontal Grid Lines */}
              <div className="absolute inset-0 pointer-events-none flex flex-col justify-between py-1">
                <div className="border-t border-[#1F2937]/20 w-full"></div>
                <div className="border-t border-[#1F2937]/20 w-full"></div>
                <div className="border-t border-[#1F2937]/20 w-full"></div>
                <div className="border-t border-[#1F2937]/20 w-full"></div>
                <div className="w-full"></div>
              </div>

              {/* Sessions Bar */}
              <div className="flex flex-col items-center justify-end h-full w-1/5 group z-10">
                <span className="text-[10px] font-bold text-blue-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                  {totalSessions}
                </span>
                <div
                  className="w-12 bg-gradient-to-t from-blue-600 to-blue-400 hover:from-blue-500 hover:to-blue-300 rounded-t-md transition-all duration-500 shadow-[0_0_12px_rgba(59,130,246,0.15)] hover:shadow-[0_0_16px_rgba(59,130,246,0.35)]"
                  style={{ height: `${sessionPct}%` }}
                ></div>
                <span className="text-[10px] text-gray-500 font-semibold mt-2.5">Sessions</span>
              </div>

              {/* Messages Bar */}
              <div className="flex flex-col items-center justify-end h-full w-1/5 group z-10">
                <span className="text-[10px] font-bold text-purple-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                  {totalMessages}
                </span>
                <div
                  className="w-12 bg-gradient-to-t from-purple-600 to-purple-400 hover:from-purple-500 hover:to-purple-300 rounded-t-md transition-all duration-500 shadow-[0_0_12px_rgba(168,85,247,0.15)] hover:shadow-[0_0_16px_rgba(168,85,247,0.35)]"
                  style={{ height: `${messagePct}%` }}
                ></div>
                <span className="text-[10px] text-gray-500 font-semibold mt-2.5">Messages</span>
              </div>

              {/* Leads Bar */}
              <div className="flex flex-col items-center justify-end h-full w-1/5 group z-10">
                <span className="text-[10px] font-bold text-emerald-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                  {totalLeads}
                </span>
                <div
                  className="w-12 bg-gradient-to-t from-emerald-600 to-emerald-400 hover:from-emerald-500 hover:to-emerald-300 rounded-t-md transition-all duration-500 shadow-[0_0_12px_rgba(16,185,129,0.15)] hover:shadow-[0_0_16px_rgba(16,185,129,0.35)]"
                  style={{ height: `${leadPct}%` }}
                ></div>
                <span className="text-[10px] text-gray-500 font-semibold mt-2.5">Leads</span>
              </div>

              {/* Blocks Bar */}
              <div className="flex flex-col items-center justify-end h-full w-1/5 group z-10">
                <span className="text-[10px] font-bold text-red-400 mb-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                  {totalBlocks}
                </span>
                <div
                  className="w-12 bg-gradient-to-t from-red-600 to-red-400 hover:from-red-500 hover:to-red-300 rounded-t-md transition-all duration-500 shadow-[0_0_12px_rgba(239,68,68,0.15)] hover:shadow-[0_0_16px_rgba(239,68,68,0.35)]"
                  style={{ height: `${blockPct}%` }}
                ></div>
                <span className="text-[10px] text-gray-500 font-semibold mt-2.5">Events</span>
              </div>
            </div>
          </div>

          <div className="text-xs text-gray-500 flex justify-between">
            <span>Live metrics computed from active datastore</span>
            <span className="font-semibold text-blue-500">Normal operations</span>
          </div>
        </div>

        {/* Top Universities */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">Top Universities</h3>
            <p className="text-xs text-gray-500 mt-1">Traffic mapped by university context.</p>
          </div>

          <div className="my-6 space-y-4 flex-1">
            {topUniversities.length === 0 ? (
              <div className="h-full flex items-center justify-center">
                <span className="text-xs text-gray-500">No active university sessions</span>
              </div>
            ) : (
              topUniversities.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="flex items-center space-x-2.5 min-w-0">
                    <School size={16} className="text-blue-500 shrink-0" />
                    <span className="text-xs font-medium text-gray-300 truncate">
                      {item.page_university_slug ? item.page_university_slug.toUpperCase() : "GENERAL / HOMEPAGE"}
                    </span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-bold text-gray-200">{item.count}</span>
                    <span className="text-[10px] text-gray-500">sessions</span>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="border-t border-[#1F2937] pt-4 flex justify-between items-center text-xs text-gray-500">
            <span>Total categorized sites</span>
            <span className="font-semibold text-gray-300">{topUniversities.length}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
