import { create } from "zustand";
import { persist } from "zustand/middleware";
import { authService, type AdminUser } from "@/services/authService";

/**
 * Admin auth store.
 *
 * Lưu token riêng (`adminToken`) để không lẫn với user SPA.
 * Chỉ user có role="admin" mới vào được /upload.
 */
interface AuthState {
  token: string | null;
  user: AdminUser | null;
  loading: boolean;
  error: string | null;

  parseOAuthToken: (hash: string) => Promise<void>;
  signOut: () => Promise<void>;
  fetchMe: () => Promise<void>;
  clearError: () => void;
  isAdmin: () => boolean;
}

export const useAdminAuth = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      user: null,
      loading: false,
      error: null,

      isAdmin: () => get().user?.role === "admin",

      async parseOAuthToken(hash: string) {
        const params = new URLSearchParams(hash.replace(/^#/, ""));
        const token =
          params.get("token") ||
          params.get("access_token") ||
          params.get("accessToken") ||
          "";

        if (!token) return;

        set({ loading: true, error: null, token });
        localStorage.setItem("adminToken", token);

        try {
          const user = await authService.getMe();
          if (user.role !== "admin") {
            set({
              error: `Tài khoản ${user.email} không có quyền admin (role=${user.role}).`,
              token: null,
              user: null,
              loading: false,
            });
            localStorage.removeItem("adminToken");
            return;
          }
          set({ user, loading: false });
        } catch {
          // Thử refresh 1 lần
          try {
            const refreshed = await authService.refreshToken();
            localStorage.setItem("adminToken", refreshed.accessToken);
            set({ token: refreshed.accessToken, loading: false });
            const user = await authService.getMe();
            if (user.role !== "admin") {
              set({
                error: `Tài khoản ${user.email} không có quyền admin.`,
                token: null,
                user: null,
              });
              localStorage.removeItem("adminToken");
              return;
            }
            set({ user });
          } catch {
            set({ loading: false, token: null });
            localStorage.removeItem("adminToken");
          }
        }
      },

      async signOut() {
        try {
          await authService.signOut();
        } catch {
          /* ignore */
        }
        set({ token: null, user: null, error: null });
        localStorage.removeItem("adminToken");
        localStorage.removeItem("adminUser");
      },

      async fetchMe() {
        if (!get().token) return;
        set({ loading: true, error: null });
        try {
          const user = await authService.getMe();
          if (user.role !== "admin") {
            set({
              error: `Tài khoản không có quyền admin (role=${user.role}).`,
              token: null,
              user: null,
              loading: false,
            });
            localStorage.removeItem("adminToken");
            return;
          }
          set({ user, loading: false });
        } catch (err) {
          const status = (err as { response?: { status?: number } })?.response
            ?.status;
          if (status === 401 || status === 403) {
            // thử refresh
            try {
              const refreshed = await authService.refreshToken();
              localStorage.setItem("adminToken", refreshed.accessToken);
              set({ token: refreshed.accessToken });
              const user = await authService.getMe();
              if (user.role !== "admin") {
                set({ token: null, user: null, loading: false });
                localStorage.removeItem("adminToken");
                return;
              }
              set({ user, loading: false });
            } catch {
              set({ token: null, user: null, loading: false });
              localStorage.removeItem("adminToken");
            }
          } else {
            set({ loading: false });
          }
        }
      },

      clearError() {
        set({ error: null });
      },
    }),
    {
      name: "admin-auth-storage",
      partialize: (state) => ({ token: state.token, user: state.user }),
    }
  )
);
