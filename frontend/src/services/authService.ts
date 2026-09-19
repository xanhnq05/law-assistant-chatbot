import { axiosInstance } from "@/lib/axios";

/**
 * Auth service - chỉ xử lý Google OAuth.
 *
 * Backend endpoints:
 * - GET  /api/auth/google/login      → redirect Google OAuth
 * - GET  /api/auth/google/callback   → Google redirect về, trả #token=<jwt>
 * - GET  /api/auth/me                → lấy thông tin user (cần JWT)
 * - POST /api/auth/refresh           → đổi refresh token → access token mới
 * - POST /api/auth/logout            → đăng xuất
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
  googleLogin: "/api/auth/google/login",
  googleCallback: "/api/auth/google/callback",
  me: "/api/auth/me",
  refresh: "/api/auth/refresh",
  logout: "/api/auth/logout",
};

// ===== API calls =====
export const authService = {
  /**
   * Trả về URL Google OAuth của backend.
   * Browser redirect tới đây → Google → callback → redirect về frontend/#token=xxx
   */
  getGoogleOAuthUrl(): string {
    const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8080";
    return `${baseURL}${API.googleLogin}`;
  },

  /** Lấy thông tin user hiện tại từ JWT */
  async getMe(): Promise<User> {
    const { data } = await axiosInstance.get<User>(API.me);
    return data;
  },

  /** Gọi refresh endpoint để lấy access token mới (cookie tự gửi) */
  async refreshToken(): Promise<RefreshResponse> {
    const { data } = await axiosInstance.post<RefreshResponse>(API.refresh);
    return data;
  },

  /** Đăng xuất */
  async signOut(): Promise<void> {
    await axiosInstance.post(API.logout);
  },
};