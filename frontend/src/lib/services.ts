/**
 * =============================================================
 * Multi-service axios — mỗi service có 1 axios instance riêng
 * =============================================================
 *
 * Luồng hoạt động:
 * - AUTH_SERVICE_URL: gọi /auth/me, /auth/refresh, /auth/logout
 * - CHAT_SERVICE_URL: gọi /chats/* (yêu cầu JWT)
 * - RAG_SERVICE_URL:  gọi /api/chat trực tiếp (guest mode, không JWT)
 *
 * Mỗi instance có retry/refresh riêng và KHÔNG ảnh hưởng lẫn nhau:
 *  - auth fail → caller xử lý (vd: xóa token, set isAuthenticated=false)
 *  - chat fail → caller xử lý (vd: ẩn sidebar history, vẫn dùng guest)
 *  - rag fail → caller xử lý (vd: show "hệ thống bận")
 *
 * Auth-service có retry/refresh logic:
 * - accessToken hết hạn (401/403) → tự gọi /auth/refresh → retry
 * - Refresh fail → caller xử lý (thường là xóa token)
 *
 * Chat-service KHÔNG có refresh (vì cùng JWT_SECRET_KEY với auth-service
 * nên cùng verify được — khi auth refresh xong, chat sẽ pass).
 * Nhưng nếu chat trả 401, ta clear token + chuyển về guest.
 */

import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";

const AUTH_SERVICE_URL =
  import.meta.env.VITE_AUTH_SERVICE_URL || "http://localhost:8001";
const CHAT_SERVICE_URL =
  import.meta.env.VITE_CHAT_SERVICE_URL || "http://localhost:8002";
export const RAG_SERVICE_URL =
  import.meta.env.VITE_RAG_SERVICE_URL || "http://localhost:8003";

// =====================================================================
// Helper: tạo axios instance cơ bản
// =====================================================================
function createInstance(baseURL: string) {
  return axios.create({
    baseURL,
    withCredentials: true, // refreshToken cookie từ auth-service
    headers: { "Content-Type": "application/json" },
    timeout: 30000,
  });
}

// =====================================================================
// AUTH INSTANCE — chỉ dùng cho auth endpoints, có refresh
// =====================================================================
const authInstance = createInstance(AUTH_SERVICE_URL);

authInstance.interceptors.request.use((config) => {
  const accessToken = localStorage.getItem("accessToken");
  if (accessToken && config.headers) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// Refresh interceptor cho auth: chỉ retry với /auth/me
let authIsRefreshing = false;
authInstance.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };
    const isAuthMe =
      original?.url?.includes("/auth/me") ||
      original?.url?.includes("/auth/logout");
    if (
      original &&
      isAuthMe &&
      (error.response?.status === 401 || error.response?.status === 403) &&
      !original._retry
    ) {
      if (authIsRefreshing) {
        await new Promise((res) => setTimeout(res, 200));
        return authInstance(original);
      }
      original._retry = true;
      authIsRefreshing = true;
      try {
        const refreshRes = await axios.post(
          `${AUTH_SERVICE_URL}/auth/refresh`,
          {},
          { withCredentials: true }
        );
        const newToken: string | undefined =
          refreshRes.data?.accessToken || refreshRes.data?.access_token;
        if (!newToken) throw new Error("No access token from refresh");
        localStorage.setItem("accessToken", newToken);
        if (original.headers) original.headers.Authorization = `Bearer ${newToken}`;
        return authInstance(original);
      } catch (e) {
        localStorage.removeItem("accessToken");
        localStorage.removeItem("user");
        throw e;
      } finally {
        authIsRefreshing = false;
      }
    }
    throw error;
  }
);

// =====================================================================
// CHAT INSTANCE — gọi chat-service:8002, có gắn token nhưng không refresh
// =====================================================================
const chatInstance = createInstance(CHAT_SERVICE_URL);

chatInstance.interceptors.request.use((config) => {
  const accessToken = localStorage.getItem("accessToken");
  if (accessToken && config.headers) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// =====================================================================
// Service exports
// =====================================================================
export const authApi = authInstance;
export const chatApi = chatInstance;
