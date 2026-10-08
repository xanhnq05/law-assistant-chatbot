import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, LogIn, Eye, EyeOff } from "lucide-react";
import { useAdminAuth } from "@/store/useAdminAuth";

/**
 * TEMP: hardcode admin/admin.
 *
 * TODO: thay bằng call auth-service / admin-auth-service thật sau khi
 * user xử lý phần backend.
 */
const HARDCODED_USERNAME = "admin";
const HARDCODED_PASSWORD = "admin";
const PLACEHOLDER_TOKEN = "hardcoded.admin.token";

export default function LoginPage() {
  const navigate = useNavigate();
  const user = useAdminAuth((s) => s.user);
  const error = useAdminAuth((s) => s.error);
  const clearError = useAdminAuth((s) => s.clearError);
  const fetchMe = useAdminAuth((s) => s.fetchMe);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (user?.role === "admin") {
      navigate("/upload", { replace: true });
    }
  }, [user, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    clearError();
    if (!username || !password) {
      useAdminAuth.setState({ error: "Vui lòng nhập username và password." });
      return;
    }
    setSubmitting(true);
    try {
      const ok =
        username.trim() === HARDCODED_USERNAME &&
        password === HARDCODED_PASSWORD;
      if (!ok) {
        useAdminAuth.setState({ error: "Sai username hoặc password." });
        return;
      }
      const fakeUser = {
        id: "hardcoded-admin",
        email: "admin@local.dev",
        name: "Administrator",
        role: "admin",
      };
      localStorage.setItem("adminToken", PLACEHOLDER_TOKEN);
      useAdminAuth.setState({
        user: fakeUser,
        token: PLACEHOLDER_TOKEN,
        error: null,
        loading: false,
      });
      void fetchMe();
      navigate("/upload", { replace: true });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gradient-to-br from-slate-50 via-white to-blue-50">
      <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-card-lg p-8">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-blue-600 text-white flex items-center justify-center shadow-sm">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Admin Console</h1>
            <p className="text-sm text-slate-500">
              Document Management · Trợ Lý Pháp Luật
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <p className="text-sm text-slate-600">
            Đăng nhập bằng tài khoản <code>admin</code> (tạm thời hardcode).
          </p>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <div>
            <label
              htmlFor="username"
              className="block text-sm font-medium text-slate-700 mb-1"
            >
              Username
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              placeholder="admin"
              disabled={submitting}
              required
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-slate-700 mb-1"
            >
              Password
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPwd ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-lg bg-white border border-slate-200 px-3 py-2 pr-10 text-sm text-slate-900 focus:outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                placeholder="••••••"
                disabled={submitting}
                required
              />
              <button
                type="button"
                onClick={() => setShowPwd((s) => !s)}
                tabIndex={-1}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-700"
                aria-label={showPwd ? "Ẩn password" : "Hiện password"}
              >
                {showPwd ? (
                  <EyeOff className="w-4 h-4" />
                ) : (
                  <Eye className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold py-3 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            <LogIn className="w-5 h-5" />
            {submitting ? "Đang đăng nhập..." : "Đăng nhập"}
          </button>

          <p className="text-xs text-slate-400 text-center mt-4">
            ⚠️ Đang dùng bản hardcode <code>admin/admin</code>. Sẽ tích hợp
            backend thật sau.
          </p>
        </form>
      </div>
    </div>
  );
}
