import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";

import SignInPage from "@/pages/auth/SignInPage";
import ChatPage from "@/pages/chat/ChatPage";
import { useAuthStore } from "@/store/useAuthStore";

/**
 * App - luồng đơn giản:
 * - /             → ChatPage (guest vẫn vào được, giới hạn 3 tin nhắn)
 * - /sign-in      → Trang đăng nhập Google OAuth
 * - /sign-up      → Redirect về /sign-in (chỉ có 1 cách đăng nhập: Google)
 * - *             → /sign-in
 *
 * Khi OAuth callback redirect về URL có #token=xxx, App tự parse token và
 * gọi /auth/me để lấy thông tin user. Sau đó clear hash khỏi URL.
 *
 * Khi reload trang (đã đăng nhập trước đó), App tự động fetch lại user info
 * từ localStorage để khôi phục trạng thái đăng nhập.
 */
function App() {
  const parseOAuthToken = useAuthStore((s) => s.parseOAuthToken);
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);

  // 1) OAuth callback: parse #token= từ URL
  useEffect(() => {
    if (window.location.hash) {
      parseOAuthToken(window.location.hash).finally(() => {
        window.history.replaceState(null, "", window.location.pathname);
      });
    }
  }, [parseOAuthToken]);

  // 2) Reload page: có accessToken nhưng chưa có user → fetch lại
  useEffect(() => {
    if (accessToken && !user) {
      fetchMe();
    }
  }, [accessToken, user, fetchMe]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/sign-in" element={<SignInPage />} />
        <Route path="/sign-up" element={<Navigate to="/sign-in" replace />} />
        <Route path="*" element={<Navigate to="/sign-in" replace />} />
      </Routes>

      {/* Sonner Toaster - đặt ở root để mọi trang đều dùng được */}
      <Toaster
        position="top-right"
        richColors
        closeButton
        toastOptions={{
          duration: 4000,
        }}
      />
    </BrowserRouter>
  );
}

export default App;
