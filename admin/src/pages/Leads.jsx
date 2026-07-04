import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Search,
  MessageSquare,
  ChevronLeft,
  ChevronRight,
  ArrowUpDown,
  Mail,
  Phone,
  Bookmark
} from "lucide-react";
import { api } from "../services/api";
import { Badge, LoadingState, ErrorState, EmptyState } from "../components/Common";

export default function Leads() {
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Search & Pagination State
  const [searchQuery, setSearchQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [sortField, setSortField] = useState("created_at");
  const [sortDirection, setSortDirection] = useState("desc");
  const itemsPerPage = 10;

  const fetchLeads = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getLeads(200, 0); // Fetch top 200 leads for sorting/pagination client side
      setLeads(data || []);
    } catch (err) {
      setError(err.message || "Failed to load lead generation list.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLeads();
  }, []);

  const handleSort = (field) => {
    const isAsc = sortField === field && sortDirection === "asc";
    setSortDirection(isAsc ? "desc" : "asc");
    setSortField(field);
  };

  // Filter & Search
  const filteredLeads = leads.filter((lead) => {
    const query = searchQuery.toLowerCase();
    if (!query) return true;
    const nameMatch = lead.name && lead.name.toLowerCase().includes(query);
    const phoneMatch = lead.phone && lead.phone.toLowerCase().includes(query);
    const emailMatch = lead.email && lead.email.toLowerCase().includes(query);
    const courseMatch = lead.course_interest && lead.course_interest.toLowerCase().includes(query);
    const sessionMatch = lead.session_id && lead.session_id.toLowerCase().includes(query);
    return nameMatch || phoneMatch || emailMatch || courseMatch || sessionMatch;
  });

  // Sorting
  const sortedLeads = [...filteredLeads].sort((a, b) => {
    let valA = a[sortField];
    let valB = b[sortField];

    if (!valA) return 1;
    if (!valB) return -1;

    if (typeof valA === "string") {
      valA = valA.toLowerCase();
      valB = valB.toLowerCase();
    }

    if (valA < valB) return sortDirection === "asc" ? -1 : 1;
    if (valA > valB) return sortDirection === "asc" ? 1 : -1;
    return 0;
  });

  // Pagination
  const totalPages = Math.ceil(sortedLeads.length / itemsPerPage);
  const indexOfLastItem = currentPage * itemsPerPage;
  const indexOfFirstItem = indexOfLastItem - itemsPerPage;
  const currentLeads = sortedLeads.slice(indexOfFirstItem, indexOfLastItem);

  if (loading) return <LoadingState message="Connecting to CRM/leads datastore..." />;
  if (error) return <ErrorState title="CRM synchronisation failed" description={error} retry={fetchLeads} />;

  return (
    <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden shadow-sm">
      {/* Header bar */}
      <div className="p-6 border-b border-[#1F2937] flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-[#0E131F]/50">
        <div>
          <h2 className="text-base font-bold text-gray-200">Captured Leads Directory</h2>
          <p className="text-xs text-gray-500 mt-0.5">Profiles extracted from form submissions across active websites.</p>
        </div>
        <div className="relative w-full md:w-72">
          <Search className="absolute left-3 top-2.5 text-gray-500" size={16} />
          <input
            type="text"
            placeholder="Search leads by name, email, interest..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setCurrentPage(1);
            }}
            className="w-full pl-9 pr-4 py-2 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Table grid */}
      <div className="overflow-x-auto">
        {currentLeads.length === 0 ? (
          <div className="p-8">
            <EmptyState title="No leads recorded" description="Try modifying your search criteria or checking CRM config." />
          </div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[#1F2937] bg-[#0E131F]/20 text-[10px] uppercase font-bold tracking-wider text-gray-400">
                <th className="px-6 py-4 cursor-pointer" onClick={() => handleSort("name")}>
                  <div className="flex items-center space-x-1.5">
                    <span>Name</span>
                    <ArrowUpDown size={12} />
                  </div>
                </th>
                <th className="px-6 py-4 cursor-pointer" onClick={() => handleSort("phone")}>
                  <div className="flex items-center space-x-1.5">
                    <span>Phone</span>
                    <ArrowUpDown size={12} />
                  </div>
                </th>
                <th className="px-6 py-4 cursor-pointer" onClick={() => handleSort("email")}>
                  <div className="flex items-center space-x-1.5">
                    <span>Email</span>
                    <ArrowUpDown size={12} />
                  </div>
                </th>
                <th className="px-6 py-4 cursor-pointer" onClick={() => handleSort("course_interest")}>
                  <div className="flex items-center space-x-1.5">
                    <span>Interest</span>
                    <ArrowUpDown size={12} />
                  </div>
                </th>
                <th className="px-6 py-4 cursor-pointer" onClick={() => handleSort("created_at")}>
                  <div className="flex items-center space-x-1.5">
                    <span>Captured At</span>
                    <ArrowUpDown size={12} />
                  </div>
                </th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1F2937] text-xs">
              {currentLeads.map((lead) => (
                <tr key={lead.id} className="hover:bg-[#1C2333]/55 transition-all text-gray-300">
                  <td className="px-6 py-4 font-bold text-gray-100">{lead.name}</td>
                  <td className="px-6 py-4 font-medium">
                    <span className="flex items-center space-x-1.5">
                      <Phone size={12} className="text-gray-500" />
                      <span>{lead.phone}</span>
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {lead.email ? (
                      <span className="flex items-center space-x-1.5">
                        <Mail size={12} className="text-gray-500" />
                        <span>{lead.email}</span>
                      </span>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-6 py-4 font-medium">
                    {lead.course_interest ? (
                      <Badge variant="primary">{lead.course_interest}</Badge>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-gray-500">
                    {new Date(lead.created_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}
                  </td>
                  <td className="px-6 py-4 text-right">
                    {lead.session_id ? (
                      <Link
                        to={`/admin/conversations/${lead.session_id}`}
                        className="inline-flex items-center space-x-1.5 text-xs text-blue-400 hover:text-blue-300 font-semibold transition-colors"
                      >
                        <MessageSquare size={13} />
                        <span>Chat Link</span>
                      </Link>
                    ) : (
                      <span className="text-[10px] text-gray-600 font-bold">NO SESSION</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Footer */}
      {totalPages > 1 && (
        <div className="p-4 border-t border-[#1F2937] flex items-center justify-between bg-[#0E131F]/30">
          <div className="text-[10px] font-semibold text-gray-500">
            SHOWING {indexOfFirstItem + 1} - {Math.min(indexOfLastItem, sortedLeads.length)} OF {sortedLeads.length} LEADS
          </div>
          <div className="flex space-x-2">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="p-1.5 bg-[#1F2937] border border-[#2D3748] rounded text-gray-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="p-1.5 bg-[#1F2937] border border-[#2D3748] rounded text-gray-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
