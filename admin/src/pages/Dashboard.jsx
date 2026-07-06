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
  BarChart3
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { LoadingState, ErrorState } from "../components/Common";

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [security, setSecurity] = useState(null);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        const [analyticsData, securityData, overviewData] = await Promise.all([
          api.getAnalytics(),
          api.getSecuritySummary(),
          api.getAnalyticsOverview(),
        ]);
        if (cancelled) return;
        setData(analyticsData);
        setSecurity(securityData);
        setOverview(overviewData);
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
    return () => { cancelled = true; };
  }, [refresh]);

  if (loading) return <LoadingState message="Connecting to analytics pipeline..." />;
  if (error) return <ErrorState title="Dashboard connection failed" description={error} retry={() => setRefresh((r) => r + 1)} />;

  // Computed metrics
  const totalSessions = data?.conversation_count || 0;
  const totalMessages = data?.message_count || 0;
  const totalLeads = data?.lead_count || 0;
  const totalBlocks = security?.total_blocks || 0;
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
    <div className="space-y-8">
      {/* Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
        <StatsCard
          title="Total Sessions"
          value={totalSessions.toLocaleString()}
          subtext="Total unique user chats initialized"
          icon={Activity}
        />
        <StatsCard
          title="Avg Response Time"
          value={`${((overview?.avg_response_time_ms || 0) / 1000).toFixed(2)}s`}
          subtext="E2E message generation latency"
          icon={Clock}
        />
        <StatsCard
          title="Avg TTFT"
          value={`${(overview?.avg_ttft_ms || 0).toFixed(0)}ms`}
          subtext="First token/decision latency"
          icon={Activity}
        />
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
        <StatsCard
          title="Cost Per Lead"
          value={`$${(overview?.cost_per_lead || 0).toFixed(4)}`}
          subtext="Model cost divided by leads count"
          icon={TrendingUp}
        />
        <StatsCard
          title="Threats Blocked"
          value={totalBlocks.toLocaleString()}
          subtext="Jailbreak & prompt injection threats"
          icon={AlertOctagon}
          trend={totalBlocks > 0 ? "Flagged" : "Clean"}
          trendType={totalBlocks > 0 ? "negative" : "positive"}
        />
        <StatsCard
          title="Unanswered Questions"
          value={unansweredCount.toLocaleString()}
          subtext="Missed queries recorded for resolution"
          icon={HelpCircle}
          trend={unansweredCount > 0 ? "Review Required" : "Zero Gaps"}
          trendType={unansweredCount > 0 ? "negative" : "positive"}
        />
      </div>

      {/* Visual Trends & Insights */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
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
                <span className="text-[10px] text-gray-500 font-semibold mt-2.5">Blocks</span>
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
