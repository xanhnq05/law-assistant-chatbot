/**
 * Admin SPA — multi-service axios.
 *
 * - AUTH_SERVICE_URL: gọi /auth/google/login, /auth/me, /auth/refresh, /auth/logout
 *   (tận dụng lại auth-service hiện có - KHÔNG tạo auth mới)
 * - DOCUMENT_SERVICE_URL: gọi /admin/* (yêu cầu JWT + role=admin)
 *
 * Token lưu riêng trong localStorage("adminToken") để không lẫn với user SPA.
 */
import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";

const AUTH_SERVICE_URL =
  import.meta.env.VITE_AUTH_SERVICE_URL || "http://localhost:8001";
const DOCUMENT_SERVICE_URL =
  import.meta.env.VITE_DOCUMENT_SERVICE_URL || "http://localhost:8004";

export { AUTH_SERVICE_URL, DOCUMENT_SERVICE_URL };

// ----------------------------------------------------------------
// Helper
// ----------------------------------------------------------------
function createInstance(baseURL: string) {
  return axios.create({
    baseURL,
    withCredentials: true, // refresh cookie
    headers: { "Content-Type": "application/json" },
    timeout: 60000, // upload PDF/DOCX cần timeout dài hơn
  });
}

// ----------------------------------------------------------------
// AUTH (verify JWT, không tạo token)
// ----------------------------------------------------------------
const authInstance = createInstance(AUTH_SERVICE_URL);

authInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem("adminToken");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Refresh logic giống user SPA
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
        localStorage.setItem("adminToken", newToken);
        if (original.headers) original.headers.Authorization = `Bearer ${newToken}`;
        return authInstance(original);
      } catch (e) {
        localStorage.removeItem("adminToken");
        localStorage.removeItem("adminUser");
        throw e;
      } finally {
        authIsRefreshing = false;
      }
    }
    throw error;
  }
);

// ----------------------------------------------------------------
// DOCUMENT-SERVICE (admin-only)
// ----------------------------------------------------------------
const docInstance = createInstance(DOCUMENT_SERVICE_URL);

// multipart cần Content-Type do browser set (với boundary)
// Nên override trên từng request: `headers: { "Content-Type": "multipart/form-data" }`
docInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem("adminToken");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

docInstance.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    // Backend đã bypass auth (Phase 2 hardcoded admin), không redirect nữa.
    // Chỉ log error.
    if (error.response?.status === 401 || error.response?.status === 403) {
      // eslint-disable-next-line no-console
      console.warn(
        "[docApi] Auth error (currently bypassed):",
        error.response?.status,
        error.response?.data
      );
    }
    throw error;
  }
);

export const authApi = authInstance;
export const docApi = docInstance;
