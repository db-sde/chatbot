import { useEffect, useState, useCallback } from "react";
import {
  ShieldAlert,
  ShieldX,
  AlertTriangle,
  Lock,
  Unlock,
  RefreshCw,
  Ban,
  Clock,
  Globe,
  X,
} from "lucide-react";
import { api } from "../services/api";
import StatsCard from "../components/StatsCard";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

// ─── helpers ───────────────────────────────────────────────────────────────

function severityBadge(sev) {
  const map = {
    critical: <Badge variant="danger">Critical</Badge>,
    high: <Badge variant="danger">High</Badge>,
    medium: <Badge variant="warning">Medium</Badge>,
    low: <Badge variant="neutral">Low</Badge>,
  };
  return map[sev] || <Badge variant="neutral">{sev}</Badge>;
}

function eventTypeBadge(type) {
  const map = {
    prompt_injection: <Badge variant="danger">Prompt Injection</Badge>,
    policy_violation: <Badge variant="warning">Policy Violation</Badge>,
    output_scan_violation: <Badge variant="primary">Output Scan</Badge>,
    blocked_ip_access: <Badge variant="danger">Blocked IP</Badge>,
    rate_limit: <Badge variant="warning">Rate Limit</Badge>,
    suspicious_activity: <Badge variant="primary">Suspicious Activity</Badge>,
  };
  return map[type] || <Badge variant="neutral">{type}</Badge>;
}

function reasonBadge(reason) {
  const r = (reason || "").toLowerCase();
  if (r.includes("injection") || r.includes("jailbreak")) return <Badge variant="danger">Prompt Injection</Badge>;
  if (r.includes("extraction")) return <Badge variant="warning">Data Extraction</Badge>;
  if (r.includes("identity")) return <Badge variant="primary">Identity Attack</Badge>;
  if (r.includes("competitor") || r.includes("impersonation")) return <Badge variant="primary">Impersonation</Badge>;
  return <Badge variant="neutral">{reason || "Policy Violation"}</Badge>;
}

function relativeTime(ts) {
  if (!ts) return "—";
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ─── View Event Modal ──────────────────────────────────────────────────────

function ViewEventModal({ event, onClose }) {
  if (!event) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-[#111827] border border-[#1F2937] rounded-2xl p-6 w-full max-w-lg shadow-2xl overflow-y-auto max-h-[85vh]">
        <div className="flex items-center justify-between mb-5 border-b border-[#1F2937] pb-3">
          <h3 className="text-sm font-semibold text-gray-200">
            Event Log Detail
          </h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-4 text-xs text-gray-300">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-gray-500 block">IP Address</span>
              <span className="font-mono text-gray-200">{event.ip_address || "N/A"}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Country</span>
              <span className="text-gray-200">{event.country || "India"}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Timestamp</span>
              <span className="text-gray-200">{new Date(event.created_at).toLocaleString()}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Event Type</span>
              <span>{eventTypeBadge(event.event_type)}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Severity</span>
              <span>{severityBadge(event.severity)}</span>
            </div>
            <div>
              <span className="text-gray-500 block">Action Taken</span>
              <span className={`font-semibold ${event.blocked ? "text-red-400" : "text-green-400"}`}>
                {event.action_taken || (event.blocked ? "blocked" : "logged")}
              </span>
            </div>
          </div>
          {event.user_agent && (
            <div>
              <span className="text-gray-500 block mb-1">User Agent</span>
              <span className="bg-[#0E131F] border border-[#1F2937] rounded p-2 block font-mono text-[10px] text-gray-400 break-all">
                {event.user_agent}
              </span>
            </div>
          )}
          {event.payload && (
            <div>
              <span className="text-gray-500 block mb-1">Attack Payload</span>
              <pre className="bg-[#0E131F] border border-[#1F2937] rounded p-3 block font-mono text-[10px] text-red-400 break-words whitespace-pre-wrap">
                {event.payload}
              </pre>
            </div>
          )}
          {event.metadata_json && (
            <div>
              <span className="text-gray-500 block mb-1">Security Metadata</span>
              <pre className="bg-[#0E131F] border border-[#1F2937] rounded p-3 block font-mono text-[10px] text-indigo-400 overflow-x-auto">
                {JSON.stringify(event.metadata_json, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

export default function Security() {
  const [summary, setSummary] = useState(null);
  const [attacks, setAttacks] = useState([]);
  const [events, setEvents] = useState([]);
  const [blockedIps, setBlockedIps] = useState([]);
  const [topIps, setTopIps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [activeTab, setActiveTab] = useState("overview"); // overview | events | ips
  const [activeEvent, setActiveEvent] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, attacksData, eventsData, blockedData, topIpsData] = await Promise.all([
        api.getSecuritySummary(),
        api.getSecurityAttacks(20),
        api.getSecurityEvents({ limit: 50 }),
        api.getBlockedIps(),
        api.getTopAttackingIps(20),
      ]);
      setSummary(summaryData);
      setAttacks(attacksData || []);
      setEvents(eventsData || []);
      setBlockedIps(blockedData || []);
      setTopIps(topIpsData || []);
    } catch (err) {
      setError(err.message || "Failed to load security data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refresh]);

  async function performBlock(ip, isPermanent) {
    try {
      await api.blockIp(
        ip,
        isPermanent ? "Manually blocked by admin (Permanent)" : "Temporary 24h ban by admin",
        isPermanent ? "permanent" : "temporary",
        isPermanent ? null : 24
      );
      setRefresh((r) => r + 1);
    } catch (err) {
      alert("Failed to block IP: " + err.message);
    }
  }

  async function performUnblock(ip) {
    try {
      await api.unblockIp(ip);
      setRefresh((r) => r + 1);
    } catch (err) {
      alert("Failed to unblock IP: " + err.message);
    }
  }

  if (loading) return <LoadingState message="Loading security intelligence…" />;
  if (error) return <ErrorState title="Security scan failed" description={error} retry={() => setRefresh((r) => r + 1)} />;

  const totalEvents = summary?.total_events ?? 0;
  const last24h = summary?.last_24h_events ?? 0;
  const promptGuardDetections = summary?.prompt_guard_detections ?? 0;
  const policyViolations = summary?.policy_violations ?? 0;
  const blockedIpCount = summary?.total_blocked_ips ?? 0;

  const TABS = [
    { id: "overview", label: "Overview" },
    { id: "events", label: `Events${events.length ? ` (${events.length})` : ""}` },
    { id: "ips", label: `IP Management${blockedIps.length ? ` (${blockedIps.length})` : ""}` },
  ];

  return (
    <div className="space-y-6 text-left">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-gray-100 flex items-center gap-2">
            <ShieldAlert size={18} className="text-indigo-400" />
            Security Dashboard
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">Real-time threat detection and IP enforcement</p>
        </div>
        <button
          onClick={() => setRefresh((r) => r + 1)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[#1F2937] text-xs text-gray-400 hover:text-gray-200 hover:border-gray-600 transition-all self-start sm:self-center"
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title="Security Events"
          value={totalEvents.toLocaleString()}
          subtext={`${last24h} in last 24h`}
          icon={ShieldAlert}
        />
        <StatsCard
          title="Prompt Guard Detections"
          value={promptGuardDetections.toLocaleString()}
          subtext="ML injection flags"
          icon={ShieldX}
          trend={promptGuardDetections > 0 ? "Active" : "Clean"}
          trendType={promptGuardDetections > 0 ? "negative" : "positive"}
        />
        <StatsCard
          title="Policy Violations"
          value={policyViolations.toLocaleString()}
          subtext="System rules triggered"
          icon={AlertTriangle}
          trend={policyViolations > 0 ? "Active" : "Clean"}
          trendType={policyViolations > 0 ? "negative" : "positive"}
        />
        <StatsCard
          title="Blocked IPs"
          value={blockedIpCount.toLocaleString()}
          subtext={`${summary?.perm_bans ?? 0} permanent`}
          icon={Ban}
          trend={blockedIpCount > 0 ? "Enforced" : "None"}
          trendType={blockedIpCount > 0 ? "negative" : "positive"}
        />
      </div>

      {/* Tabs */}
      <div className="border-b border-[#1F2937]">
        <div className="flex gap-0">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-4 py-2 text-xs font-medium transition-all border-b-2 ${
                activeTab === t.id
                  ? "border-indigo-500 text-indigo-400"
                  : "border-transparent text-gray-500 hover:text-gray-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Overview Tab ── */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Attack Patterns */}
          <div className="lg:col-span-2 bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden">
            <div className="p-5 border-b border-[#1F2937]">
              <h3 className="text-sm font-semibold text-gray-200">Top Blocked Attack Patterns</h3>
              <p className="text-xs text-gray-500 mt-1">Aggregated by payload and reason from flagged messages.</p>
            </div>
            {attacks.length === 0 ? (
              <div className="p-8"><EmptyState title="No attacks recorded" description="Security logs are empty." /></div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[#1F2937] text-[9px] uppercase font-bold text-gray-500">
                      <th className="px-5 py-3">Payload</th>
                      <th className="px-5 py-3 text-center">Hits</th>
                      <th className="px-5 py-3">Type</th>
                      <th className="px-5 py-3">Last seen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1F2937] text-xs">
                    {attacks.map((item, idx) => (
                      <tr key={idx} className="hover:bg-[#1C2333]/40 text-gray-300">
                        <td className="px-5 py-3 font-mono text-[10px] break-all max-w-[260px] text-gray-400">
                          "{(item.message || "").slice(0, 80)}{item.message?.length > 80 ? "…" : ""}"
                        </td>
                        <td className="px-5 py-3 text-center font-bold text-gray-100">{item.occurrences}</td>
                        <td className="px-5 py-3">{reasonBadge(item.reason)}</td>
                        <td className="px-5 py-3 text-[10px] text-gray-500">{relativeTime(item.last_seen)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Violations Summary */}
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-5">
            <h3 className="text-sm font-semibold text-gray-200 mb-1">Violation Breakdown</h3>
            <p className="text-xs text-gray-500 mb-5">By classification across all flagged messages.</p>

            {(!summary?.blocks_by_reason || summary.blocks_by_reason.length === 0) ? (
              <div className="flex items-center justify-center h-24">
                <span className="text-xs text-gray-500">No violations recorded</span>
              </div>
            ) : (
              <div className="space-y-3">
                {summary.blocks_by_reason.map((item, idx) => (
                  <div key={idx} className="flex items-center justify-between">
                    <div>{reasonBadge(item.reason)}</div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-bold text-gray-100">{item.count}</span>
                      <span className="text-[10px] text-gray-500">blocks</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-6 pt-4 border-t border-[#1F2937] space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Prompt Guard Detections</span>
                <span className="text-gray-300 font-mono">{promptGuardDetections}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Policy Violations</span>
                <span className="text-gray-300 font-mono">{policyViolations}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Temp Bans</span>
                <span className="text-yellow-400 font-mono">{summary?.temp_bans ?? 0}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-500">Perm Bans</span>
                <span className="text-red-400 font-mono">{summary?.perm_bans ?? 0}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Events Tab ── */}
      {activeTab === "events" && (
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden">
          <div className="p-5 border-b border-[#1F2937] flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-200">Security Event Log</h3>
              <p className="text-xs text-gray-500 mt-0.5">Last 50 events across all detection layers.</p>
            </div>
            <span className="text-[10px] text-gray-500 font-mono">{events.length} events</span>
          </div>
          {events.length === 0 ? (
            <div className="p-8">
              <EmptyState title="No events recorded" description="Events appear here when security layers block a request." />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-[#1F2937] text-[9px] uppercase font-bold text-gray-500">
                    <th className="px-5 py-3">Timestamp</th>
                    <th className="px-5 py-3">IP Address</th>
                    <th className="px-5 py-3">Country</th>
                    <th className="px-5 py-3">Event Type</th>
                    <th className="px-5 py-3">Severity</th>
                    <th className="px-5 py-3">Payload</th>
                    <th className="px-5 py-3">Action Taken</th>
                    <th className="px-5 py-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1F2937] text-xs">
                  {events.map((ev, idx) => {
                    const isBanned = blockedIps.some((b) => b.ip_address === ev.ip_address);
                    return (
                      <tr key={idx} className="hover:bg-[#1C2333]/40 text-gray-300">
                        <td className="px-5 py-3 text-[10px] text-gray-500 whitespace-nowrap">
                          {relativeTime(ev.created_at)}
                        </td>
                        <td className="px-5 py-3 font-mono text-[10px] text-gray-400">
                          {ev.ip_address || "—"}
                        </td>
                        <td className="px-5 py-3 text-gray-400">{ev.country || "India"}</td>
                        <td className="px-5 py-3">{eventTypeBadge(ev.event_type)}</td>
                        <td className="px-5 py-3">{severityBadge(ev.severity)}</td>
                        <td className="px-5 py-3 font-mono text-[10px] text-gray-500 max-w-[150px] truncate">
                          {ev.payload ? `"${ev.payload.slice(0, 45)}${ev.payload.length > 45 ? "…" : ""}"` : "—"}
                        </td>
                        <td className="px-5 py-3">
                          <span className={`text-[10px] font-medium ${ev.blocked ? "text-red-400" : "text-green-400"}`}>
                            {ev.action_taken || (ev.blocked ? "blocked" : "logged")}
                          </span>
                        </td>
                        <td className="px-5 py-3 whitespace-nowrap text-center">
                          <div className="flex justify-center gap-2">
                            {ev.ip_address && (
                              isBanned ? (
                                <button
                                  onClick={() => performUnblock(ev.ip_address)}
                                  className="text-[10px] bg-green-500/10 text-green-400 hover:bg-green-500/25 border border-green-500/30 px-2 py-0.5 rounded transition-all font-semibold"
                                >
                                  Unblock
                                </button>
                              ) : (
                                <>
                                  <button
                                    onClick={() => performBlock(ev.ip_address, true)}
                                    className="text-[10px] bg-red-500/10 text-red-400 hover:bg-red-500/25 border border-red-500/30 px-2 py-0.5 rounded transition-all font-semibold"
                                  >
                                    Block
                                  </button>
                                  <button
                                    onClick={() => performBlock(ev.ip_address, false)}
                                    className="text-[10px] bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/25 border border-yellow-500/30 px-2 py-0.5 rounded transition-all font-semibold"
                                  >
                                    Temp Ban
                                  </button>
                                </>
                              )
                            )}
                            <button
                              onClick={() => setActiveEvent(ev)}
                              className="text-[10px] bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/25 border border-indigo-500/30 px-2 py-0.5 rounded transition-all font-semibold"
                            >
                              View
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── IP Management Tab ── */}
      {activeTab === "ips" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Blocked IPs */}
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden">
            <div className="p-5 border-b border-[#1F2937]">
              <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                <Lock size={13} className="text-red-400" /> Active Blocked IPs
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">Active temporary and permanent bans.</p>
            </div>
            {blockedIps.length === 0 ? (
              <div className="p-8">
                <EmptyState
                  title="No blocked IPs"
                  description="Use the action buttons in the Event Log or Top Attacking IPs list to block IP addresses."
                />
              </div>
            ) : (
              <div className="divide-y divide-[#1F2937]">
                {blockedIps.map((b, idx) => (
                  <div key={idx} className="px-5 py-3.5 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-gray-200">{b.ip_address}</span>
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${
                          b.block_type === "permanent"
                            ? "bg-red-500/15 text-red-400"
                            : "bg-yellow-500/15 text-yellow-400"
                        }`}>
                          {b.block_type === "permanent" ? "PERM" : "TEMP"}
                        </span>
                      </div>
                      <p className="text-[10px] text-gray-500 mt-0.5 truncate">{b.reason || "No reason given"}</p>
                      <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-600">
                        <span>By: {b.blocked_by}</span>
                        {b.expires_at && (
                          <span className="flex items-center gap-0.5">
                            <Clock size={9} /> expires {relativeTime(b.expires_at)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => performUnblock(b.ip_address)}
                        className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#1F2937] text-[10px] text-gray-400 hover:text-green-400 hover:border-green-500/40 transition-all font-semibold"
                      >
                        <Unlock size={10} />
                        Unblock
                      </button>
                      <button
                        onClick={() => {
                          const matchingEvent = events.find(e => e.ip_address === b.ip_address) || {
                            ip_address: b.ip_address,
                            country: "India",
                            created_at: b.created_at,
                            event_type: "suspicious_activity",
                            severity: "high",
                            payload: b.reason || "Banned IP record details.",
                            action_taken: "blocked",
                            blocked: true,
                          };
                          setActiveEvent(matchingEvent);
                        }}
                        className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-[#1F2937] text-[10px] text-gray-400 hover:text-indigo-400 hover:border-indigo-500/40 transition-all font-semibold"
                      >
                        View
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Top Attacking IPs */}
          <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden">
            <div className="p-5 border-b border-[#1F2937]">
              <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                <Globe size={13} className="text-orange-400" /> Top Attacking IPs
              </h3>
              <p className="text-xs text-gray-500 mt-0.5">IPs with the most security violations.</p>
            </div>
            {topIps.length === 0 ? (
              <div className="p-8">
                <EmptyState title="No IP data" description="IP-based events haven't been recorded yet." />
              </div>
            ) : (
              <div className="divide-y divide-[#1F2937]">
                {topIps.slice(0, 10).map((ip, idx) => (
                  <div key={idx} className="px-5 py-3.5 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-xs text-gray-200">{ip.ip_address}</span>
                        {ip.is_blocked && (
                          <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-500/15 text-red-400 font-bold">BLOCKED</span>
                        )}
                      </div>
                      <p className="text-[10px] text-gray-500 mt-0.5">
                        {ip.attack_count} events · {ip.blocked_count} blocked · last {relativeTime(ip.last_seen)}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {!ip.is_blocked ? (
                        <>
                          <button
                            onClick={() => performBlock(ip.ip_address, true)}
                            className="text-[10px] bg-red-500/10 text-red-400 hover:bg-red-500/25 border border-red-500/30 px-2.5 py-1.5 rounded transition-all font-semibold"
                          >
                            Block
                          </button>
                          <button
                            onClick={() => performBlock(ip.ip_address, false)}
                            className="text-[10px] bg-yellow-500/10 text-yellow-400 hover:bg-yellow-500/25 border border-yellow-500/30 px-2.5 py-1.5 rounded transition-all font-semibold"
                          >
                            Temp Ban
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => performUnblock(ip.ip_address)}
                          className="text-[10px] bg-green-500/10 text-green-400 hover:bg-green-500/25 border border-green-500/30 px-2.5 py-1.5 rounded transition-all font-semibold"
                        >
                          Unblock
                        </button>
                      )}
                      <button
                        onClick={() => {
                          const matchingEvent = events.find(e => e.ip_address === ip.ip_address) || {
                            ip_address: ip.ip_address,
                            country: "India",
                            created_at: ip.last_seen,
                            event_type: "suspicious_activity",
                            severity: "high",
                            payload: `IP resolved with ${ip.attack_count} total events recorded.`,
                            action_taken: ip.is_blocked ? "blocked" : "logged",
                            blocked: ip.is_blocked,
                          };
                          setActiveEvent(matchingEvent);
                        }}
                        className="text-[10px] bg-indigo-500/10 text-indigo-400 hover:bg-indigo-500/25 border border-indigo-500/30 px-2.5 py-1.5 rounded transition-all font-semibold"
                      >
                        View
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* View Event Modal */}
      {activeEvent && (
        <ViewEventModal
          event={activeEvent}
          onClose={() => setActiveEvent(null)}
        />
      )}
    </div>
  );
}
