import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  MessageSquare,
  Users,
  BarChart3,
  Shield,
  HelpCircle,
  Settings,
  LogOut,
  Menu,
  X,
  UserCheck
} from "lucide-react";
import { api } from "../services/api";

const navigation = [
  { name: "Dashboard", href: "/admin", icon: LayoutDashboard },
  { name: "Conversations", href: "/admin/conversations", icon: MessageSquare },
  { name: "Leads", href: "/admin/leads", icon: Users },
  { name: "Analytics", href: "/admin/analytics", icon: BarChart3 },
  { name: "Security", href: "/admin/security", icon: Shield },
  { name: "Unanswered", href: "/admin/unanswered", icon: HelpCircle },
  { name: "Settings", href: "/admin/settings", icon: Settings },
];

export default function Layout({ children }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const handleLogout = () => {
    api.clearToken();
    navigate(0); // reload to trigger auth challenge
  };

  const getPageTitle = () => {
    if (location.pathname === "/admin") return "Dashboard Overview";
    const current = navigation.find((item) => item.href === location.pathname);
    if (current) return current.name;
    if (location.pathname.startsWith("/admin/conversations/")) return "Conversation Details";
    return "DegreeBaba AI Advisor";
  };

  return (
    <div className="min-h-screen bg-[#0B1020] text-gray-100 flex flex-col md:flex-row">
      {/* Mobile Header */}
      <header className="md:hidden bg-[#111827] border-b border-[#1F2937] px-4 py-3 flex justify-between items-center z-50">
        <div className="flex items-center space-x-2">
          <span className="font-bold text-lg text-blue-500 tracking-wider">DegreeBaba</span>
          <span className="text-xs bg-[#1F2937] px-2 py-0.5 rounded text-gray-400">Admin</span>
        </div>
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="text-gray-400 hover:text-white focus:outline-none"
        >
          {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      </header>

      {/* Sidebar - Desktop */}
      <aside className={`
        fixed inset-y-0 left-0 transform -translate-x-full transition-transform duration-200 ease-in-out z-40
        md:translate-x-0 md:static md:flex md:flex-col
        w-64 bg-[#111827] border-r border-[#1F2937] shrink-0
        ${mobileMenuOpen ? "translate-x-0" : "-translate-x-full"}
      `}>
        {/* Brand Header */}
        <div className="hidden md:flex items-center space-x-2 px-6 py-5 border-b border-[#1F2937]">
          <span className="font-extrabold text-xl text-blue-500 tracking-wider">DegreeBaba</span>
          <span className="text-[10px] bg-blue-900/50 text-blue-400 px-2 py-0.5 rounded font-medium border border-blue-800">
            ADMIN
          </span>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-4 py-6 space-y-1 overflow-y-auto">
          {navigation.map((item) => {
            const isActive =
              item.href === "/admin"
                ? location.pathname === "/admin"
                : location.pathname.startsWith(item.href);
            return (
              <Link
                key={item.name}
                to={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`
                  flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition-all duration-150
                  ${isActive
                    ? "bg-[#3B82F6] text-white shadow-lg shadow-blue-500/20"
                    : "text-gray-400 hover:bg-[#1F2937] hover:text-white"
                  }
                `}
              >
                <item.icon size={18} className={isActive ? "text-white" : "text-gray-400"} />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* Logout Section */}
        <div className="p-4 border-t border-[#1F2937] bg-[#0E131F]">
          <div className="flex items-center justify-between mb-4 px-2">
            <div className="flex items-center space-x-2 text-xs text-gray-500">
              <UserCheck size={14} className="text-emerald-500" />
              <span className="truncate max-w-[120px]">Authorized Session</span>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center space-x-2 px-4 py-2.5 rounded-lg text-xs font-semibold bg-red-950/40 text-red-400 border border-red-900/50 hover:bg-red-900/30 hover:text-red-300 transition-all duration-150"
          >
            <LogOut size={14} />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-x-hidden">
        {/* Top Navbar */}
        <header className="hidden md:flex bg-[#111827] border-b border-[#1F2937] h-16 items-center justify-between px-8 z-10 shrink-0">
          <h1 className="text-lg font-bold text-gray-100">{getPageTitle()}</h1>
          <div className="flex items-center space-x-4">
            <div className="flex items-center space-x-2 bg-[#1F2937] px-3 py-1.5 rounded-full text-xs text-gray-300 border border-[#2D3748]">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>API Gateway Connected</span>
            </div>
          </div>
        </header>

        {/* Sub Header for Mobile */}
        <div className="md:hidden bg-[#0B1020] border-b border-[#1F2937] px-4 py-3 shrink-0">
          <h2 className="text-sm font-semibold text-gray-300">{getPageTitle()}</h2>
        </div>

        {/* Children Page View */}
        <main className="flex-1 overflow-y-auto p-4 md:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
