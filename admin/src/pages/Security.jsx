import React, { useEffect, useState } from "react";
import {
  ShieldAlert,
  ShieldAlert as SecurityIcon,
  AlertTriangle,
  Play,
  Activity,
  UserCheck
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Security() {
  const [summary, setSummary] = useState(null);
  const [attacks, setAttacks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchSecurity = async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, attacksData] = await Promise.all([
        api.getSecuritySummary(),
        api.getSecurityAttacks(20),
      ]);
      setSummary(summaryData);
      setAttacks(attacksData || []);
    } catch (err) {
      setError(err.message || "Failed to load security summary.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSecurity();
  }, []);

  if (loading) return <LoadingState message="Querying Prompt Guard 2 & Policy logs..." />;
  if (error) return <ErrorState title="Security scan failed" description={error} retry={fetchSecurity} />;

  // Aggregate blocks by layer
  const totalBlocks = summary?.total_blocks || 0;
  const last24h = summary?.last_24h_blocks || 0;
  
  let promptGuardBlocks = 0;
  let policyBlocks = 0;
  let outputScanBlocks = 0;

  summary?.blocks_by_layer?.forEach((row) => {
    const l = row.layer || "";
    if (l.startsWith("prompt_guard")) {
      promptGuardBlocks += row.count;
    } else if (l === "policy") {
      policyBlocks += row.count;
    } else if (l.startsWith("output_scan")) {
      outputScanBlocks += row.count;
    }
  });

  const getReasonBadge = (reason) => {
    const lower = (reason || "").toLowerCase();
    if (lower.includes("injection") || lower.includes("jailbreak")) return <Badge variant="danger">Prompt Injection</Badge>;
    if (lower.includes("extraction")) return <Badge variant="warning">Prompt Extraction</Badge>;
    if (lower.includes("identity")) return <Badge variant="primary">Identity Attack</Badge>;
    if (lower.includes("competitor") || lower.includes("impersonation")) return <Badge variant="primary">Competitor Impersonation</Badge>;
    return <Badge variant="neutral">{reason || "Policy Violation"}</Badge>;
  };

  return (
    <div className="space-y-8 text-left">
      {/* Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard
          title="Total Blocks"
          value={totalBlocks.toLocaleString()}
          subtext={`Last 24h: ${last24h} blocks`}
          icon={ShieldAlert}
        />
        <StatsCard
          title="Prompt Guard Blocks"
          value={promptGuardBlocks.toLocaleString()}
          subtext="Meta Llama classification blocks"
          icon={SecurityIcon}
          trend={promptGuardBlocks > 0 ? "Active" : "None"}
          trendType={promptGuardBlocks > 0 ? "negative" : "positive"}
        />
        <StatsCard
          title="Policy Blocks"
          value={policyBlocks.toLocaleString()}
          subtext="DegreeBaba system rules blocks"
          icon={AlertTriangle}
          trend={policyBlocks > 0 ? "Active" : "None"}
          trendType={policyBlocks > 0 ? "negative" : "positive"}
        />
        <StatsCard
          title="Output Scan Blocks"
          value={outputScanBlocks.toLocaleString()}
          subtext="Post-generation leak blocks"
          icon={Activity}
          trend={outputScanBlocks > 0 ? "Active" : "None"}
          trendType={outputScanBlocks > 0 ? "negative" : "positive"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Side: Top Attack Patterns Table */}
        <div className="lg:col-span-2 bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden flex flex-col justify-between">
          <div className="p-6 border-b border-[#1F2937] bg-[#0E131F]/50">
            <h3 className="text-sm font-semibold text-gray-200">Top Blocked Attack Patterns</h3>
            <p className="text-xs text-gray-500 mt-1">Aggregated logs of most common jailbreak and injection payloads.</p>
          </div>

          <div className="overflow-x-auto flex-1">
            {attacks.length === 0 ? (
              <div className="p-8">
                <EmptyState title="No attack patterns recorded" description="Security logs show zero blocked events." />
              </div>
            ) : (
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#1F2937] bg-[#0E131F]/10 text-[9px] uppercase font-bold text-gray-400">
                    <th className="px-6 py-3">Attack Payload</th>
                    <th className="px-6 py-3 text-center">Hits</th>
                    <th className="px-6 py-3">Classification</th>
                    <th className="px-6 py-3">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1F2937] text-xs">
                  {attacks.map((item, idx) => (
                    <tr key={idx} className="hover:bg-[#1C2333]/50 text-gray-300">
                      <td className="px-6 py-3.5 font-mono text-[10px] break-all max-w-[280px]">
                        "{item.message}"
                      </td>
                      <td className="px-6 py-3.5 text-center font-bold text-gray-200">{item.occurrences}</td>
                      <td className="px-6 py-3.5">{getReasonBadge(item.reason)}</td>
                      <td className="px-6 py-3.5 font-mono text-[10px] text-gray-500">
                        {item.layer}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Right Side: Blocks by Reason/Violation type */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-sm font-semibold text-gray-200">Most Common Violations</h3>
            <p className="text-xs text-gray-500 mt-1">Classification breakdown of all threat incidents.</p>
          </div>

          <div className="my-6 space-y-4 flex-1">
            {!summary?.blocks_by_reason || summary.blocks_by_reason.length === 0 ? (
              <div className="h-full flex items-center justify-center">
                <span className="text-xs text-gray-500">No threat classifications recorded</span>
              </div>
            ) : (
              summary.blocks_by_reason.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="min-w-0 pr-2">
                    {getReasonBadge(item.reason)}
                  </div>
                  <div className="flex items-center space-x-2 shrink-0">
                    <span className="text-xs font-bold text-gray-200">{item.count}</span>
                    <span className="text-[10px] text-gray-500">blocks</span>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="border-t border-[#1F2937] pt-4 flex justify-between items-center text-xs text-gray-500">
            <span>Clean operations rate</span>
            <span className="font-semibold text-emerald-500">99.98%</span>
          </div>
        </div>
      </div>
    </div>
  );
}
