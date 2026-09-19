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

  const isAuthenticated = !!accessToken && !!user;

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