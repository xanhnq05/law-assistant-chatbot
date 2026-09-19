import { useAuthStore } from "@/store/useAuthStore";

/**
 * Custom hook để dễ dàng truy cập auth state mà không phải import store trực tiếp.
 */
export const useAuth = () => {
  const {
    accessToken,
    user,
    loading,
    error,
    signOut,
    fetchMe,
    parseOAuthToken,
    setAccessToken,
    clearError,
  } = useAuthStore();

  // Authenticated khi CẢ accessToken VÀ user đều có (persist từ localStorage).
  // accessToken dùng để gọi API (axios interceptor tự gắn vào header).
  // user dùng để hiển thị UI (avatar, tên, sidebar).
  const isAuthenticated = !!(accessToken && user);

  return {
    accessToken,
    user,
    loading,
    error,
    isAuthenticated,
    signOut,
    fetchMe,
    parseOAuthToken,
    setAccessToken,
    clearError,
  };
};