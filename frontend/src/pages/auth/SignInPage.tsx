import { Scale, ShieldAlert } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { authService } from "@/services/authService";

/**
 * Trang đăng nhập - layout y hệt frontend-vanilla-backup.
 * Theme dark navy + vàng đồng, font Noto Serif + Be Vietnam Pro.
 */
export default function SignInPage() {
  const { error } = useAuth();

  const handleGoogleLogin = () => {
    window.location.href = authService.getGoogleOAuthUrl();
  };

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-brand">
          <div className="icon-ring">
            <Scale width={28} height={28} />
          </div>
          <h1>Trợ Lý Pháp Luật</h1>
          <p>Tra cứu &amp; giải đáp pháp lý Việt Nam bằng AI</p>
        </div>

        <button
          className="google-btn"
          id="googleLoginBtn"
          type="button"
          onClick={handleGoogleLogin}
        >
          <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
            <path
              fill="#FFC107"
              d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.6-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
            />
            <path
              fill="#FF3D00"
              d="M6.3 14.7l6.6 4.8C14.6 15.7 18.9 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6 29.6 4 24 4 16.3 4 9.6 8.3 6.3 14.7z"
            />
            <path
              fill="#4CAF50"
              d="M24 44c5.5 0 10.4-1.9 14.2-5.1l-6.6-5.4C29.6 35.4 26.9 36 24 36c-5.2 0-9.7-3.4-11.3-8.1l-6.6 5.1C9.5 39.6 16.2 44 24 44z"
            />
            <path
              fill="#1976D2"
              d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.3-4.1 5.7l6.6 5.4C41.1 36 44 30.6 44 24c0-1.3-.1-2.4-.4-3.5z"
            />
          </svg>
          <span>Đăng nhập bằng Gmail</span>
        </button>

        {error && (
          <div
            className="setup-notice"
            style={{
              fontSize: "12.5px",
              lineHeight: 1.6,
              color: "var(--text-muted)",
              background: "rgba(190, 61, 42, 0.1)",
              border: "1px solid rgba(190, 61, 42, 0.35)",
              borderRadius: "8px",
              padding: "12px 14px",
              marginTop: 14,
            }}
          >
            <strong style={{ color: "var(--red)", display: "block", marginBottom: 4 }}>
              Không thể đăng nhập
            </strong>
            {error}
          </div>
        )}

        <p className="login-hint">
          Hệ thống sẽ chuyển hướng sang Google để xác thực an toàn.
          <br />
          Sau khi đăng nhập bạn sẽ được đưa về trang này.
        </p>

        <div className="login-disclaimer">
          <ShieldAlert width={14} height={14} />
          <span>
            Nội dung do AI cung cấp chỉ mang tính tham khảo, không thay thế ý kiến
            tư vấn chính thức của luật sư hoặc cơ quan nhà nước có thẩm quyền.
          </span>
        </div>
      </div>
    </div>
  );
}
