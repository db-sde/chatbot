import React, { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import {
  Search,
  Filter,
  Calendar,
  UserCheck,
  HelpCircle,
  Clock,
  ChevronRight,
  MessageSquare,
  School,
  ExternalLink,
  Code
} from "lucide-react";
import { api } from "../services/api";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Conversations() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  const [sessions, setSessions] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [errorList, setErrorList] = useState(null);

  // Selected Session Details
  const [activeSession, setActiveSession] = useState(null);
  const [loadingActive, setLoadingActive] = useState(false);
  const [errorActive, setErrorActive] = useState(null);

  // Filters State
  const [searchQuery, setSearchQuery] = useState("");
  const [universityFilter, setUniversityFilter] = useState("");
  const [hasLeadFilter, setHasLeadFilter] = useState("");
  const [hasUnansweredFilter, setHasUnansweredFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const fetchSessionList = async () => {
    setLoadingList(true);
    setErrorList(null);
    try {
      const filters = {
        university: universityFilter || null,
        date_from: dateFrom || null,
        date_to: dateTo || null,
        has_lead: hasLeadFilter === "true" ? true : hasLeadFilter === "false" ? false : null,
        has_unanswered: hasUnansweredFilter === "true" ? true : hasUnansweredFilter === "false" ? false : null,
      };
      const data = await api.getConversations(filters);
      setSessions(data || []);
    } catch (err) {
      setErrorList(err.message || "Failed to load session list.");
    } finally {
      setLoadingList(false);
    }
  };

  const fetchActiveSession = async (id) => {
    setLoadingActive(true);
    setErrorActive(null);
    try {
      const data = await api.getConversation(id);
      setActiveSession(data || null);
    } catch (err) {
      setErrorActive(err.message || "Failed to load conversation messages.");
    } finally {
      setLoadingActive(false);
    }
  };

  useEffect(() => {
    fetchSessionList();
  }, [universityFilter, hasLeadFilter, hasUnansweredFilter, dateFrom, dateTo]);

  useEffect(() => {
    if (sessionId) {
      fetchActiveSession(sessionId);
    } else {
      setActiveSession(null);
    }
  }, [sessionId]);

  // Client side search filtering
  const filteredSessions = sessions.filter((s) => {
    const query = searchQuery.toLowerCase().strip ? searchQuery.toLowerCase().trim() : searchQuery.toLowerCase();
    if (!query) return true;
    const matchId = s.id.toLowerCase().includes(query);
    const matchUni = s.page_university_slug && s.page_university_slug.toLowerCase().includes(query);
    const matchSummary = s.summary && s.summary.toLowerCase().includes(query);
    return matchId || matchUni || matchSummary;
  });

  const selectSession = (id) => {
    navigate(`/admin/conversations/${id}`);
  };

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col lg:flex-row gap-6 overflow-hidden">
      {/* Left Panel: Search, Filters & Session List */}
      <div className="w-full lg:w-96 flex flex-col bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden shrink-0 h-1/2 lg:h-full">
        {/* Search & Filter Inputs */}
        <div className="p-4 border-b border-[#1F2937] space-y-3 bg-[#0E131F]/50">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 text-gray-500" size={16} />
            <input
              type="text"
              placeholder="Search Session ID, slug, text..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <select
              value={hasLeadFilter}
              onChange={(e) => setHasLeadFilter(e.target.value)}
              className="bg-[#1F2937] border border-[#2D3748] rounded-lg text-[10px] py-1.5 px-2 text-gray-300 focus:outline-none"
            >
              <option value="">Lead Captured</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
            <select
              value={hasUnansweredFilter}
              onChange={(e) => setHasUnansweredFilter(e.target.value)}
              className="bg-[#1F2937] border border-[#2D3748] rounded-lg text-[10px] py-1.5 px-2 text-gray-300 focus:outline-none"
            >
              <option value="">Has Unanswered</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          </div>

          <div className="grid grid-cols-2 gap-2 items-center">
            <div className="relative">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                placeholder="From"
                className="w-full bg-[#1F2937] border border-[#2D3748] rounded-lg text-[10px] py-1 px-2 text-gray-300 focus:outline-none"
              />
            </div>
            <div className="relative">
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                placeholder="To"
                className="w-full bg-[#1F2937] border border-[#2D3748] rounded-lg text-[10px] py-1 px-2 text-gray-300 focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Sessions list */}
        <div className="flex-1 overflow-y-auto divide-y divide-[#1F2937]">
          {loadingList ? (
            <div className="py-8"><LoadingState message="Loading sessions..." /></div>
          ) : errorList ? (
            <div className="p-4"><ErrorState title="List failed" description={errorList} retry={fetchSessionList} /></div>
          ) : filteredSessions.length === 0 ? (
            <div className="p-4"><EmptyState title="No matching sessions" description="Try adjusting search or filter attributes." /></div>
          ) : (
            filteredSessions.map((session) => {
              const isSelected = session.id === sessionId;
              const formattedTime = new Date(session.last_active_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              return (
                <div
                  key={session.id}
                  onClick={() => selectSession(session.id)}
                  className={`
                    p-4 cursor-pointer transition-all flex justify-between items-start text-left
                    ${isSelected ? "bg-blue-950/20 border-l-2 border-blue-500" : "hover:bg-[#1C2333]/50"}
                  `}
                >
                  <div className="min-w-0 flex-1 pr-2">
                    <div className="flex items-center space-x-2 mb-1.5">
                      <span className="text-[10px] font-mono text-gray-400 font-semibold truncate max-w-[120px]">
                        {session.id.substring(0, 8)}...
                      </span>
                      {session.page_university_slug && (
                        <span className="text-[9px] bg-blue-950 text-blue-400 border border-blue-900/50 px-1.5 py-0.5 rounded uppercase font-bold shrink-0">
                          {session.page_university_slug}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-300 truncate font-medium">
                      {session.summary || "Conversation Turn..."}
                    </p>
                    <div className="flex items-center space-x-2 mt-2">
                      <span className="text-[9px] text-gray-500 flex items-center space-x-1 font-medium">
                        <Clock size={10} />
                        <span>{formattedTime}</span>
                      </span>
                      <span className="text-[9px] text-gray-500 font-bold">•</span>
                      <span className="text-[9px] text-gray-500 font-medium">
                        {session.message_count} msgs
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-col items-end space-y-1.5 shrink-0">
                    {session.has_lead && (
                      <Badge variant="success">LEAD</Badge>
                    )}
                    {session.has_unanswered && (
                      <Badge variant="warning">GAP</Badge>
                    )}
                    <ChevronRight size={14} className="text-gray-600 mt-1" />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Right Panel: Selected Conversation preview timeline */}
      <div className="flex-1 bg-[#111827] border border-[#1F2937] rounded-xl flex flex-col overflow-hidden h-1/2 lg:h-full">
        {loadingActive ? (
          <div className="flex-1 flex items-center justify-center"><LoadingState message="Fetching chat history..." /></div>
        ) : errorActive ? (
          <div className="p-8"><ErrorState title="History load failed" description={errorActive} /></div>
        ) : !activeSession ? (
          <div className="flex-1 flex items-center justify-center">
            <EmptyState
              title="No Conversation Selected"
              description="Click a session item on the left panel to preview transcript timeline."
              icon={MessageSquare}
            />
          </div>
        ) : (
          <>
            {/* Session Metadata Header */}
            <div className="p-4 md:p-6 border-b border-[#1F2937] bg-[#0E131F]/50 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
              <div>
                <div className="flex items-center space-x-2 mb-1">
                  <h3 className="font-bold text-sm text-gray-200">Session Transcript</h3>
                  <span className="text-xs font-mono text-gray-500 font-medium">({activeSession.session?.id})</span>
                </div>
                <div className="flex flex-wrap gap-2 items-center text-[10px] text-gray-400">
                  <span className="flex items-center space-x-1">
                    <School size={12} className="text-blue-500" />
                    <span>Site: <strong className="text-gray-300">{activeSession.session?.site_id}</strong></span>
                  </span>
                  {activeSession.session?.page_university_slug && (
                    <>
                      <span>•</span>
                      <span>Page: <strong className="text-gray-300 uppercase">{activeSession.session?.page_university_slug}</strong></span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex gap-2">
                {activeSession.leads?.length > 0 && (
                  <Badge variant="success">Lead Profile Active</Badge>
                )}
                <Link
                  to={`/admin/conversations/${activeSession.session?.id}`}
                  className="p-2 bg-[#1F2937] hover:bg-[#2D3748] border border-[#2D3748] rounded-lg text-gray-300 transition-all text-xs flex items-center gap-1.5"
                >
                  <ExternalLink size={12} />
                  <span>Detail View</span>
                </Link>
              </div>
            </div>

            {/* Chat Timeline (GPT Rendering style) */}
            <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 bg-[#0E131F]/20">
              {activeSession.messages?.length === 0 ? (
                <EmptyState title="No messages recorded" description="This session contains zero transcripts." />
              ) : (
                activeSession.messages?.map((msg, index) => {
                  const isUser = msg.role === "user";
                  let toolCalls = msg.tool_calls;
                  if (typeof toolCalls === "string") {
                    try {
                      toolCalls = JSON.parse(toolCalls);
                    } catch (_) {
                      toolCalls = [];
                    }
                  }

                  return (
                    <div key={index} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                      <div className={`
                        max-w-[85%] rounded-2xl p-4 text-left shadow-sm border
                        ${isUser
                          ? "bg-blue-600 text-white border-blue-500"
                          : "bg-[#111827] text-gray-200 border-[#1F2937]"
                        }
                      `}>
                        <div className="flex justify-between items-center w-full min-w-[140px] mb-1 text-[9px] font-semibold tracking-wider opacity-60">
                          <span>{isUser ? "STUDENT" : "ADVISOR"}</span>
                          <span className="ml-4">{new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                        </div>
                        <p className="text-xs whitespace-pre-wrap leading-relaxed">{msg.content}</p>

                        {/* Tool Calls logs */}
                        {toolCalls && Array.isArray(toolCalls) && toolCalls.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-[#1F2937]/50 space-y-2">
                            <span className="text-[9px] font-bold text-gray-400 flex items-center gap-1">
                              <Code size={10} className="text-blue-400" />
                              <span>TOOL EVENTS EXECUTED</span>
                            </span>
                            {toolCalls.map((tc, tcIdx) => (
                              <div key={tcIdx} className="bg-[#1C2433] rounded p-2.5 border border-[#2D3748] space-y-1.5 font-mono text-[9px]">
                                <div className="flex justify-between text-blue-400 font-bold">
                                  <span>{tc.name || "ToolCall"}</span>
                                  <span className="text-gray-500 text-[8px] font-normal">
                                    {tc.status || "success"}
                                  </span>
                                </div>
                                <div className="text-gray-300 break-all bg-[#111827] p-1.5 rounded border border-gray-800/40">
                                  <span className="text-gray-500 font-bold">Args:</span> {JSON.stringify(tc.args)}
                                </div>
                                {tc.result_summary && (
                                  <div className="text-gray-300 break-all bg-[#111827] p-1.5 rounded border border-gray-800/20 whitespace-pre-wrap">
                                    <span className="text-gray-500 font-bold">Result:</span> {tc.result_summary}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
