import React, { useEffect, useState } from "react";
import {
  BarChart3,
  School,
  Activity,
  Award,
  BookOpen
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Analytics() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const analyticsData = await api.getAnalytics();
      setData(analyticsData);
    } catch (err) {
      setError(err.message || "Failed to load analytics records.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  if (loading) return <LoadingState message="Analyzing catalog performance indexes..." />;
  if (error) return <ErrorState title="Analytics scan failed" description={error} retry={fetchAnalytics} />;

  const topUniversities = data?.top_universities || [];

  return (
    <div className="space-y-8 text-left">
      {/* Overview stats header */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatsCard
          title="Session Volume"
          value={data?.conversation_count || 0}
          subtext="All-time chat session interactions"
          icon={Activity}
        />
        <StatsCard
          title="Message Activity"
          value={data?.message_count || 0}
          subtext="Total inbound/outbound prompt exchanges"
          icon={BarChart3}
        />
        <StatsCard
          title="Lead Generation"
          value={data?.lead_count || 0}
          subtext="Successful student conversions recorded"
          icon={Award}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* University performance */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">University Performance</h3>
            <p className="text-xs text-gray-500 mt-1">Relative session volume mapped by university tags.</p>
          </div>

          <div className="my-6 space-y-4 flex-1">
            {topUniversities.length === 0 ? (
              <div className="h-full flex items-center justify-center py-8">
                <span className="text-xs text-gray-500">No active university context data found</span>
              </div>
            ) : (
              topUniversities.map((item, idx) => (
                <div key={idx} className="space-y-1.5">
                  <div className="flex justify-between items-center text-xs font-semibold text-gray-300">
                    <span className="truncate uppercase">{item.page_university_slug || "Homepage Context"}</span>
                    <span>{item.count} sessions</span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-2">
                    <div
                      className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.min(
                          100,
                          (item.count / Math.max(1, topUniversities[0]?.count || 1)) * 100
                        )}%`,
                      }}
                    ></div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Course performance - No backend API exists yet */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">Course & Program Performance</h3>
            <p className="text-xs text-gray-500 mt-1">Detailed view counts and leads generated per course.</p>
          </div>

          <div className="my-6 flex-1 flex items-center justify-center border border-[#1F2937] border-dashed rounded-xl bg-[#0E131F]/30 p-8 text-center">
            <div>
              <BookOpen size={24} className="text-gray-600 mx-auto mb-2" />
              <h4 className="text-xs font-semibold text-gray-400">Course Data Unavailable</h4>
              <p className="text-[10px] text-gray-500 mt-1 max-w-[240px] mx-auto">
                No real database mappings exist for top course metrics yet. Under construction.
              </p>
            </div>
          </div>
        </div>

        {/* Daily message trends - No backend API exists yet */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">Daily Message Volume Trend</h3>
            <p className="text-xs text-gray-500 mt-1">Timeseries distribution of student prompts over time.</p>
          </div>

          <div className="my-6 flex-1 flex items-center justify-center border border-[#1F2937] border-dashed rounded-xl bg-[#0E131F]/30 p-8 text-center">
            <div>
              <Activity size={24} className="text-gray-600 mx-auto mb-2" />
              <h4 className="text-xs font-semibold text-gray-400">Trend Data Unavailable</h4>
              <p className="text-[10px] text-gray-500 mt-1 max-w-[240px] mx-auto">
                Timeseries metrics are not exposed by the current analytics endpoint.
              </p>
            </div>
          </div>
        </div>

        {/* Lead Conversion trend - No backend API exists yet */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">Lead Conversion Analytics</h3>
            <p className="text-xs text-gray-500 mt-1">Breakdown of form conversion rates by channel.</p>
          </div>

          <div className="my-6 flex-1 flex items-center justify-center border border-[#1F2937] border-dashed rounded-xl bg-[#0E131F]/30 p-8 text-center">
            <div>
              <Award size={24} className="text-gray-600 mx-auto mb-2" />
              <h4 className="text-xs font-semibold text-gray-400">Conversion Breakdown Unavailable</h4>
              <p className="text-[10px] text-gray-500 mt-1 max-w-[240px] mx-auto">
                Granular lead attribution tracking is under development.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
