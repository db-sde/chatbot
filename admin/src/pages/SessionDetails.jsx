import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  Calendar,
  MessageSquare,
  Users,
  Code,
  Terminal,
  Server,
  Play,
  ChevronDown,
  ChevronUp,
  Activity
} from "lucide-react";
import { api } from "../services/api";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function SessionDetails() {
  const { sessionId } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedTools, setExpandedTools] = useState({});

  const toggleTool = (idx) => {
    setExpandedTools((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        const result = await api.getConversation(sessionId);
        if (cancelled) return;
        setData(result || null);
      } catch (err) {
        if (cancelled) return;
        setError(err.message || "Failed to load session transaction.");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    run();
    return () => { cancelled = true; };
  }, [sessionId, refresh]);

  if (loading) return <LoadingState message="Fetching session transaction details..." />;
  if (error) return <ErrorState title="Session query failed" description={error} retry={() => setRefresh((r) => r + 1)} />;
  if (!data) return <EmptyState title="Session not found" description="No details are active for this Session ID." />;

  const session = data.session || {};
  const messages = data.messages || [];
  const leads = data.leads || [];

  // Extract all tool calls from the chat log for the execution pipeline view
  const allToolCalls = [];
  messages.forEach((msg) => {
    let toolCalls = msg.tool_calls;
    if (typeof toolCalls === "string") {
      try {
        toolCalls = JSON.parse(toolCalls);
      } catch {
        toolCalls = [];
      }
    }
    if (toolCalls && Array.isArray(toolCalls)) {
      toolCalls.forEach((tc) => {
        allToolCalls.push({
          ...tc,
          timestamp: msg.created_at,
        });
      });
    }
  });

  // Compute session metrics dynamically from messages
  const assistantMessages = messages.filter((m) => m.role === "assistant");
  const totalMessagesCount = messages.length;
  
  // Total Tokens
  const totalTokensSum = assistantMessages.reduce((sum, m) => sum + (m.total_tokens || 0), 0);
  const inputTokensSum = assistantMessages.reduce((sum, m) => sum + (m.input_tokens || 0), 0);
  const outputTokensSum = assistantMessages.reduce((sum, m) => sum + (m.output_tokens || 0), 0);
  
  // Total Cost
  const totalCostSum = assistantMessages.reduce((sum, m) => sum + (parseFloat(m.estimated_cost_usd) || 0.0), 0.0);
  
  // Averages
  const timedMessages = assistantMessages.filter((m) => m.response_time_ms !== undefined && m.response_time_ms !== null);
  const avgResponseTimeSec = timedMessages.length > 0
    ? (timedMessages.reduce((sum, m) => sum + m.response_time_ms, 0) / timedMessages.length / 1000).toFixed(2)
    : "—";
    
  const ttftMessages = assistantMessages.filter((m) => m.ttft_ms !== undefined && m.ttft_ms !== null);
  const avgTtftMs = ttftMessages.length > 0
    ? (ttftMessages.reduce((sum, m) => sum + m.ttft_ms, 0) / ttftMessages.length).toFixed(0)
    : "—";

  return (
    <div className="space-y-8">
      {/* Back Button & Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <Link
          to="/admin/conversations"
          className="flex items-center space-x-2 text-xs text-gray-400 hover:text-white transition-colors"
        >
          <ArrowLeft size={14} />
          <span>Back to conversations</span>
        </Link>
        <div className="flex gap-2">
          {leads.length > 0 && <Badge variant="success">Lead Captured</Badge>}
          {session.page_university_slug && (
            <Badge variant="primary">Page Context: {session.page_university_slug.toUpperCase()}</Badge>
          )}
        </div>
      </div>

      {/* Prominent Lead Profile Banner */}
      {leads.length > 0 && (
        <div className="bg-gradient-to-r from-emerald-950/40 to-blue-950/20 border border-emerald-500/30 rounded-xl p-6 flex flex-col justify-between gap-4 shadow-[0_0_15px_rgba(16,185,129,0.05)]">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div className="space-y-1">
              <span className="text-[10px] text-emerald-400 font-bold uppercase tracking-wider">Acquired Lead Profile</span>
              <h2 className="text-xl font-extrabold text-gray-100">{leads[0].name}</h2>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-gray-400 pt-1">
                <span className="font-semibold">Phone: <strong className="text-gray-200 font-mono">{leads[0].phone}</strong></span>
                <span className="text-gray-600 font-bold">•</span>
                <span>Email: <strong className="text-gray-200 font-mono">{leads[0].email || "—"}</strong></span>
              </div>
            </div>
            
            <div className="flex flex-col items-start md:items-end text-left md:text-right gap-1 shrink-0">
              <span className="text-[10px] text-gray-500 uppercase tracking-wider">Trigger Mechanism</span>
              <Badge variant={leads[0].trigger_reason === "LLM Intent" ? "success" : "primary"}>
                {leads[0].trigger_reason || "Score Engine"}
              </Badge>
              <span className="text-[9px] text-gray-500 font-mono mt-1">
                Acquired: {new Date(leads[0].created_at).toLocaleString()}
              </span>
            </div>
          </div>
          
          {session.lead_intent_detected && (
            <div className="pt-3 border-t border-emerald-500/10 text-xs text-gray-400 flex flex-wrap gap-x-6 gap-y-1.5 font-mono">
              <span>Trigger Reason: <strong className="text-emerald-400 font-sans">Lead Intent Detected</strong></span>
              <span>Intent Type: <strong className="text-gray-200">{session.lead_intent_type || "—"}</strong></span>
              <span>Confidence: <strong className="text-gray-200">{session.lead_intent_confidence || "—"}</strong></span>
              {session.lead_intent_reasoning && (
                <div className="w-full text-[11px] text-gray-500 font-sans italic mt-1">
                  Reasoning: "{session.lead_intent_reasoning}"
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Info Cards Row */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* Session Metadata Card */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
          <div className="flex items-center space-x-2">
            <Server size={16} className="text-blue-500" />
            <h3 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Session Metadata</h3>
          </div>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-500">Session ID</span>
              <span className="font-mono text-gray-300 font-semibold">{session.id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Site ID</span>
              <span className="text-gray-300 font-medium">{session.site_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Messages Count</span>
              <span className="text-gray-300 font-semibold">{session.message_count}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">First Active</span>
              <span className="text-gray-300">{new Date(session.started_at).toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Last Active</span>
              <span className="text-gray-300">{new Date(session.last_active_at).toLocaleString()}</span>
            </div>
            <div className="border-t border-[#1F2937] pt-3 flex justify-between">
              <span className="text-gray-500">IP Address</span>
              <span className="font-mono text-emerald-400 font-medium">
                {session.ip_address || <span className="text-gray-600 italic">—</span>}
              </span>
            </div>
            <div className="flex justify-between items-start gap-2">
              <span className="text-gray-500 shrink-0">User Agent</span>
              <span className="font-mono text-gray-400 text-right break-all leading-relaxed">
                {session.user_agent || <span className="text-gray-600 italic">—</span>}
              </span>
            </div>
          </div>
        </div>

        {/* Context Profile Card */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
          <div className="flex items-center space-x-2">
            <Calendar size={16} className="text-blue-500" />
            <h3 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Page Context State</h3>
          </div>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-500">University Slug</span>
              <span className="font-mono text-gray-300">{session.page_university_slug || "None"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Conversational University</span>
              <span className="font-mono text-gray-300 text-blue-400 font-medium">
                {session.current_university_slug || "NULL / Empty"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Conversational Course</span>
              <span className="font-mono text-gray-300 text-purple-400 font-medium">
                {session.current_course_slug || "NULL / Empty"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Conversational Spec</span>
              <span className="font-mono text-gray-300 font-medium">
                {session.current_specialization_slug || "NULL / Empty"}
              </span>
            </div>
          </div>
        </div>

        {/* Lead Profile Capture Card */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
          <div className="flex items-center space-x-2">
            <Users size={16} className="text-blue-500" />
            <h3 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Lead Profile Capture</h3>
          </div>
          {leads.length === 0 ? (
            <div className="h-[90px] flex items-center justify-center border border-[#1F2937] border-dashed rounded-lg bg-[#0E131F]/30">
              <span className="text-xs text-gray-500">No leads captured in this transcript</span>
            </div>
          ) : (
            leads.map((lead, idx) => (
              <div key={idx} className="space-y-2 text-xs">
                <div className="flex justify-between">
                  <span className="text-gray-500">Student Name</span>
                  <span className="text-gray-200 font-bold">{lead.name}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Phone Number</span>
                  <span className="text-gray-200 font-medium">{lead.phone}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Email Address</span>
                  <span className="text-gray-300">{lead.email || "—"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Trigger Reason</span>
                  <Badge variant="primary">{lead.trigger_reason}</Badge>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Conversation Summary Card */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 space-y-4">
          <div className="flex items-center space-x-2">
            <Activity size={16} className="text-emerald-500" />
            <h3 className="text-xs font-bold text-gray-300 uppercase tracking-wider">Conversation Summary</h3>
          </div>
          <div className="space-y-3 text-xs">
            <div className="flex justify-between">
              <span className="text-gray-500">Total Messages</span>
              <span className="text-gray-300 font-semibold">{totalMessagesCount}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Total Tokens</span>
              <span className="text-gray-300 font-mono font-medium">
                {totalTokensSum.toLocaleString()} <span className="text-[10px] text-gray-500">({inputTokensSum} in / {outputTokensSum} out)</span>
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Avg Response Time</span>
              <span className="text-gray-300 font-mono font-semibold">{avgResponseTimeSec}s</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Avg TTFT</span>
              <span className="text-gray-300 font-mono font-semibold">{avgTtftMs}ms</span>
            </div>
            <div className="border-t border-[#1F2937]/60 pt-3 flex justify-between">
              <span className="text-gray-400 font-semibold">Total Cost</span>
              <span className="font-mono text-emerald-400 font-bold">${totalCostSum.toFixed(6)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Conversation & Tool Execution Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Side: ChatGPT Chat Timeline */}
        <div className="lg:col-span-2 bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col h-[670px]">
          <div className="flex items-center space-x-2 mb-4">
            <MessageSquare size={16} className="text-blue-500" />
            <h3 className="text-sm font-semibold text-gray-200">Conversation Timeline</h3>
          </div>
          <div className="flex-1 overflow-y-auto pr-2 space-y-6">
            {messages.map((msg, index) => {
              const isUser = msg.role === "user";
              return (
                <div key={index} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                  <div className={`
                    max-w-[90%] rounded-2xl p-4 text-left shadow-sm border
                    ${isUser
                      ? "bg-blue-600 text-white border-blue-500"
                      : "bg-[#0E131F]/80 text-gray-200 border-[#1F2937]"
                    }
                  `}>
                    <div className="flex justify-between items-center w-full min-w-[140px] mb-1 text-[9px] font-semibold tracking-wider opacity-60">
                      <span>{isUser ? "STUDENT" : "ADVISOR"}</span>
                      <span className="ml-4">{new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                    <p className="text-xs whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    {!isUser && (msg.model_name || msg.response_time_ms !== undefined) && (
                      <div className="mt-3 pt-2 border-t border-[#1F2937]/60 flex flex-wrap gap-x-4 gap-y-1.5 text-[9px] text-gray-500 font-mono">
                        {msg.model_name && (
                          <span>Model: <strong className="text-gray-400">{msg.model_name}</strong></span>
                        )}
                        {msg.response_time_ms !== undefined && msg.response_time_ms !== null && (
                          <span>Response: <strong className="text-gray-400">{(msg.response_time_ms / 1000).toFixed(2)}s</strong></span>
                        )}
                        {msg.ttft_ms !== undefined && msg.ttft_ms !== null && (
                          <span>TTFT: <strong className="text-gray-400">{msg.ttft_ms}ms</strong></span>
                        )}
                        {msg.total_tokens !== undefined && msg.total_tokens > 0 && (
                          <span>Tokens: <strong className="text-gray-400">{msg.total_tokens} ({msg.input_tokens} in / {msg.output_tokens} out)</strong></span>
                        )}
                        {msg.estimated_cost_usd !== undefined && msg.estimated_cost_usd !== null && (
                          <span>Cost: <strong className="text-emerald-400">${parseFloat(msg.estimated_cost_usd).toFixed(6)}</strong></span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Side: Tool Call Timeline */}
        <div className="bg-[#111827] border border-[#1F2937] rounded-xl p-6 flex flex-col h-[670px]">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-2">
              <Terminal size={16} className="text-blue-500" />
              <h3 className="text-sm font-semibold text-gray-200">Tool Calls Timeline</h3>
            </div>
            {allToolCalls.length > 0 && (
              <Badge variant="primary">{allToolCalls.length} executed</Badge>
            )}
          </div>
          {allToolCalls.length === 0 ? (
            <div className="py-16 text-center border border-[#1F2937] border-dashed rounded-xl bg-[#0E131F]/30 flex-1 flex flex-col justify-center items-center">
              <Code size={24} className="text-gray-600 mb-2" />
              <span className="text-xs text-gray-500 font-medium">No tools executed during this session</span>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto pr-2 space-y-6 relative before:absolute before:inset-y-0 before:left-3.5 before:w-0.5 before:bg-[#1F2937]">
              {allToolCalls.map((tc, idx) => {
                const isExpanded = !!expandedTools[idx];
                return (
                  <div key={idx} className="flex gap-4 relative">
                    <div className="h-7 w-7 rounded-full bg-blue-950/80 border border-blue-900/60 text-blue-400 flex items-center justify-center shrink-0 z-10">
                      <Play size={10} />
                    </div>
                    <div
                      onClick={() => toggleTool(idx)}
                      className={`
                        flex-1 bg-[#0E131F] border rounded-lg p-3.5 space-y-2 min-w-0 cursor-pointer select-none transition-all duration-150
                        ${isExpanded ? "border-[#2D3748] bg-[#0E131F]" : "border-[#1F2937] hover:border-[#2D3748] hover:bg-[#141A29]/40"}
                      `}
                    >
                      <div className="flex justify-between items-center w-full">
                        <span className="text-xs font-bold text-blue-400 font-mono break-all">{tc.name}</span>
                        <div className="flex items-center space-x-2 shrink-0 ml-2">
                          {tc.duration_ms !== undefined && tc.duration_ms !== null && (
                            <span className="text-[9px] font-mono text-gray-400 bg-gray-900 border border-gray-800 px-1 py-0.5 rounded">
                              {tc.duration_ms}ms
                            </span>
                          )}
                          {tc.status && (
                            <span className={`text-[9px] px-1 py-0.5 rounded uppercase font-bold shrink-0 ${
                              tc.status === "FAILURE" ? "bg-red-950/40 text-red-400 border border-red-900/50" : "bg-emerald-950/40 text-emerald-400 border border-emerald-900/50"
                            }`}>
                              {tc.status}
                            </span>
                          )}
                          <span className="text-[9px] text-gray-500">
                            {new Date(tc.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </span>
                          {isExpanded ? (
                            <ChevronUp size={14} className="text-gray-400" />
                          ) : (
                            <ChevronDown size={14} className="text-gray-400" />
                          )}
                        </div>
                      </div>

                      {/* Dropdown Section showing args and results */}
                      {isExpanded && (
                        <div className="space-y-2.5 pt-2.5 border-t border-[#1F2937] transition-all">
                          <div className="text-[10px] text-gray-300 font-mono bg-[#111827] p-2.5 rounded border border-gray-800 break-all">
                            <span className="text-gray-500 font-bold">Args:</span> {JSON.stringify(tc.args)}
                          </div>
                          {tc.result_summary && (
                            <div className="text-[10px] text-gray-300 font-mono bg-[#111827] p-2.5 rounded border border-gray-800 break-all whitespace-pre-wrap">
                              <span className="text-gray-500 font-bold">Result:</span> {tc.result_summary}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
