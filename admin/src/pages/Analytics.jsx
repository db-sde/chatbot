import React, { useEffect, useState } from "react";
import {
  BarChart3,
  School,
  Activity,
  Award,
  BookOpen,
  Cpu,
  Terminal,
  DollarSign,
  Clock,
  TrendingUp,
  Percent,
  Search,
  Filter
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Analytics() {
  const [overview, setOverview] = useState(null);
  const [models, setModels] = useState([]);
  const [tools, setTools] = useState([]);
  const [universities, setUniversities] = useState([]);
  const [costs, setCosts] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [leadIntentStats, setLeadIntentStats] = useState({ source_breakdown: [], intent_categories: [] });
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [overRes, modRes, toolRes, uniRes, costRes, funRes, leadRes] = await Promise.all([
        api.getAnalyticsOverview(),
        api.getAnalyticsModels(),
        api.getAnalyticsTools(),
        api.getAnalyticsUniversities(),
        api.getAnalyticsCosts(),
        api.getAnalyticsFunnel(),
        api.getAnalyticsLeads(),
      ]);
      setOverview(overRes);
      setModels(modRes || []);
      setTools(toolRes || []);
      setUniversities(uniRes || []);
      setCosts(costRes);
      setFunnel(funRes);
      setLeadIntentStats(leadRes || { source_breakdown: [], intent_categories: [] });
    } catch (err) {
      setError(err.message || "Failed to load observability metrics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading) return <LoadingState message="Calculating AI observability metrics and costs..." />;
  if (error) return <ErrorState title="observability fetch failed" description={error} retry={fetchData} />;

  return (
    <div className="space-y-8 text-left">
      {/* Overview Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-5">
        <StatsCard
          title="Avg Response Time"
          value={`${((overview?.avg_response_time_ms || 0) / 1000).toFixed(2)}s`}
          subtext="E2E synthesis latency"
          icon={Clock}
        />
        <StatsCard
          title="Avg TTFT"
          value={`${(overview?.avg_ttft_ms || 0).toFixed(0)}ms`}
          subtext="First token latency"
          icon={Activity}
        />
        <StatsCard
          title="Tokens Today"
          value={(overview?.total_tokens_today || 0).toLocaleString()}
          subtext="Prompt + generation"
          icon={BarChart3}
        />
        <StatsCard
          title="Cost Today"
          value={`$${(overview?.total_cost_today || 0.0).toFixed(4)}`}
          subtext="Estimated running costs"
          icon={DollarSign}
        />
        <StatsCard
          title="Leads Captured"
          value={overview?.total_leads || 0}
          subtext="Total acquired student details"
          icon={Award}
        />
        <StatsCard
          title="Cost Per Lead"
          value={`$${(overview?.cost_per_lead || 0.0).toFixed(4)}`}
          subtext="Total cost / Total leads"
          icon={TrendingUp}
        />
      </div>

      {/* Tabs Menu */}
      <div className="flex border-b border-[#1F2937] space-x-6 text-sm font-semibold text-gray-400">
        {[
          { id: "overview", label: "Model Metrics" },
          { id: "tools", label: "Tool Analytics" },
          { id: "universities", label: "University Contexts" },
          { id: "costs", label: "Cost Breakdown" },
          { id: "funnel", label: "Acquisition Funnel" },
          { id: "leads", label: "Lead Intent" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`pb-3 transition-colors ${
              activeTab === tab.id
                ? "border-b-2 border-blue-500 text-blue-400 font-bold"
                : "hover:text-gray-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Panels */}
      <div className="space-y-6">
        
        {/* Model Metrics Tab */}
        {activeTab === "overview" && (
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-gray-200 flex items-center gap-2">
                <Cpu size={16} className="text-blue-500" />
                LLM Provider Metrics
              </h3>
              <p className="text-xs text-gray-500 mt-1">Token volume, cost generation, and response latencies broken down by active LLM models.</p>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#1F2937] text-gray-400 font-semibold">
                    <th className="pb-3 pr-4">Model Name</th>
                    <th className="pb-3 px-4">Messages</th>
                    <th className="pb-3 px-4">Input Tokens</th>
                    <th className="pb-3 px-4">Output Tokens</th>
                    <th className="pb-3 px-4">Total Tokens</th>
                    <th className="pb-3 px-4">Avg Latency</th>
                    <th className="pb-3 px-4">Avg TTFT</th>
                    <th className="pb-3 pl-4 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1F2937]/50 text-gray-300 font-medium">
                  {models.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-gray-500">No model usage recorded.</td>
                    </tr>
                  ) : (
                    models.map((m, idx) => (
                      <tr key={idx} className="hover:bg-[#1C2333]/20">
                        <td className="py-3 pr-4 font-mono font-bold text-blue-400">{m.model_name}</td>
                        <td className="py-3 px-4">{m.messages}</td>
                        <td className="py-3 px-4 font-mono text-[11px] text-gray-400">{m.input_tokens.toLocaleString()}</td>
                        <td className="py-3 px-4 font-mono text-[11px] text-gray-400">{m.output_tokens.toLocaleString()}</td>
                        <td className="py-3 px-4 font-mono font-semibold text-gray-300">{m.total_tokens.toLocaleString()}</td>
                        <td className="py-3 px-4 font-mono text-gray-400">{(Number(m.avg_response_time) / 1000).toFixed(2)}s</td>
                        <td className="py-3 px-4 font-mono text-gray-400">{Number(m.avg_ttft).toFixed(0)}ms</td>
                        <td className="py-3 pl-4 font-mono text-emerald-400 text-right font-bold">${parseFloat(m.total_cost).toFixed(6)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tool Analytics Tab */}
        {activeTab === "tools" && (
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-gray-200 flex items-center gap-2">
                <Terminal size={16} className="text-blue-500" />
                LangGraph Tool Executions
              </h3>
              <p className="text-xs text-gray-500 mt-1">Audit execution counts, average latency, and success rates for SQL/Catalog query tools.</p>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#1F2937] text-gray-400 font-semibold">
                    <th className="pb-3 pr-4">Tool Name</th>
                    <th className="pb-3 px-4">Executions</th>
                    <th className="pb-3 px-4">Avg Duration</th>
                    <th className="pb-3 px-4">Max Duration</th>
                    <th className="pb-3 px-4">Failures</th>
                    <th className="pb-3 pl-4 text-right">Success Rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1F2937]/50 text-gray-300 font-medium">
                  {tools.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-gray-500">No tool executions recorded.</td>
                    </tr>
                  ) : (
                    tools.map((t, idx) => (
                      <tr key={idx} className="hover:bg-[#1C2333]/20">
                        <td className="py-3 pr-4 font-mono font-bold text-blue-400">{t.name}</td>
                        <td className="py-3 px-4">{t.executions}</td>
                        <td className="py-3 px-4 font-mono">{Number(t.avg_duration).toFixed(0)}ms</td>
                        <td className="py-3 px-4 font-mono text-gray-400">{t.max_duration}ms</td>
                        <td className="py-3 px-4 font-mono text-red-400">{t.failure_count}</td>
                        <td className="py-3 pl-4 text-right font-mono">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            t.success_rate >= 98 ? "bg-emerald-950/40 text-emerald-400 border border-emerald-900/30" : "bg-yellow-950/40 text-yellow-400"
                          }`}>
                            {t.success_rate}%
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* University Contexts Tab */}
        {activeTab === "universities" && (
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
            <div>
              <h3 className="text-sm font-bold text-gray-200 flex items-center gap-2">
                <School size={16} className="text-blue-500" />
                University Channel Performance
              </h3>
              <p className="text-xs text-gray-500 mt-1">Usage, lead capture conversion rates, and total token costs categorized by university widgets.</p>
            </div>
            
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#1F2937] text-gray-400 font-semibold">
                    <th className="pb-3 pr-4">University Channel</th>
                    <th className="pb-3 px-4">Chats</th>
                    <th className="pb-3 px-4">Messages</th>
                    <th className="pb-3 px-4">Leads</th>
                    <th className="pb-3 px-4">Conversion Rate</th>
                    <th className="pb-3 px-4">Tokens</th>
                    <th className="pb-3 px-4">Avg Latency</th>
                    <th className="pb-3 pl-4 text-right">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1F2937]/50 text-gray-300 font-medium">
                  {universities.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-gray-500">No university context usage recorded.</td>
                    </tr>
                  ) : (
                    universities.map((u, idx) => (
                      <tr key={idx} className="hover:bg-[#1C2333]/20">
                        <td className="py-3 pr-4 font-mono font-semibold uppercase text-gray-200">{u.university}</td>
                        <td className="py-3 px-4">{u.chats}</td>
                        <td className="py-3 px-4 text-gray-400">{u.messages}</td>
                        <td className="py-3 px-4">{u.leads}</td>
                        <td className="py-3 px-4 font-mono font-bold text-blue-400">{u.conversion_rate}%</td>
                        <td className="py-3 px-4 font-mono text-[11px] text-gray-400">{u.total_tokens.toLocaleString()}</td>
                        <td className="py-3 px-4 font-mono text-gray-400">{(Number(u.avg_response_time) / 1000).toFixed(2)}s</td>
                        <td className="py-3 pl-4 font-mono text-emerald-400 text-right font-semibold">${parseFloat(u.total_cost).toFixed(4)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Cost Breakdown Tab */}
        {activeTab === "costs" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Side: Summary Cards */}
            <div className="space-y-6">
              <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
                <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider">Cost Aggregates</h4>
                <div className="space-y-3 text-xs">
                  <div className="flex justify-between">
                    <span className="text-gray-500">Today's Spend</span>
                    <span className="font-mono text-gray-200 font-semibold">${(costs?.cost_today || 0.0).toFixed(4)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Last 7 Days</span>
                    <span className="font-mono text-gray-200 font-semibold">${(costs?.cost_week || 0.0).toFixed(4)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-500">Last 30 Days</span>
                    <span className="font-mono text-gray-200 font-semibold">${(costs?.cost_month || 0.0).toFixed(4)}</span>
                  </div>
                  <div className="border-t border-[#1F2937]/60 pt-3 flex justify-between">
                    <span className="text-gray-400 font-semibold">Total Cumulative Spend</span>
                    <span className="font-mono text-emerald-400 font-bold">${(costs?.total_cost || 0.0).toFixed(4)}</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Side: Expensive Chats */}
            <div className="lg:col-span-2 bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
              <div>
                <h4 className="text-xs font-bold text-gray-200 flex items-center gap-2">
                  <DollarSign size={14} className="text-blue-500" />
                  Most Expensive Conversations
                </h4>
                <p className="text-[10px] text-gray-500 mt-1">Audit which visitor sessions consume the highest volume of API credits.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[#1F2937] text-gray-400">
                      <th className="pb-3 pr-4">Session ID</th>
                      <th className="pb-3 px-4">Messages</th>
                      <th className="pb-3 px-4">Total Tokens</th>
                      <th className="pb-3 px-4">Date</th>
                      <th className="pb-3 pl-4 text-right">Estimated Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1F2937]/50 text-gray-300 font-medium">
                    {!costs?.expensive_conversations || costs.expensive_conversations.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="py-8 text-center text-gray-500">No sessions recorded.</td>
                      </tr>
                    ) : (
                      costs.expensive_conversations.map((c, idx) => (
                        <tr key={idx} className="hover:bg-[#1C2333]/20">
                          <td className="py-3 pr-4 font-mono text-[11px] text-blue-400">{c.session_id}</td>
                          <td className="py-3 px-4">{c.message_count}</td>
                          <td className="py-3 px-4 font-mono text-gray-400">{c.total_tokens.toLocaleString()}</td>
                          <td className="py-3 px-4 text-gray-400">{new Date(c.started_at).toLocaleDateString()}</td>
                          <td className="py-3 pl-4 font-mono text-emerald-400 text-right font-semibold">${parseFloat(c.total_cost).toFixed(5)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Funnel Analytics Tab */}
        {activeTab === "funnel" && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Funnel Layout */}
            <div className="lg:col-span-2 bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-6">
              <h4 className="text-xs font-bold text-gray-200">Visitor Acquisition Funnel</h4>
              
              <div className="space-y-5">
                {[
                  { label: "1. Total Visitors", count: funnel?.visitors || 0, percent: 100, color: "bg-blue-600" },
                  { label: "2. Conversation Starters", count: funnel?.conversations || 0, percent: funnel?.visitors ? ((funnel.conversations / funnel.visitors) * 100).toFixed(1) : 0, color: "bg-indigo-600" },
                  { label: "3. Qualified Chats (>=3 msgs)", count: funnel?.qualified_conversations || 0, percent: funnel?.visitors ? ((funnel.qualified_conversations / funnel.visitors) * 100).toFixed(1) : 0, color: "bg-purple-600" },
                  { label: "4. Captured Lead Profiles", count: funnel?.leads || 0, percent: funnel?.visitors ? ((funnel.leads / funnel.visitors) * 100).toFixed(1) : 0, color: "bg-emerald-600" },
                ].map((stage, idx) => (
                  <div key={idx} className="space-y-1.5">
                    <div className="flex justify-between items-center text-xs">
                      <span className="font-semibold text-gray-300">{stage.label}</span>
                      <span className="font-mono text-gray-400">{stage.count} ({stage.percent}%)</span>
                    </div>
                    <div className="w-full bg-gray-800 rounded-full h-3">
                      <div
                        className={`${stage.color} h-3 rounded-full transition-all duration-500`}
                        style={{ width: `${stage.percent}%` }}
                      ></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Acquisition Cost Cards */}
            <div className="space-y-6">
              <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
                <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider">SaaS Acquisition Metrics</h4>
                <div className="space-y-4 pt-2">
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-gray-500">Cost Per Conversation</span>
                    <span className="font-mono text-gray-200 font-bold">${parseFloat(funnel?.cost_per_conversation || 0).toFixed(4)}</span>
                  </div>
                  <div className="flex justify-between items-center text-xs">
                    <span className="text-gray-500">Cost Per Qualified Lead</span>
                    <span className="font-mono text-emerald-400 font-bold">${parseFloat(funnel?.cost_per_lead || 0).toFixed(4)}</span>
                  </div>
                  <div className="border-t border-[#1F2937]/60 pt-3 text-[10px] text-gray-500 leading-relaxed">
                    Calculated by dividing the total estimated model/token spend by the respective funnel stage volume.
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Lead Intent Tab */}
        {activeTab === "leads" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left Card: Lead Source Breakdown */}
            <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
              <div>
                <h4 className="text-xs font-bold text-gray-200 uppercase tracking-wider flex items-center gap-2">
                  <TrendingUp size={14} className="text-emerald-500" />
                  Lead Source Breakdown
                </h4>
                <p className="text-[10px] text-gray-500 mt-1">Comparison of lead acquisitions triggered by Score Engine vs next-gen LLM Intent detection.</p>
              </div>
              <div className="space-y-4 pt-2">
                {!leadIntentStats?.source_breakdown || leadIntentStats.source_breakdown.length === 0 ? (
                  <div className="text-xs text-gray-500 py-4 text-center">No lead sources logged yet.</div>
                ) : (
                  leadIntentStats.source_breakdown.map((src, idx) => (
                    <div key={idx} className="space-y-1.5">
                      <div className="flex justify-between items-center text-xs">
                        <span className="font-semibold text-gray-300">{src.source}</span>
                        <span className="font-mono text-gray-400">{src.count} ({src.percentage}%)</span>
                      </div>
                      <div className="w-full bg-gray-800 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full transition-all duration-500 ${
                            src.source === "LLM Intent" ? "bg-emerald-500" : "bg-blue-500"
                          }`}
                          style={{ width: `${src.percentage}%` }}
                        ></div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Right Card: Intent Categories */}
            <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
              <div>
                <h4 className="text-xs font-bold text-gray-200 uppercase tracking-wider flex items-center gap-2">
                  <Cpu size={14} className="text-indigo-500" />
                  Intent Categories Distribution
                </h4>
                <p className="text-[10px] text-gray-500 mt-1">Semantic classification categories identified by the LLM Intent Classifier.</p>
              </div>
              <div className="space-y-4 pt-2">
                {!leadIntentStats?.intent_categories || leadIntentStats.intent_categories.length === 0 ? (
                  <div className="text-xs text-gray-500 py-4 text-center">No intent categories recorded yet.</div>
                ) : (
                  leadIntentStats.intent_categories.map((cat, idx) => (
                    <div key={idx} className="space-y-1.5">
                      <div className="flex justify-between items-center text-xs">
                        <span className="font-semibold text-gray-300">{cat.category}</span>
                        <span className="font-mono text-gray-400">{cat.count} ({cat.percentage}%)</span>
                      </div>
                      <div className="w-full bg-gray-800 rounded-full h-2">
                        <div
                          className="h-2 rounded-full bg-indigo-500 transition-all duration-500"
                          style={{ width: `${cat.percentage}%` }}
                        ></div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
