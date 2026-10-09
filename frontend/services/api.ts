import {
  User,
  PriorArtSearchResponse,
  SearchHistoryItem,
  SavedPatent,
  Report,
  Patent,
  SearchFormData,
  TokenResponse
} from "@/types";

const rawApiUrl = process.env.NEXT_PUBLIC_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || "/api";
const API_BASE_URL = typeof window !== "undefined" ? "/api" : (rawApiUrl === "/api" ? "/api" : (rawApiUrl.endsWith("/api") ? rawApiUrl : `${rawApiUrl.replace(/\/$/, "")}/api`));

function getStoredToken(): string | null {
  if (typeof window !== "undefined") {
    return localStorage.getItem("patentlens_token");
  }
  return null;
}

export function setStoredToken(token: string | null) {
  if (typeof window !== "undefined") {
    if (token) {
      localStorage.setItem("patentlens_token", token);
    } else {
      localStorage.removeItem("patentlens_token");
      localStorage.removeItem("patentlens_user_email");
      localStorage.removeItem("patentlens_user_name");
    }
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const config: RequestInit = {
    ...options,
    headers,
  };

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${endpoint}`, config);
  } catch (networkErr: any) {
    throw new Error(
      `Failed to connect to API server (${API_BASE_URL}). Please ensure the backend service is running.`
    );
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (response.status === 401 && typeof window !== "undefined") {
      setStoredToken(null);
      const pathname = window.location.pathname;
      if (pathname !== "/login" && pathname !== "/register" && pathname !== "/") {
        window.location.href = "/login";
      }
    }
    const errorMsg = data.detail || data.message || `API request failed with status ${response.status}`;
    throw new Error(errorMsg);
  }

  return data as T;
}

function saveUserData(user?: { email?: string; name?: string } | null) {
  if (typeof window !== "undefined" && user) {
    if (user.email) localStorage.setItem("patentlens_user_email", user.email);
    if (user.name) localStorage.setItem("patentlens_user_name", user.name);
  }
}

export const api = {
  // Auth
  register: async (payload: any) => {
    const data = await request<any>("/auth/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.user) saveUserData(data.user);
    if (data.access_token) setStoredToken(data.access_token);
    return data;
  },

  login: async (payload: any): Promise<TokenResponse> => {
    const data = await request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.user) saveUserData(data.user);
    if (data.access_token) setStoredToken(data.access_token);
    return data;
  },

  googleAuth: async (payload: { email: string; name?: string }): Promise<TokenResponse> => {
    const data = await request<TokenResponse>("/auth/google", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.user) saveUserData(data.user);
    if (data.access_token) setStoredToken(data.access_token);
    return data;
  },

  verifyOTP: async (payload: { email: string; otp: string }): Promise<TokenResponse> => {
    const data = await request<TokenResponse>("/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.user) saveUserData(data.user);
    if (data.access_token) setStoredToken(data.access_token);
    return data;
  },

  resendOTP: async (payload: { email: string }): Promise<TokenResponse> => {
    const data = await request<TokenResponse>("/auth/resend-otp", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (data.user) saveUserData(data.user);
    return data;
  },

  logout: async () => {
    try {
      await request<any>("/auth/logout", { method: "POST" });
    } catch {}
    setStoredToken(null);
  },

  getMe: async (): Promise<User | null> => {
    const token = getStoredToken();
    if (!token) {
      return null;
    }
    if (!token.startsWith("demo_token_")) {
      try {
        return await request<User>("/auth/me");
      } catch (err) {
        // Fallback if backend /auth/me fails
      }
    }
    const storedEmail = typeof window !== "undefined" ? localStorage.getItem("patentlens_user_email") : null;
    const storedName = typeof window !== "undefined" ? localStorage.getItem("patentlens_user_name") : null;
    const email = storedEmail || "inventor@startup.com";
    let name = storedName;
    if (!name) {
      const parts = email.split("@")[0].replace(/[^a-zA-Z0-9]/g, " ");
      name = parts ? parts.charAt(0).toUpperCase() + parts.slice(1) : "User";
    }
    return {
      id: "user-" + email.replace(/[^a-zA-Z0-9]/g, "-"),
      email: email,
      name: name,
      created_at: new Date().toISOString(),
      search_count: 3,
    } as User;
  },

  // Prior-Art Search
  performSearch: async (payload: SearchFormData): Promise<PriorArtSearchResponse> => {
    return request<PriorArtSearchResponse>("/search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getSearchHistory: async (): Promise<SearchHistoryItem[]> => {
    try {
      return await request<SearchHistoryItem[]>("/search/history");
    } catch {
      return [];
    }
  },

  getSearchDetails: async (searchId: string): Promise<PriorArtSearchResponse> => {
    return request<PriorArtSearchResponse>(`/search/${searchId}`);
  },

  deleteSearch: async (searchId: string): Promise<{ success: boolean }> => {
    return request<{ success: boolean }>(`/search/${searchId}`, {
      method: "DELETE",
    });
  },

  // Patents
  getPatentDetails: async (patentId: string): Promise<Patent> => {
    return request<Patent>(`/patents/${patentId}`);
  },

  getSavedPatents: async (): Promise<SavedPatent[]> => {
    try {
      return await request<SavedPatent[]>("/patents/saved");
    } catch {
      return [];
    }
  },

  savePatent: async (patentId: string, notes?: string): Promise<SavedPatent> => {
    return request<SavedPatent>(`/patents/${patentId}/save`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    });
  },

  unsavePatent: async (patentId: string): Promise<{ success: boolean }> => {
    return request<{ success: boolean }>(`/patents/${patentId}/save`, {
      method: "DELETE",
    });
  },

  // Reports
  createReport: async (searchId: string): Promise<Report> => {
    return request<Report>(`/reports/${searchId}`, {
      method: "POST",
    });
  },

  getReports: async (): Promise<Report[]> => {
    try {
      return await request<Report[]>("/reports");
    } catch {
      return [];
    }
  },

  getReportDownloadUrl: (reportId: string) => {
    const token = getStoredToken();
    return `${API_BASE_URL}/reports/${reportId}/download?token=${token}`;
  },

  downloadReportPDF: async (reportId: string, filename: string) => {
    const token = getStoredToken();
    const res = await fetch(`${API_BASE_URL}/reports/${reportId}/download`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) throw new Error("Failed to download PDF report");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  },

  // User Profile
  updateProfile: async (payload: { name: string; email: string }): Promise<User> => {
    return request<User>("/users/profile", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  changePassword: async (payload: any): Promise<{ success: boolean; message: string }> => {
    return request<{ success: boolean; message: string }>("/users/change-password", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteAccount: async (): Promise<{ success: boolean }> => {
    return request<{ success: boolean }>("/users/account?confirm=true", {
      method: "DELETE",
    });
  },
};
