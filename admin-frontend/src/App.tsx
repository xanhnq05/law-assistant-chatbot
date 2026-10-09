import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";

import LoginPage from "@/pages/LoginPage";
import UploadPage from "@/pages/UploadPage";
import { useAdminAuth } from "@/store/useAdminAuth";

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const token = useAdminAuth((s) => s.token);
  const user = useAdminAuth((s) => s.user);
  const fetchMe = useAdminAuth((s) => s.fetchMe);

  useEffect(() => {
    if (token && !user) {
      fetchMe();
    }
  }, [token, user, fetchMe]);

  if (!token) return <Navigate to="/login" replace />;
  if (!user) return <div className="p-8">Đang tải...</div>;
  if (user.role !== "admin") return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function App() {
  const parseOAuthToken = useAdminAuth((s) => s.parseOAuthToken);
  const token = useAdminAuth((s) => s.token);
  const user = useAdminAuth((s) => s.user);
  const fetchMe = useAdminAuth((s) => s.fetchMe);

  // OAuth callback: parse #token= từ URL
  useEffect(() => {
    if (window.location.hash) {
      parseOAuthToken(window.location.hash).finally(() => {
        window.history.replaceState(null, "", window.location.pathname);
      });
    }
  }, [parseOAuthToken]);

  // Reload: có token nhưng chưa có user → fetchMe
  useEffect(() => {
    if (token && !user) fetchMe();
  }, [token, user, fetchMe]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/upload"
          element={
            <RequireAdmin>
              <UploadPage />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes>
      <Toaster
        position="top-right"
        richColors
        closeButton
        toastOptions={{ duration: 4000 }}
      />
    </BrowserRouter>
  );
}

export default App;
