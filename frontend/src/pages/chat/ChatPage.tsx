import { useEffect, useRef, useState } from "react";
import {
  Scale,
  X,
  Menu,
  Plus,
  ChevronDown,
  LogOut,
  Trash2,
  Stamp,
  Send,
  Lock,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useChatStore, MAX_GUEST_MESSAGES, type Message } from "@/store/useChatStore";
import { chatService, type ChatSessionResponse } from "@/services/chatService";
import { authService } from "@/services/authService";
import { toast } from "sonner";

const SUGGESTIONS = [
  "Thủ tục ly hôn đơn phương cần giấy tờ gì?",
  "Mức phạt vượt đèn đỏ đối với xe máy năm nay?",
  "Soạn giúp tôi mẫu hợp đồng thuê nhà cơ bản",
  "Thời gian thử việc tối đa theo luật lao động là bao lâu?",
];

/** Tạo mã hồ sơ ngắn từ session_id để hiển thị UI */
function makeCodeFromId(id: string | null | undefined) {
  if (!id) return "HS-000";
  return "HS-" + String(id).split("-")[0].slice(0, 6).toUpperCase();
}

function initialsOf(name?: string | null) {
  return (name || "?")
    .split(" ")
    .filter(Boolean)
    .slice(-2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

/**
 * Trang Chat - layout y hệt frontend-vanilla-backup.
 *
 * Hỗ trợ 2 chế độ:
 *  - GUEST: dùng ngay, tối đa 3 tin nhắn. Khi hết → disable input + banner cảnh báo.
 *  - AUTHENTICATED: dùng backend chat-service, có sidebar lịch sử chat, sources, v.v.
 */
export default function ChatPage() {
  const { user, isAuthenticated, signOut } = useAuth();

  // Chat store
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const sending = useChatStore((s) => s.sending);
  const guestRemaining = useChatStore((s) => s.getGuestRemaining());
  const canSendGuest = useChatStore((s) => s.canSendGuestMessage());

  const setSessions = useChatStore((s) => s.setSessions);
  const addSession = useChatStore((s) => s.addSession);
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const addMessageLocal = useChatStore((s) => s.addMessage);
  const setSending = useChatStore((s) => s.setSending);
  const addGuestMessage = useChatStore((s) => s.addGuestMessage);
  const resetGuestChat = useChatStore((s) => s.resetGuestChat);
  const deleteSessionLocal = useChatStore((s) => s.deleteSession);

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  // Local state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const [input, setInput] = useState("");
  const [banner, setBanner] = useState<{ type: "error" | "info" | "warn"; text: string } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);

  // ── Khi authenticated, fetch lịch sử chat từ backend ───────────────────
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await chatService.getHistory();
        if (cancelled) return;
        setSessions(
          data.map((s) => ({
            id: s.id,
            title: s.title,
            createdAt: s.createdAt,
            updatedAt: s.updatedAt,
            messages: s.messages.map((m) => ({
              id: m.id,
              role: m.role,
              content: m.content,
              sources: m.sources,
              createdAt: m.createdAt,
            })),
          }))
        );
      } catch (err) {
        console.error("Không tải được lịch sử chat:", err);
        setBanner({ type: "error", text: "Không tải được lịch sử hồ sơ." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, setSessions]);

  // ── Auto-scroll xuống tin nhắn mới nhất ─────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.messages.length, sending]);

  // ── Đóng user menu khi click ra ngoài ───────────────────────────────────
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = () => setMenuOpen(false);
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, [menuOpen]);

  // ── Handlers ────────────────────────────────────────────────────────────
  const handleGoogleLogin = () => {
    window.location.href = authService.getGoogleOAuthUrl();
  };

  const handleSignOut = async () => {
    try {
      await signOut();
      resetGuestChat();
      setMenuOpen(false);
      toast.success("Đã đăng xuất");
    } catch {
      toast.error("Đăng xuất thất bại");
    }
  };

  const handleNewChat = async () => {
    if (!isAuthenticated) return;
    try {
      const newSession: ChatSessionResponse = await chatService.createSession(
        "Cuộc trò chuyện mới"
      );
      addSession({
        id: newSession.id,
        title: newSession.title,
        createdAt: newSession.createdAt,
        updatedAt: newSession.updatedAt,
        messages: [],
      });
      setBanner(null);
    } catch (err) {
      console.error(err);
      setBanner({ type: "error", text: "Không tạo được hồ sơ mới." });
    }
  };

  const handleDeleteChat = async (id: string, evt: React.MouseEvent) => {
    evt.stopPropagation();
    if (!confirm("Xóa hồ sơ này? Hành động không thể hoàn tác.")) return;
    try {
      await chatService.deleteSession(id);
      deleteSessionLocal(id);
    } catch (err) {
      console.error(err);
      setBanner({ type: "error", text: "Không xoá được hồ sơ." });
    }
  };

  // ── Gửi tin nhắn ───────────────────────────────────────────────────────
  const handleSend = async () => {
    const content = input.trim();
    if (!content || sending) return;

    setBanner(null);

    // ── GUEST MODE ────────────────────────────────────────────────────────
    if (!isAuthenticated) {
      if (!canSendGuest) {
        toast.warning(
          "Bạn đã dùng hết 3 lượt tin nhắn miễn phí. Vui lòng đăng nhập để tiếp tục.",
          { duration: 5000 }
        );
        return;
      }
      addGuestMessage(content);
      setInput("");
      const remaining = useChatStore.getState().getGuestRemaining();
      if (remaining === 0) {
        setTimeout(() => {
          setBanner({
            type: "warn",
            text: "Bạn đã hết lượt tin nhắn miễn phí. Đăng nhập để tiếp tục!",
          });
        }, 300);
      }
      return;
    }

    // ── AUTHENTICATED MODE ───────────────────────────────────────────────
    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        const newSession: ChatSessionResponse = await chatService.createSession(
          "Cuộc trò chuyện mới"
        );
        addSession({
          id: newSession.id,
          title: newSession.title,
          createdAt: newSession.createdAt,
          updatedAt: newSession.updatedAt,
          messages: [],
        });
        sessionId = newSession.id;
      } catch {
        setBanner({ type: "error", text: "Không tạo được phiên chat." });
        return;
      }
    }

    // Optimistic update
    const tempUserMsg: Message = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content,
      createdAt: new Date().toISOString(),
    };
    addMessageLocal(sessionId, tempUserMsg);
    setInput("");
    setSending(true);

    try {
      const updated = await chatService.sendMessage(sessionId, content);
      const messages = updated.messages.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        sources: m.sources,
        createdAt: m.createdAt,
      }));
      const currentSessions = useChatStore.getState().sessions;
      setSessions(
        currentSessions.map((s) =>
          s.id === sessionId ? { ...s, messages, updatedAt: updated.updatedAt } : s
        )
      );

      // Auto-rename session lần đầu tiên
      const session = currentSessions.find((s) => s.id === sessionId);
      if (session && session.title === "Cuộc trò chuyện mới") {
        const newTitle = content.slice(0, 40);
        try {
          await chatService.updateTitle(sessionId, newTitle);
          const refreshed = useChatStore.getState().sessions;
          setSessions(
            refreshed.map((s) =>
              s.id === sessionId ? { ...s, title: newTitle, messages } : s
            )
          );
        } catch {
          /* bỏ qua */
        }
      }
    } catch (err) {
      console.error(err);
      setBanner({ type: "error", text: "Gửi tin nhắn thất bại. Vui lòng thử lại." });
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSuggestionClick = (text: string) => {
    if (sending) return;
    setInput(text);
    setTimeout(() => {
      composerTextareaRef.current?.focus();
    }, 0);
  };

  // ── Render helpers ────────────────────────────────────────────────────
  const inputDisabled = sending || (!isAuthenticated && !canSendGuest);
  const firstName = (user?.name || "bạn").split(" ").pop() || "bạn";

  // ── JSX ────────────────────────────────────────────────────────────────
  return (
    <div className="app-shell">
      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      {isAuthenticated && (
        <aside className={`sidebar ${sidebarOpen ? "" : "closed"}`} id="sidebar">
          <div className="sidebar-header">
            <div className="icon-ring-sm">
              <Scale width={16} height={16} />
            </div>
            <span className="brand-name">Trợ Lý Pháp Luật</span>
            <button
              className="icon-btn close-btn"
              title="Đóng"
              onClick={() => setSidebarOpen(false)}
            >
              <X width={18} height={18} />
            </button>
          </div>

          <div className="new-chat-wrap">
            <button className="new-chat-btn" type="button" onClick={handleNewChat}>
              <Plus width={16} height={16} />
              <span>Hồ sơ mới</span>
            </button>
          </div>

          <div className="chat-list" id="chatList">
            <div className="chat-list-label">Hồ sơ tư vấn</div>
            <div id="chatListItems">
              {sessions.length === 0 ? (
                <div className="chat-empty">
                  Chưa có hồ sơ nào. Bấm "Hồ sơ mới" để bắt đầu.
                </div>
              ) : (
                sessions.map((c) => {
                  const isActive = c.id === activeSessionId;
                  return (
                    <div
                      key={c.id}
                      className={`chat-item-wrap ${isActive ? "active" : ""}`}
                    >
                      <button
                        className="chat-item"
                        type="button"
                        onClick={() => setActiveSession(c.id)}
                      >
                        <span className="code">
                          {makeCodeFromId(c.id)}
                        </span>
                        <span className="title">
                          {c.title || "Cuộc trò chuyện"}
                        </span>
                      </button>
                      <button
                        className="chat-delete-btn"
                        type="button"
                        onClick={(e) => handleDeleteChat(c.id, e)}
                        title="Xóa hồ sơ"
                      >
                        <Trash2 width={13} height={13} />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* ── User menu (sidebar) ──────────────────────────────── */}
          <div className="sidebar-user">
            <button
              className="user-row"
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen((v) => !v);
              }}
            >
              <span id="userAvatarSlot">
                {user?.picture ? (
                  <img
                    src={user.picture}
                    alt=""
                    className="user-avatar"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <div className="user-avatar">{initialsOf(user?.name)}</div>
                )}
              </span>
              <div className="user-meta">
                <div className="name">{user?.name || "Người dùng"}</div>
                <div className="email">{user?.email || ""}</div>
              </div>
              <ChevronDown width={15} height={15} />
            </button>
            {menuOpen && (
              <div className="user-menu">
                <button
                  className="logout-btn"
                  type="button"
                  onClick={handleSignOut}
                >
                  <LogOut width={15} height={15} />
                  <span>Đăng xuất</span>
                </button>
              </div>
            )}
          </div>
        </aside>
      )}

      {/* ── Main panel ───────────────────────────────────────────── */}
      <div className="main-panel">
        {/* Topbar */}
        <div className="topbar">
          <button
            className="icon-btn menu-toggle"
            title="Mở menu"
            onClick={() => setSidebarOpen((v) => !v)}
          >
            <Menu width={20} height={20} />
          </button>
          <div className="topbar-text">
            <div className="topbar-title">
              {activeSession?.title || "Cuộc trò chuyện mới"}
            </div>
            <div className="topbar-code">
              {activeSession ? makeCodeFromId(activeSession.id) : ""}
            </div>
          </div>

          {!isAuthenticated && (
            <div style={{ marginLeft: "auto" }}>
              <button
                type="button"
                onClick={handleGoogleLogin}
                className="google-btn"
                style={{ width: "auto", padding: "8px 16px", fontSize: 13 }}
              >
                <svg width="14" height="14" viewBox="0 0 48 48" aria-hidden="true">
                  <path
                    fill="#FFC107"
                    d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.6-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"
                  />
                </svg>
                Đăng nhập
              </button>
            </div>
          )}
        </div>

        {/* Banner */}
        {banner && (
          <div className={`banner ${banner.type}`}>{banner.text}</div>
        )}

        {/* Banner: guest hết lượt */}
        {!isAuthenticated && !canSendGuest && (
          <div className="banner warn">
            <Lock width={14} height={14} />
            <span>
              Bạn đã dùng hết 3 lượt tin nhắn miễn phí. Đăng nhập để tiếp tục.
            </span>
            <button
              type="button"
              className="google-btn ml-auto"
              style={{ width: "auto", padding: "6px 14px", fontSize: 12 }}
              onClick={handleGoogleLogin}
            >
              Đăng nhập
            </button>
          </div>
        )}

        {/* Messages area */}
        <div className="messages-area" id="messagesArea">
          {!activeSession || activeSession.messages.length === 0 ? (
            <div className="empty-state">
              <div className="icon-ring">
                <Stamp width={24} height={24} />
              </div>
              <h2>Xin chào, {firstName}</h2>
              <p>
                {isAuthenticated
                  ? "Đặt câu hỏi pháp lý, hoặc chọn một gợi ý bên dưới để bắt đầu."
                  : `Đặt câu hỏi pháp lý để dùng thử. Bạn còn ${guestRemaining}/${MAX_GUEST_MESSAGES} lượt miễn phí.`}
              </p>
              <div className="suggestions-grid">
                {SUGGESTIONS.map((s, i) => (
                  <button
                    key={i}
                    className="suggestion-btn"
                    type="button"
                    onClick={() => handleSuggestionClick(s)}
                    disabled={inputDisabled}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-thread">
              {activeSession.messages.map((m) => (
                <ChatBubble key={m.id} message={m} />
              ))}
              {sending && (
                <div className="message-row assistant">
                  <div className="stamp-avatar">
                    <Stamp width={14} height={14} />
                  </div>
                  <div className="typing-bubble">
                    <span className="typing-dot"></span>
                    <span className="typing-dot"></span>
                    <span className="typing-dot"></span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="composer">
          <div className="composer-inner">
            <div className="composer-box">
              <textarea
                ref={composerTextareaRef}
                id="messageInput"
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  !isAuthenticated && !canSendGuest
                    ? "Vui lòng đăng nhập để tiếp tục…"
                    : "Đặt câu hỏi pháp lý của bạn…"
                }
                disabled={inputDisabled}
                onInput={(e) => {
                  const ta = e.currentTarget;
                  ta.style.height = "auto";
                  ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
                }}
              />
              <button
                className="send-btn"
                id="sendBtn"
                type="button"
                disabled={!input.trim() || sending}
                onClick={handleSend}
                aria-label="Gửi"
              >
                <Send width={14} height={14} />
              </button>
            </div>
            <p className="composer-disclaimer">
              Thông tin do AI cung cấp chỉ mang tính tham khảo, không thay thế tư vấn pháp lý chính thức.
              {!isAuthenticated && canSendGuest && (
                <span style={{ marginLeft: 8 }}>
                  · Còn {guestRemaining}/{MAX_GUEST_MESSAGES} lượt miễn phí
                </span>
              )}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Chat bubble component ─────────────────────────────────────────────────
function ChatBubble({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="message-row user">
        <div className="message-col">
          <div className="bubble user">{message.content}</div>
        </div>
      </div>
    );
  }
  const sources = Array.isArray(message.sources) ? message.sources : [];
  return (
    <div className="message-row assistant">
      <div className="stamp-avatar">
        <Stamp width={14} height={14} />
      </div>
      <div className="message-col">
        <div className="bubble assistant">{message.content}</div>
        {sources.length > 0 && (
          <details className="sources-card">
            <summary>{sources.length} nguồn tham khảo</summary>
            <ul>
              {sources.map((s, i) => {
                const title =
                  (s as { law_title?: string }).law_title ||
                  (s as { law_document_type?: string }).law_document_type ||
                  (s as { citation?: string }).citation ||
                  (s as { title?: string }).title ||
                  (s as { url?: string }).url ||
                  "Nguồn";
                const score =
                  typeof (s as { score?: number }).score === "number" ? (
                    <span className="source-score">
                      {((s as { score: number }).score).toFixed(2)}
                    </span>
                  ) : null;
                return (
                  <li key={i}>
                    {title}
                    {score}
                  </li>
                );
              })}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}
