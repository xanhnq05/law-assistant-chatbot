import { create } from "zustand";
import { persist } from "zustand/middleware";
import { authService, type User } from "@/services/authService";

/**
 * useAuthStore - quản lý trạng thái đăng nhập.
 *
 * Guest (chưa đăng nhập) vẫn truy cập được trang chat.
 * Access token được parse từ URL hash (#token=xxx) khi OAuth callback redirect về.
 * RefreshToken được backend set vào HttpOnly cookie → tự động gửi qua axios.
 */
interface AuthState {
  accessToken: string | null;
  user: User | null;
  loading: boolean;
  error: string | null;

  // Actions
  /** Parse #token= từ URL (OAuth callback), lưu token và fetch user info */
  parseOAuthToken: (hash: string) => Promise<void>;
  signOut: () => Promise<void>;
  fetchMe: () => Promise<void>;
  setAccessToken: (token: string | null) => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      user: null,
      loading: false,
      error: null,

      async parseOAuthToken(hash: string) {
        // hash dạng #token=xxx hoặc #access_token=xxx
        const params = new URLSearchParams(hash.replace(/^#/, ""));
        const token =
          params.get("token") ||
          params.get("access_token") ||
          params.get("accessToken") ||
          "";

        if (!token) return;

        set({ loading: true, error: null, accessToken: token });
        localStorage.setItem("accessToken", token);

        try {
          const user = await authService.getMe();
          set({ user, loading: false });
        } catch {
          // Token có thể chưa kích hoạt được → thử refresh
          try {
            const refreshed = await authService.refreshToken();
            localStorage.setItem("accessToken", refreshed.accessToken);
            set({ accessToken: refreshed.accessToken, loading: false });
            const user = await authService.getMe();
            set({ user });
          } catch {
            set({ loading: false, accessToken: null });
            localStorage.removeItem("accessToken");
          }
        }
      },

      async signOut() {
        try {
          await authService.signOut();
        } catch {
          // Bỏ qua lỗi từ server
        }
        set({ accessToken: null, user: null, error: null });
        localStorage.removeItem("accessToken");
      },

      async fetchMe() {
        if (!get().accessToken) return;
        set({ loading: true, error: null });
        try {
          const user = await authService.getMe();
          set({ user, loading: false });
        } catch {
          set({ loading: false });
        }
      },

      setAccessToken(token) {
        set({ accessToken: token });
        if (token) localStorage.setItem("accessToken", token);
        else localStorage.removeItem("accessToken");
      },

      clearError() {
        set({ error: null });
      },
    }),
    {
      name: "auth-storage",
      partialize: (state) => ({ user: state.user }),
    }
  )
);