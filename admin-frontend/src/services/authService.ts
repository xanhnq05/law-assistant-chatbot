/**
 * Admin auth service - OAuth Google + role check.
 * Tận dụng lại auth-service hiện có (không tạo auth mới).
 */
import { authApi } from "@/lib/services";

export interface AdminUser {
  id: string;
  email: string;
  name?: string;
  role: string;
  picture?: string;
}

const API = {
  googleLogin: "/auth/google/login",
  me: "/auth/me",
  refresh: "/auth/refresh",
  logout: "/auth/logout",
};

export const authService = {
  getGoogleOAuthUrl(): string {
    return `${import.meta.env.VITE_AUTH_SERVICE_URL || "http://localhost:8001"}${API.googleLogin}`;
  },

  async getMe(): Promise<AdminUser> {
    const { data } = await authApi.get<AdminUser>(API.me);
    return data;
  },

  async refreshToken(): Promise<{ accessToken: string }> {
    const { data } = await authApi.post<{ accessToken: string }>(API.refresh);
    return data;
  },

  async signOut(): Promise<void> {
    await authApi.post(API.logout);
  },
};
