import React, { useEffect, useState } from "react";
import {
  MessageSquare,
  Users,
  AlertOctagon,
  HelpCircle,
  TrendingUp,
  School,
  Activity,
  Bookmark
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Dashboard() {
  const [data, setData] = useState(null);
  const [security, setSecurity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [analyticsData, securityData] = await Promise.all([
        api.getAnalytics(),
        api.getSecuritySummary(),
      ]);
      setData(analyticsData);
      setSecurity(securityData);
    } catch (err) {
      setError(err.message || "Failed to load dashboard metrics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading) return <LoadingState message="Connecting to analytics pipeline..." />;
  if (error) return <ErrorState title="Dashboard connection failed" description={error} retry={fetchData} />;

  // Computed metrics
  const totalSessions = data?.conversation_count || 0;
  const totalMessages = data?.message_count || 0;
  const totalLeads = data?.lead_count || 0;
  const totalBlocks = security?.total_blocks || 0;
  const unansweredCount = data?.unanswered_count || 0;

  const leadConvRate = totalSessions > 0 ? ((totalLeads / totalSessions) * 100).toFixed(1) : "0.0";

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
          title="Total Messages"
          value={totalMessages.toLocaleString()}
          subtext="Volume of incoming & outgoing messages"
          icon={MessageSquare}
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
          title="Blocked Attacks"
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
          
          <div className="my-8 h-48 flex items-end justify-between px-4 relative border-b border-[#1F2937]">
            {/* Visual Bar representations for active counts */}
            <div className="flex flex-col items-center w-1/4 group">
              <span className="text-xs font-semibold text-blue-400 mb-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {totalSessions}
              </span>
              <div
                className="w-12 bg-blue-500/80 hover:bg-blue-500 rounded-t-lg transition-all duration-500"
                style={{ height: `${Math.max(10, Math.min(100, (totalSessions / (totalMessages || 1)) * 100))}%` }}
              ></div>
              <span className="text-[10px] text-gray-500 font-medium mt-2">Sessions</span>
            </div>

            <div className="flex flex-col items-center w-1/4 group">
              <span className="text-xs font-semibold text-purple-400 mb-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {totalMessages}
              </span>
              <div
                className="w-12 bg-purple-500/80 hover:bg-purple-500 rounded-t-lg transition-all duration-500"
                style={{ height: `${totalMessages > 0 ? 100 : 10}%` }}
              ></div>
              <span className="text-[10px] text-gray-500 font-medium mt-2">Messages</span>
            </div>

            <div className="flex flex-col items-center w-1/4 group">
              <span className="text-xs font-semibold text-emerald-400 mb-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {totalLeads}
              </span>
              <div
                className="w-12 bg-emerald-500/80 hover:bg-emerald-500 rounded-t-lg transition-all duration-500"
                style={{ height: `${Math.max(10, Math.min(100, (totalLeads / (totalSessions || 1)) * 100))}%` }}
              ></div>
              <span className="text-[10px] text-gray-500 font-medium mt-2">Leads</span>
            </div>

            <div className="flex flex-col items-center w-1/4 group">
              <span className="text-xs font-semibold text-red-400 mb-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {totalBlocks}
              </span>
              <div
                className="w-12 bg-red-500/80 hover:bg-red-500 rounded-t-lg transition-all duration-500"
                style={{ height: `${Math.max(10, Math.min(100, (totalBlocks / (totalSessions || 1)) * 100))}%` }}
              ></div>
              <span className="text-[10px] text-gray-500 font-medium mt-2">Blocks</span>
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
