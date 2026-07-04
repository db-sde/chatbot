const API_BASE = "/api/admin";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const getHeaders = () => {
  const token = localStorage.getItem("db_admin_token") || "";
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

const request = async (path, options = {}) => {
  const url = `${API_BASE}${path}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      ...getHeaders(),
      ...options.headers,
    },
  });

  if (response.status === 401 || response.status === 403) {
    // Clear token on auth failure so user is prompted again
    localStorage.removeItem("db_admin_token");
  }

  if (!response.ok) {
    let errMsg = `Request failed with status ${response.status}`;
    try {
      const data = await response.json();
      if (data && data.detail) {
        errMsg = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // Ignore JSON parse errors; fall back to status-based message
    }
    throw new ApiError(errMsg, response.status);
  }

  return response.json();
};

export const api = {
  setToken(token) {
    localStorage.setItem("db_admin_token", token);
  },

  getToken() {
    return localStorage.getItem("db_admin_token");
  },

  clearToken() {
    localStorage.removeItem("db_admin_token");
  },

  async getAnalytics() {
    return request("/analytics");
  },

  async getConversations(filters = {}) {
    const params = new URLSearchParams();
    if (filters.university) params.append("university", filters.university);
    if (filters.date_from) params.append("date_from", filters.date_from);
    if (filters.date_to) params.append("date_to", filters.date_to);
    if (filters.has_lead !== undefined && filters.has_lead !== null) params.append("has_lead", filters.has_lead);
    if (filters.has_unanswered !== undefined && filters.has_unanswered !== null) params.append("has_unanswered", filters.has_unanswered);
    if (filters.limit) params.append("limit", filters.limit);
    if (filters.offset) params.append("offset", filters.offset);

    const query = params.toString();
    return request(`/conversations${query ? `?${query}` : ""}`);
  },

  async getConversation(sessionId) {
    return request(`/conversations/${sessionId}`);
  },

  async getLeads(limit = 100, offset = 0) {
    return request(`/leads?limit=${limit}&offset=${offset}`);
  },

  async getUnanswered() {
    return request("/unanswered");
  },

  async getSecuritySummary() {
    return request("/security/summary");
  },

  async getSecurityAttacks(limit = 20) {
    return request(`/security/attacks?limit=${limit}`);
  },

  async getAnalyticsOverview() {
    return request("/analytics/overview");
  },

  async getAnalyticsModels() {
    return request("/analytics/models");
  },

  async getAnalyticsTools() {
    return request("/analytics/tools");
  },

  async getAnalyticsUniversities() {
    return request("/analytics/universities");
  },

  async getAnalyticsCosts() {
    return request("/analytics/costs");
  },

  async getAnalyticsFunnel() {
    return request("/analytics/funnel");
  },

  async getWidgetSettings(siteId) {
    return request(`/widget-settings/${encodeURIComponent(siteId)}`);
  },

  async updateWidgetSettings(siteId, settings) {
    return request(`/widget-settings/${encodeURIComponent(siteId)}`, {
      method: "PUT",
      body: JSON.stringify(settings),
    });
  },

  async listWidgetSettings() {
    return request("/widget-settings");
  },
};
