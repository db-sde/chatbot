import { useEffect, useState } from "react";
import {
  HelpCircle,
  HelpCircle as QuestionIcon,
  ChevronDown,
  ChevronUp,
  School,
  Bookmark
} from "lucide-react";
import { api } from "../services/api";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Unanswered() {
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedGroupId, setExpandedGroupId] = useState(null);

  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getUnanswered();
        if (cancelled) return;
        setGroups(data || []);
      } catch (err) {
        if (cancelled) return;
        setError(err.message || "Failed to load unanswered question log.");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    run();
    return () => { cancelled = true; };
  }, [refresh]);

  const toggleGroup = (id) => {
    if (expandedGroupId === id) {
      setExpandedGroupId(null);
    } else {
      setExpandedGroupId(id);
    }
  };

  if (loading) return <LoadingState message="Scanning unanswered database for knowledge gaps..." />;
  if (error) return <ErrorState title="Unanswered scan failed" description={error} retry={() => setRefresh((r) => r + 1)} />;

  return (
    <div className="space-y-6 text-left">
      <div className="flex justify-between items-start">
        <div>
          <h2 className="text-base font-bold text-gray-200">Knowledge Gap Discovery</h2>
          <p className="text-xs text-gray-500 mt-0.5">Identify topics where the AI advisor failed to retrieve data from DegreeBaba catalogs.</p>
        </div>
        <Badge variant="primary">{groups.length} active gaps</Badge>
      </div>

      {groups.length === 0 ? (
        <EmptyState
          title="Zero Gaps Detected!"
          description="Every query has successfully triggered catalog retrievals. The advisor database is complete."
          icon={HelpCircle}
        />
      ) : (
        <div className="space-y-4">
          {groups.map((group, idx) => {
            const isExpanded = expandedGroupId === idx;
            const uniLabel = group.university_slug ? group.university_slug.toUpperCase() : "GENERAL SITE";
            const courseLabel = group.course_slug ? group.course_slug.toUpperCase() : "ANY COURSE";
            
            return (
              <div
                key={idx}
                className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden hover:border-[#2D3748] transition-all"
              >
                {/* Header section */}
                <div
                  onClick={() => toggleGroup(idx)}
                  className="p-4 md:p-6 flex items-center justify-between cursor-pointer bg-[#0E131F]/30"
                >
                  <div className="flex items-center space-x-4 min-w-0">
                    <div className="h-10 w-10 bg-amber-950/20 text-amber-500 rounded-lg flex items-center justify-center shrink-0 border border-amber-900/30">
                      <QuestionIcon size={20} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        <span className="text-xs bg-[#1F2937] text-gray-300 font-semibold px-2 py-0.5 rounded flex items-center space-x-1">
                          <School size={10} className="text-blue-500" />
                          <span>{uniLabel}</span>
                        </span>
                        {group.course_slug && (
                          <span className="text-[10px] bg-[#1F2937] text-gray-400 font-semibold px-2 py-0.5 rounded flex items-center space-x-1">
                            <Bookmark size={10} className="text-purple-500" />
                            <span>{courseLabel}</span>
                          </span>
                        )}
                      </div>
                      <p className="text-[10px] text-gray-500 font-medium truncate max-w-[300px] md:max-w-[500px]">
                        Last: "{group.examples?.[0] || "No text sample"}"
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center space-x-4 shrink-0">
                    <div className="text-right">
                      <span className="block text-lg font-bold text-amber-400">{group.count}</span>
                      <span className="text-[9px] text-gray-500 uppercase tracking-wider font-bold">occurrences</span>
                    </div>
                    {isExpanded ? <ChevronUp size={18} className="text-gray-500" /> : <ChevronDown size={18} className="text-gray-500" />}
                  </div>
                </div>

                {/* Expanded question examples section */}
                {isExpanded && (
                  <div className="border-t border-[#1F2937] p-6 bg-[#0E131F]/20 space-y-4">
                    <h4 className="text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Recent Question Samples:</h4>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {group.examples?.map((sample, sIdx) => (
                        <div
                          key={sIdx}
                          className="bg-[#111827] border border-[#1F2937] p-3 rounded-lg text-xs font-medium text-gray-300 flex items-start space-x-2"
                        >
                          <span className="text-amber-500/80 select-none font-bold">Q.</span>
                          <span className="italic">"{sample}"</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
