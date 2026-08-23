// ---------- CONFIG ----------
// Đổi thành URL server FastAPI thật khi deploy (vd: https://api.tro-ly-phap-luat.vn)
const API_BASE_URL = "http://localhost:8000";

const TOKEN_STORAGE_KEY = "tlpl_token";

const SUGGESTIONS = [
  "Thủ tục ly hôn đơn phương cần giấy tờ gì?",
  "Mức phạt vượt đèn đỏ đối với xe máy năm nay?",
  "Soạn giúp tôi mẫu hợp đồng thuê nhà cơ bản",
  "Thời gian thử việc tối đa theo luật lao động là bao lâu?",
];

// ---------- STATE ----------
const state = {
  booting: true, // đang kiểm tra token lúc mới load trang
  user: null,
  idToken: null,
  authError: null,
  chats: [], // {id, code, title, updated_at, messages?: [...]}  messages undefined = chưa tải chi tiết
  chatsLoading: false,
  activeChatId: null,
  input: "",
  loading: false,
  sidebarOpen: true,
  menuOpen: false,
};

const app = document.getElementById("app");

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function initialsOf(name) {
  return (name || "?")
    .split(" ")
    .filter(Boolean)
    .slice(-2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

function getActiveChat() {
  return state.chats.find((c) => c.id === state.activeChatId) || null;
}

// ---------- GỌI API (có kèm JWT) ----------
async function authFetch(path, options = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  if (state.idToken) headers["Authorization"] = `Bearer ${state.idToken}`;

  const res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    // Token hết hạn hoặc không hợp lệ -> đưa về màn đăng nhập
    handleLogout({ expired: true });
    throw new Error("Phiên đăng nhập đã hết hạn.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Lỗi ${res.status}`);
  }
  return res;
}

// ---------- KHỞI ĐỘNG ----------
// Xử lý 2 trường hợp khi trang vừa load:
// 1) Vừa được backend redirect về sau khi đăng nhập Google thành công -> URL có #token=...
// 2) Đã đăng nhập từ trước -> token còn lưu trong sessionStorage
async function boot() {
  const hashMatch = window.location.hash.match(/token=([^&]+)/);
  if (hashMatch) {
    state.idToken = decodeURIComponent(hashMatch[1]);
    sessionStorage.setItem(TOKEN_STORAGE_KEY, state.idToken);
    history.replaceState(null, "", window.location.pathname + window.location.search);
  } else {
    state.idToken = sessionStorage.getItem(TOKEN_STORAGE_KEY);
  }

  const params = new URLSearchParams(window.location.search);
  if (params.get("login_error")) {
    state.authError = "Đăng nhập Google không thành công. Vui lòng thử lại.";
    history.replaceState(null, "", window.location.pathname);
  }

  if (state.idToken) {
    try {
      const res = await authFetch("/auth/me");
      state.user = await res.json();
      await loadChats();
    } catch (err) {
      console.error(err);
      state.idToken = null;
      sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  }

  state.booting = false;
  render();
}

async function loadChats() {
  state.chatsLoading = true;
  try {
    const res = await authFetch("/chats");
    const list = await res.json();
    state.chats = list.map((c) => ({ ...c, messages: undefined }));
  } catch (err) {
    console.error(err);
  } finally {
    state.chatsLoading = false;
  }
}

// ---------- RENDER ----------
function render() {
  if (state.booting) {
    app.innerHTML = `<div class="login-screen"><p style="color:var(--text-muted);font-size:14px;">Đang tải…</p></div>`;
    return;
  }
  app.innerHTML = state.user ? renderAppShell() : renderLogin();
  if (window.lucide) lucide.createIcons();
  attachEvents();
  const scrollArea = document.querySelector(".messages-area");
  if (scrollArea) scrollArea.scrollTop = scrollArea.scrollHeight;
}

function renderLogin() {
  return `
    <div class="login-screen">
      <div class="login-card">
        <div class="login-brand">
          <div class="icon-ring"><i data-lucide="scale" width="28" height="28"></i></div>
          <h1>Trợ Lý Pháp Luật</h1>
          <p>Tra cứu &amp; giải đáp pháp lý Việt Nam bằng AI</p>
        </div>
        <button class="google-btn" id="googleLoginBtn">
          <svg width="18" height="18" viewBox="0 0 48 48">
            <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.6-6 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 15.7 18.9 13 24 13c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6 29.6 4 24 4 16.3 4 9.6 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.5 0 10.4-1.9 14.2-5.1l-6.6-5.4C29.6 35.4 26.9 36 24 36c-5.2 0-9.7-3.4-11.3-8.1l-6.6 5.1C9.5 39.6 16.2 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.3-4.1 5.7l6.6 5.4C41.1 36 44 30.6 44 24c0-1.3-.1-2.4-.4-3.5z"/>
          </svg>
          <span>Đăng nhập bằng Gmail</span>
        </button>
        ${
          state.authError
            ? `<div class="setup-notice"><strong>Không thể đăng nhập.</strong>${escapeHtml(state.authError)}</div>`
            : ""
        }
        <div class="login-disclaimer">
          <i data-lucide="shield-alert" width="14" height="14"></i>
          <span>Nội dung do AI cung cấp chỉ mang tính tham khảo, không thay thế ý kiến tư vấn chính thức của luật sư hoặc cơ quan nhà nước có thẩm quyền.</span>
        </div>
      </div>
    </div>
  `;
}

function renderAppShell() {
  const activeChat = getActiveChat();
  return `
    <div class="app-shell">
      ${renderSidebar()}
      <div class="main-panel">
        ${renderTopbar(activeChat)}
        <div class="messages-area">
          ${renderMessagesArea(activeChat)}
        </div>
        ${renderComposer()}
      </div>
    </div>
  `;
}

function renderMessagesArea(activeChat) {
  if (!activeChat) return renderEmptyState();
  if (activeChat.messages === undefined) {
    return `<div class="empty-state"><p style="color:var(--text-muted);font-size:14px;">Đang tải hội thoại…</p></div>`;
  }
  if (activeChat.messages.length === 0) return renderEmptyState();
  return renderThread(activeChat);
}

function renderSidebar() {
  return `
    <div class="sidebar ${state.sidebarOpen ? "" : "closed"}">
      <div class="sidebar-header">
        <div class="icon-ring-sm"><i data-lucide="scale" width="16" height="16"></i></div>
        <span class="brand-name">Trợ Lý Pháp Luật</span>
        <button class="close-btn" id="closeSidebarBtn"><i data-lucide="x" width="18" height="18"></i></button>
      </div>
      <div class="new-chat-wrap">
        <button class="new-chat-btn" id="newChatBtn"><i data-lucide="plus" width="16" height="16"></i> Hồ sơ mới</button>
      </div>
      <div class="chat-list">
        <div class="chat-list-label">Hồ sơ tư vấn</div>
        ${
          state.chatsLoading && state.chats.length === 0
            ? `<p style="padding:8px 12px;font-size:13px;color:var(--text-muted);">Đang tải hồ sơ…</p>`
            : state.chats
                .map(
                  (c) => `
          <div class="chat-item-wrap ${c.id === state.activeChatId ? "active" : ""}">
            <button class="chat-item" data-chat-id="${c.id}">
              <span class="code">${c.code || "HS-000"}</span>
              <span class="title">${escapeHtml(c.title)}</span>
            </button>
            <button class="chat-delete-btn" data-delete-id="${c.id}" title="Xóa hồ sơ">
              <i data-lucide="trash-2" width="13" height="13"></i>
            </button>
          </div>
        `
                )
                .join("")
        }
      </div>
      <div class="sidebar-user">
        <button class="user-row" id="userMenuBtn">
          ${
            state.user.picture
              ? `<img class="user-avatar" src="${state.user.picture}" alt="" referrerpolicy="no-referrer" />`
              : `<div class="user-avatar">${initialsOf(state.user.name)}</div>`
          }
          <div class="user-meta">
            <div class="name">${escapeHtml(state.user.name)}</div>
            <div class="email">${escapeHtml(state.user.email)}</div>
          </div>
          <i data-lucide="chevron-down" width="15" height="15"></i>
        </button>
        ${
          state.menuOpen
            ? `<div class="user-menu">
                <button class="logout-btn" id="logoutBtn"><i data-lucide="log-out" width="15" height="15"></i> Đăng xuất</button>
              </div>`
            : ""
        }
      </div>
    </div>
  `;
}

function renderTopbar(activeChat) {
  return `
    <div class="topbar">
      <button class="menu-toggle" id="toggleSidebarBtn"><i data-lucide="menu" width="20" height="20"></i></button>
      <div>
        <div class="topbar-title">${activeChat ? escapeHtml(activeChat.title) : "Cuộc trò chuyện mới"}</div>
        ${activeChat ? `<div class="topbar-code">${activeChat.code}</div>` : ""}
      </div>
    </div>
  `;
}

function renderEmptyState() {
  return `
    <div class="empty-state">
      <div class="icon-ring"><i data-lucide="stamp" width="24" height="24"></i></div>
      <h2>Xin chào, ${escapeHtml((state.user.name || "").split(" ").pop())}</h2>
      <p>Đặt câu hỏi pháp lý, hoặc chọn một gợi ý bên dưới để bắt đầu.</p>
      <div class="suggestions-grid">
        ${SUGGESTIONS.map((s) => `<button class="suggestion-btn" data-suggestion="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join("")}
      </div>
    </div>
  `;
}

function renderThread(chat) {
  const rows = chat.messages
    .map(
      (m) => `
      <div class="message-row ${m.role}">
        ${m.role === "assistant" ? `<div class="stamp-avatar"><i data-lucide="stamp" width="14" height="14"></i></div>` : ""}
        <div class="bubble ${m.role}">${escapeHtml(m.content)}</div>
      </div>
    `
    )
    .join("");

  const typing = state.loading
    ? `
      <div class="message-row assistant">
        <div class="stamp-avatar"><i data-lucide="stamp" width="14" height="14"></i></div>
        <div class="typing-bubble">
          <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
        </div>
      </div>
    `
    : "";

  return `<div class="chat-thread">${rows}${typing}</div>`;
}

function renderComposer() {
  return `
    <div class="composer">
      <div class="composer-inner">
        <div class="composer-box">
          <textarea id="messageInput" rows="1" placeholder="Đặt câu hỏi pháp lý của bạn…">${escapeHtml(state.input)}</textarea>
          <button class="send-btn" id="sendBtn" ${!state.input.trim() || state.loading ? "disabled" : ""}>
            <i data-lucide="send" width="14" height="14"></i>
          </button>
        </div>
        <p class="composer-disclaimer">Thông tin do AI cung cấp chỉ mang tính tham khảo, không thay thế tư vấn pháp lý chính thức.</p>
      </div>
    </div>
  `;
}

// ---------- EVENTS ----------
function attachEvents() {
  const googleLoginBtn = document.getElementById("googleLoginBtn");
  if (googleLoginBtn) googleLoginBtn.addEventListener("click", handleGoogleLoginRedirect);

  const newChatBtn = document.getElementById("newChatBtn");
  if (newChatBtn) newChatBtn.addEventListener("click", handleNewChat);

  const closeSidebarBtn = document.getElementById("closeSidebarBtn");
  if (closeSidebarBtn) closeSidebarBtn.addEventListener("click", () => { state.sidebarOpen = false; render(); });

  const toggleSidebarBtn = document.getElementById("toggleSidebarBtn");
  if (toggleSidebarBtn) toggleSidebarBtn.addEventListener("click", () => { state.sidebarOpen = !state.sidebarOpen; render(); });

  const userMenuBtn = document.getElementById("userMenuBtn");
  if (userMenuBtn) userMenuBtn.addEventListener("click", () => { state.menuOpen = !state.menuOpen; render(); });

  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) logoutBtn.addEventListener("click", () => handleLogout());

  document.querySelectorAll(".chat-item").forEach((btn) => {
    btn.addEventListener("click", () => selectChat(btn.getAttribute("data-chat-id")));
  });

  document.querySelectorAll(".chat-delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => handleDeleteChat(btn.getAttribute("data-delete-id"), e));
  });

  document.querySelectorAll(".suggestion-btn").forEach((btn) => {
    btn.addEventListener("click", () => handleSend(btn.getAttribute("data-suggestion")));
  });

  const messageInput = document.getElementById("messageInput");
  if (messageInput) {
    messageInput.addEventListener("input", (e) => {
      state.input = e.target.value;
      const sendBtn = document.getElementById("sendBtn");
      if (sendBtn) sendBtn.disabled = !state.input.trim() || state.loading;
    });
    messageInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    });
    messageInput.focus();
    messageInput.selectionStart = messageInput.selectionEnd = messageInput.value.length;
  }

  const sendBtn = document.getElementById("sendBtn");
  if (sendBtn) sendBtn.addEventListener("click", () => handleSend());
}

// ---------- AUTH ----------
// Đăng nhập thật: chuyển hẳn trình duyệt sang backend, backend chuyển tiếp sang Google.
// KHÔNG dùng fetch ở đây vì cần trình duyệt điều hướng thật (để nhận cookie state + redirect của Google).
function handleGoogleLoginRedirect() {
  window.location.href = `${API_BASE_URL}/auth/google/login`;
}

function handleLogout(opts = {}) {
  state.user = null;
  state.idToken = null;
  state.chats = [];
  state.activeChatId = null;
  state.menuOpen = false;
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  state.authError = opts.expired ? "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại." : null;
  render();
}

// ---------- CHAT ACTIONS ----------
async function selectChat(id) {
  state.activeChatId = id;
  render();
  const chat = state.chats.find((c) => c.id === id);
  if (chat && chat.messages === undefined) {
    try {
      const res = await authFetch(`/chats/${id}`);
      const full = await res.json();
      state.chats = state.chats.map((c) => (c.id === id ? full : c));
    } catch (err) {
      console.error(err);
    }
    render();
  }
}

async function handleNewChat() {
  try {
    const res = await authFetch("/chats", {
      method: "POST",
      body: JSON.stringify({ title: "Cuộc trò chuyện mới" }),
    });
    const chat = await res.json();
    state.chats = [chat, ...state.chats];
    state.activeChatId = chat.id;
    state.input = "";
    render();
  } catch (err) {
    console.error(err);
  }
}

async function handleDeleteChat(id, evt) {
  evt.stopPropagation();
  if (!confirm("Xóa hồ sơ này? Hành động không thể hoàn tác.")) return;
  try {
    await authFetch(`/chats/${id}`, { method: "DELETE" });
    state.chats = state.chats.filter((c) => c.id !== id);
    if (state.activeChatId === id) state.activeChatId = null;
    render();
  } catch (err) {
    console.error(err);
  }
}

async function handleSend(overrideText) {
  const text = (overrideText ?? state.input).trim();
  if (!text || state.loading) return;
  state.input = "";

  try {
    let chatId = state.activeChatId;

    if (!chatId) {
      const res = await authFetch("/chats", {
        method: "POST",
        body: JSON.stringify({ title: text.slice(0, 44) }),
      });
      const chat = await res.json();
      chatId = chat.id;
      state.chats = [chat, ...state.chats];
      state.activeChatId = chatId;
    }

    // Cập nhật lạc quan để người dùng thấy tin nhắn ngay, trước khi có phản hồi AI
    state.chats = state.chats.map((c) =>
      c.id === chatId ? { ...c, messages: [...(c.messages || []), { role: "user", content: text }] } : c
    );
    state.loading = true;
    render();

    const res2 = await authFetch(`/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: text }),
    });
    const fullChat = await res2.json();
    state.chats = state.chats.map((c) => (c.id === chatId ? fullChat : c));
  } catch (err) {
    console.error(err);
  } finally {
    state.loading = false;
    render();
  }
}

// ---------- INIT ----------
boot();
