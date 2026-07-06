import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Lock, ShieldAlert } from "lucide-react";
import { api } from "./services/api";

// Layout & Pages
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Conversations from "./pages/Conversations";
import SessionDetails from "./pages/SessionDetails";
import Leads from "./pages/Leads";
import Analytics from "./pages/Analytics";
import Security from "./pages/Security";
import Unanswered from "./pages/Unanswered";
import Settings from "./pages/Settings";

function LoginScreen({ onLogin }) {
  const [tokenInput, setTokenInput] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!tokenInput.trim()) {
      setErrorMsg("Please enter an authorization token.");
      return;
    }
    // Set token client side; API client will automatically attach it as Bearer header.
    api.setToken(tokenInput.trim());
    onLogin();
  };

  return (
    <div className="min-h-screen bg-[#0B1020] text-gray-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-[#111827] border border-[#1F2937] rounded-2xl p-8 space-y-6 shadow-2xl relative overflow-hidden">
        {/* Glow effect decorative */}
        <div className="absolute -top-16 -left-16 h-32 w-32 bg-blue-500/10 rounded-full blur-3xl"></div>
        <div className="absolute -bottom-16 -right-16 h-32 w-32 bg-blue-500/10 rounded-full blur-3xl"></div>

        <div className="text-center space-y-2 relative">
          <div className="h-12 w-12 bg-blue-950/40 text-blue-400 border border-blue-900/50 rounded-xl flex items-center justify-center mx-auto mb-4 shadow-inner">
            <Lock size={22} />
          </div>
          <h2 className="text-lg font-bold text-gray-100 tracking-tight">Access Authorization</h2>
          <p className="text-xs text-gray-500 font-medium">Verify your admin token to connect to DegreeBaba databases.</p>
        </div>

        {errorMsg && (
          <div className="p-3 bg-red-950/20 border border-red-900/50 rounded-lg text-xs text-red-400 font-medium flex items-center space-x-2">
            <ShieldAlert size={14} className="text-red-500 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 relative">
          <div className="space-y-1.5 text-left">
            <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">Secret Security Token</label>
            <input
              type="password"
              placeholder="Enter admin token..."
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              className="w-full px-4 py-3 bg-[#1F2937] border border-[#2D3748] rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all font-mono"
            />
          </div>

          <button
            type="submit"
            className="w-full py-3 bg-[#3B82F6] hover:bg-blue-600 text-white font-semibold text-xs tracking-wider rounded-lg shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30 transition-all duration-150"
          >
            Authenticate Session
          </button>
        </form>

        <div className="text-[10px] text-gray-600 text-center font-medium">
          Protected by DegreeBaba AI Security Policy Layer
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(!!api.getToken());

  if (!isAuthenticated) {
    return <LoginScreen onLogin={() => setIsAuthenticated(true)} />;
  }

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/admin" element={<Dashboard />} />
          <Route path="/admin/conversations" element={<Conversations />} />
          <Route path="/admin/conversations/:sessionId" element={<SessionDetails />} />
          <Route path="/admin/leads" element={<Leads />} />
          <Route path="/admin/analytics" element={<Analytics />} />
          <Route path="/admin/security" element={<Security />} />
          <Route path="/admin/unanswered" element={<Unanswered />} />
          <Route path="/admin/settings" element={<Settings />} />
          {/* Redirect matching default pathing */}
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
