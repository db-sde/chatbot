import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  Clock,
  ChevronRight,
} from "lucide-react";
import { api } from "../services/api";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Conversations() {
  const navigate = useNavigate();

  const [sessions, setSessions] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [errorList, setErrorList] = useState(null);

  // Filters State
  const [searchQuery, setSearchQuery] = useState("");
  const [hasLeadFilter, setHasLeadFilter] = useState("");
  const [hasUnansweredFilter, setHasUnansweredFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoadingList(true);
      setErrorList(null);
      try {
        const filters = {
          date_from: dateFrom || null,
          date_to: dateTo || null,
          has_lead: hasLeadFilter === "true" ? true : hasLeadFilter === "false" ? false : null,
          has_unanswered: hasUnansweredFilter === "true" ? true : hasUnansweredFilter === "false" ? false : null,
        };
        const data = await api.getConversations(filters);
        if (cancelled) return;
        setSessions(data || []);
      } catch (err) {
        if (cancelled) return;
        setErrorList(err.message || "Failed to load session list.");
      } finally {
        if (!cancelled) {
          setLoadingList(false);
        }
      }
    }
    run();
    return () => { cancelled = true; };
  }, [hasLeadFilter, hasUnansweredFilter, dateFrom, dateTo, refresh]);

  // Client side search filtering
  const filteredSessions = sessions.filter((s) => {
    const query = searchQuery.toLowerCase().trim();
    if (!query) return true;
    const matchId = s.id.toLowerCase().includes(query);
    const matchUni = s.page_university_slug && s.page_university_slug.toLowerCase().includes(query);
    const matchSummary = s.summary && s.summary.toLowerCase().includes(query);
    const matchName = s.lead_name && s.lead_name.toLowerCase().includes(query);
    const matchPhone = s.lead_phone && s.lead_phone.toLowerCase().includes(query);
    const matchEmail = s.lead_email && s.lead_email.toLowerCase().includes(query);
    return matchId || matchUni || matchSummary || matchName || matchPhone || matchEmail;
  });

  const selectSession = (id) => {
    navigate(`/admin/conversations/${id}`);
  };

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col gap-6 overflow-hidden">
      <div className="w-full flex flex-col bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden shrink-0 h-full">
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
            <div className="p-4"><ErrorState title="List failed" description={errorList} retry={() => setRefresh((r) => r + 1)} /></div>
          ) : filteredSessions.length === 0 ? (
            <div className="p-4"><EmptyState title="No matching sessions" description="Try adjusting search or filter attributes." /></div>
          ) : (
            filteredSessions.map((session) => {
              const formattedTime = new Date(session.last_active_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              return (
                <div
                  key={session.id}
                  onClick={() => selectSession(session.id)}
                  className="p-4 cursor-pointer transition-all flex justify-between items-start text-left hover:bg-[#1C2333]/50"
                >
                  <div className="min-w-0 flex-1 pr-2">
                    <div className="flex flex-col mb-1.5">
                      <div className="flex items-center space-x-2">
                        <span className="text-xs font-bold text-gray-200 truncate">
                          {session.lead_name || `${session.id.substring(0, 8)}...`}
                        </span>
                        {session.page_university_slug && (
                          <span className="text-[9px] bg-blue-950 text-blue-400 border border-blue-900/50 px-1.5 py-0.5 rounded uppercase font-bold shrink-0">
                            {session.page_university_slug}
                          </span>
                        )}
                      </div>
                      {session.lead_name && (
                        <span className="text-[9px] font-mono text-gray-500 mt-0.5">
                          Session: {session.id.substring(0, 8)}...
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
                      {session.ip_address && (
                        <>
                          <span className="text-[9px] text-gray-500 font-bold">•</span>
                          <span className="text-[9px] font-mono text-emerald-500 font-semibold">
                            {session.ip_address}
                          </span>
                        </>
                      )}
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
    </div>
  );
}
