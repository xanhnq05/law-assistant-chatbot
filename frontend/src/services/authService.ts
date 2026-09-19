import { authApi } from "@/lib/services";

/**
 * Auth service - chỉ xử lý Google OAuth + user info.
 *
 * Backend endpoints (chạy trực tiếp từ browser, không cần Vite proxy):
 * - GET  /auth/google/login        → bắt đầu Google OAuth
 * - GET  /auth/google/callback     → Google redirect về, trả #token=<jwt>
 * - GET  /auth/me                  → lấy thông tin user (cần JWT)
 * - POST /auth/refresh             → đổi refresh token → access token mới
 * - POST /auth/logout              → đăng xuất
 */

// ===== Types =====
export interface User {
  id: string;
  google_id?: string;
  email: string;
  name: string;
  picture?: string;
  email_verified?: boolean;
  role?: string;
  [key: string]: unknown;
}

export interface RefreshResponse {
  accessToken: string;
  token_type?: string;
  access_token?: string;
}

const API = {
  googleLogin: "/auth/google/login",
  me: "/auth/me",
  refresh: "/auth/refresh",
  logout: "/auth/logout",
};

// ===== API calls =====
export const authService = {
  /**
   * Trả về URL Google OAuth của backend.
   * Browser redirect tới đây → Google → callback → redirect về frontend/#token=xxx
   */
  getGoogleOAuthUrl(): string {
    return `${import.meta.env.VITE_AUTH_SERVICE_URL || "http://localhost:8001"}${API.googleLogin}`;
  },

  /** Lấy thông tin user hiện tại từ JWT */
  async getMe(): Promise<User> {
    const { data } = await authApi.get<User>(API.me);
    return data;
  },

  /** Gọi refresh endpoint (cookie tự gửi) để lấy access token mới */
  async refreshToken(): Promise<RefreshResponse> {
    const { data } = await authApi.post<RefreshResponse>(API.refresh);
    return data;
  },

  /** Đăng xuất */
  async signOut(): Promise<void> {
    await authApi.post(API.logout);
  },
};
