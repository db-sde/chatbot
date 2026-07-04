import React, { useState } from "react";
import {
  Users,
  Key,
  Database,
  Smartphone,
  Save,
  CheckCircle
} from "lucide-react";
import { Badge } from "../components/Common";

export default function Settings() {
  const [activeTab, setActiveTab] = useState("users");
  const [successMsg, setSuccessMsg] = useState("");

  const handleSave = (e) => {
    e.preventDefault();
    setSuccessMsg("Settings mock payload validated successfully.");
    setTimeout(() => setSuccessMsg(""), 3000);
  };

  const tabs = [
    { id: "users", name: "Admin Users", icon: Users },
    { id: "keys", name: "API Keys", icon: Key },
    { id: "crm", name: "CRM Integration", icon: Database },
    { id: "widget", name: "Widget Customization", icon: Smartphone },
  ];

  return (
    <div className="space-y-6 text-left max-w-4xl">
      <div>
        <h2 className="text-base font-bold text-gray-200">System Configuration</h2>
        <p className="text-xs text-gray-500 mt-0.5">Customize security keys, admin accounts, widget themes, and CRM integrations.</p>
      </div>

      {successMsg && (
        <div className="p-4 bg-emerald-950/20 border border-emerald-900/50 rounded-xl flex items-center space-x-3 text-xs text-emerald-400">
          <CheckCircle size={16} className="text-emerald-500 shrink-0" />
          <span>{successMsg}</span>
        </div>
      )}

      <div className="bg-[#111827] border border-[#1F2937] rounded-xl overflow-hidden flex flex-col md:flex-row shadow-sm">
        {/* Navigation Tabs */}
        <div className="w-full md:w-60 bg-[#0E131F]/30 border-b md:border-b-0 md:border-r border-[#1F2937] p-4 flex md:flex-col gap-1 shrink-0 overflow-x-auto md:overflow-x-visible">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                flex items-center space-x-2.5 px-4 py-2.5 rounded-lg text-xs font-semibold tracking-wider text-left transition-all shrink-0 w-auto md:w-full
                ${activeTab === tab.id
                  ? "bg-[#3B82F6] text-white"
                  : "text-gray-400 hover:bg-[#1F2937] hover:text-white"
                }
              `}
            >
              <tab.icon size={14} />
              <span>{tab.name}</span>
            </button>
          ))}
        </div>

        {/* Configurations content panel */}
        <form onSubmit={handleSave} className="flex-1 p-6 md:p-8 space-y-6">
          {activeTab === "users" && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-200 mb-1">Administrative Users</h3>
                <p className="text-xs text-gray-500">Manage user authorization profiles capable of reviewing analytics.</p>
              </div>
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Username / Email</label>
                    <input
                      type="text"
                      disabled
                      placeholder="admin@degreebaba.com"
                      className="w-full px-3 py-2 bg-[#1C2433] border border-[#2D3748] rounded-lg text-xs text-gray-400 cursor-not-allowed"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Role</label>
                    <input
                      type="text"
                      disabled
                      placeholder="System Administrator"
                      className="w-full px-3 py-2 bg-[#1C2433] border border-[#2D3748] rounded-lg text-xs text-gray-400 cursor-not-allowed"
                    />
                  </div>
                </div>
                <div className="p-4 border border-[#1F2937] border-dashed rounded-lg bg-[#0E131F]/30 text-xs text-gray-500">
                  User creation and password management settings are disabled in sandbox environment.
                </div>
              </div>
            </div>
          )}

          {activeTab === "keys" && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-200 mb-1">Integrations & API Tokens</h3>
                <p className="text-xs text-gray-500">Tokens used to authenticate against AI agents and catalog endpoints.</p>
              </div>
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Groq API Key</label>
                    <Badge variant="success">Bound</Badge>
                  </div>
                  <input
                    type="password"
                    disabled
                    value="••••••••••••••••••••••••••••"
                    className="w-full px-3 py-2 bg-[#1C2433] border border-[#2D3748] rounded-lg text-xs text-gray-400 cursor-not-allowed"
                  />
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between items-center">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Gemini API Key</label>
                    <Badge variant="success">Bound</Badge>
                  </div>
                  <input
                    type="password"
                    disabled
                    value="••••••••••••••••••••••••••••"
                    className="w-full px-3 py-2 bg-[#1C2433] border border-[#2D3748] rounded-lg text-xs text-gray-400 cursor-not-allowed"
                  />
                </div>
              </div>
            </div>
          )}

          {activeTab === "crm" && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-200 mb-1">CRM Webhook Endpoint</h3>
                <p className="text-xs text-gray-500">Incoming lead notifications will be forwarded to this URL.</p>
              </div>
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] font-bold text-gray-400 uppercase">Webhook Callback URL</label>
                  <input
                    type="url"
                    placeholder="https://crm.degreebaba.com/api/v1/leads"
                    className="w-full px-3 py-2 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div className="flex items-center space-x-2">
                  <input type="checkbox" defaultChecked className="rounded border-gray-700 bg-gray-800 text-blue-500" />
                  <span className="text-xs text-gray-400">Retry webhook forwarding on network failure</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === "widget" && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-200 mb-1">Advising Widget Customization</h3>
                <p className="text-xs text-gray-500">Configure visual themes, placeholders, and widget behaviors.</p>
              </div>
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Theme Primary Color</label>
                    <input
                      type="text"
                      defaultValue="#3B82F6"
                      className="w-full px-3 py-2 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-gray-400 uppercase">Welcome Greeting Message</label>
                    <input
                      type="text"
                      defaultValue="Hello! Ask me about colleges or courses."
                      className="w-full px-3 py-2 bg-[#1F2937] border border-[#2D3748] rounded-lg text-xs text-gray-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Action button */}
          <div className="border-t border-[#1F2937] pt-6 flex justify-end">
            <button
              type="submit"
              className="flex items-center space-x-2 px-5 py-2.5 bg-[#3B82F6] hover:bg-blue-600 text-white rounded-lg text-xs font-semibold tracking-wider transition-all shadow-md"
            >
              <Save size={14} />
              <span>Save Configurations</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
