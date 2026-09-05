/* ============================================================
   Trợ Lý Pháp Luật - Frontend (vanilla JS, không cần bundler)

   Cách chạy (một trong hai):
     1. Mở file qua http-server:
        cd frontend
        python -m http.server 5500
        -> mở http://localhost:5500

     2. Mở trực tiếp file index.html trong trình duyệt (file://):
        Tốt nhất nên chạy qua http-server để CORS / cookie chạy đúng.
   ============================================================ */

(() => {
  "use strict";

  // ---------- CONFIG ----------
  // URL backend được inject runtime qua /config.js (xem frontend/Dockerfile).
  // Nếu không có window.__APP_CONFIG__ thì fallback về localhost:8080
  // (port frontend container trong docker-compose).
  const API_BASE_URL =
    (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_BASE_URL) ||
    "http://localhost:8080";

  const TOKEN_STORAGE_KEY = "tlpl_token";
  const USER_STORAGE_KEY = "tlpl_user";

  const SUGGESTIONS = [
    "Thủ tục ly hôn đơn phương cần giấy tờ gì?",
    "Mức phạt vượt đèn đỏ đối với xe máy năm nay?",
    "Soạn giúp tôi mẫu hợp đồng thuê nhà cơ bản",
    "Thời gian thử việc tối đa theo luật lao động là bao lâu?",
  ];

  // ---------- STATE ----------
  const state = {
    booting: true,
    user: null,
    token: null,
    authError: null,
    chats: [],          // [{session_id, title, messages?: [], ...}]
    chatsLoading: false,
    activeChatId: null,
    input: "",
    loading: false,
    sidebarOpen: true,
    menuOpen: false,
    banner: null,       // {type:'error'|'info', text:string}
  };

  // ---------- HELPERS ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

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
    return state.chats.find((c) => c.session_id === state.activeChatId) || null;
  }

  function makeCodeFromId(id) {
    // Tạo mã hồ sơ ngắn từ session_id để hiển thị UI.
    if (!id) return "HS-000";
    return "HS-" + String(id).split("-")[0].slice(0, 6).toUpperCase();
  }

  function setBanner(type, text) {
    state.banner = text ? { type, text } : null;
    renderBanner();
  }

  // ---------- API ----------
  async function authFetch(path, options = {}) {
    const headers = Object.assign(
      { "Content-Type": "application/json" },
      options.headers || {}
    );
    if (state.token) headers["Authorization"] = `Bearer ${state.token}`;

    let res;
    try {
      res = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    } catch (err) {
      throw new Error(
        `Không kết nối được tới backend (${API_BASE_URL}). Hãy chắc chắn các service đang chạy.`
      );
    }

    if (res.status === 401) {
      handleLogout({ expired: true });
      throw new Error("Phiên đăng nhập đã hết hạn.");
    }
    if (!res.ok) {
      let detail = `Lỗi ${res.status}`;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch (_) {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res;
  }

  // ---------- BOOT ----------
  async function boot() {
    // 1) Đọc token từ hash hoặc sessionStorage
    const hashMatch = window.location.hash.match(/token=([^&]+)/);
    if (hashMatch) {
      state.token = decodeURIComponent(hashMatch[1]);
      sessionStorage.setItem(TOKEN_STORAGE_KEY, state.token);
      // Xoá hash khỏi URL nhưng vẫn giữ nguyên query
      history.replaceState(null, "", window.location.pathname + window.location.search);
    } else {
      state.token = sessionStorage.getItem(TOKEN_STORAGE_KEY);
    }

    // 2) Đọc login_error từ query
    const params = new URLSearchParams(window.location.search);
    if (params.get("login_error")) {
      state.authError = params.get("login_error");
      history.replaceState(null, "", window.location.pathname);
    }

    // 3) Thử dùng cache user để render ngay
    try {
      const cached = sessionStorage.getItem(USER_STORAGE_KEY);
      if (cached) state.user = JSON.parse(cached);
    } catch (_) { state.user = null; }

    // 4) Nếu có token, xác minh qua /auth/me
    if (state.token) {
      try {
        const res = await authFetch("/auth/me");
        state.user = await res.json();
        sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(state.user));
      } catch (err) {
        console.error(err);
        state.token = null;
        sessionStorage.removeItem(TOKEN_STORAGE_KEY);
        state.user = null;
      }
    }

    state.booting = false;
    render();
    if (state.user) loadChats();
  }

  async function loadChats() {
    state.chatsLoading = true;
    renderChatList();
    try {
      const res = await authFetch("/chats");
      const list = await res.json();
      // Chuẩn hoá field cho client
      state.chats = (list || []).map((c) => ({
        ...c,
        messages: c.messages || [],
        code: c.code || makeCodeFromId(c.session_id),
      }));
      // Cache session đầu tiên làm active nếu chưa có
      if (!state.activeChatId && state.chats.length > 0) {
        state.activeChatId = state.chats[0].session_id;
      }
    } catch (err) {
      console.error(err);
      setBanner("error", err.message);
    } finally {
      state.chatsLoading = false;
      renderChatList();
      renderMessagesArea();
    }
  }

  // ---------- AUTH ----------
  function handleGoogleLogin() {
    // Chuyển trình duyệt sang backend -> Google -> backend callback -> redirect về đây
    window.location.href = `${API_BASE_URL}/auth/google/login`;
  }

  function handleLogout(opts = {}) {
    state.user = null;
    state.token = null;
    state.chats = [];
    state.activeChatId = null;
    state.menuOpen = false;
    sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    sessionStorage.removeItem(USER_STORAGE_KEY);
    state.authError = opts.expired
      ? "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại."
      : null;
    render();
  }

  // ---------- CHAT ACTIONS ----------
  async function selectChat(id) {
    state.activeChatId = id;
    renderMessagesArea();
    renderTopbar();
    renderChatList();
    const chat = state.chats.find((c) => c.session_id === id);
    if (chat && (chat.messages === undefined || chat.messages === null)) {
      try {
        const res = await authFetch(`/chats/${id}`);
        const full = await res.json();
        state.chats = state.chats.map((c) =>
          c.session_id === id ? { ...c, ...full, messages: full.messages || [] } : c
        );
        renderMessagesArea();
      } catch (err) {
        console.error(err);
        setBanner("error", err.message);
      }
    }
  }

  async function handleNewChat() {
    try {
      const res = await authFetch("/chats", {
        method: "POST",
        body: JSON.stringify({ title: "Cuộc trò chuyện mới" }),
      });
      const chat = await res.json();
      chat.messages = chat.messages || [];
      chat.code = makeCodeFromId(chat.session_id);
      state.chats = [chat, ...state.chats];
      state.activeChatId = chat.session_id;
      state.menuOpen = false;
      setBanner(null);
      render();
    } catch (err) {
      console.error(err);
      setBanner("error", err.message);
    }
  }

  async function handleDeleteChat(id, evt) {
    evt.stopPropagation();
    if (!confirm("Xóa hồ sơ này? Hành động không thể hoàn tác.")) return;
    try {
      await authFetch(`/chats/${id}`, { method: "DELETE" });
      state.chats = state.chats.filter((c) => c.session_id !== id);
      if (state.activeChatId === id) state.activeChatId = null;
      renderChatList();
      renderMessagesArea();
      renderTopbar();
    } catch (err) {
      console.error(err);
      setBanner("error", err.message);
    }
  }

  async function handleSend() {
    const text = state.input.trim();
    if (!text || state.loading) return;

    setBanner(null);
    state.input = "";
    const sendBtn = $("#sendBtn");
    if (sendBtn) sendBtn.disabled = true;
    const ta = $("#messageInput");
    if (ta) ta.value = "";

    try {
      let chatId = state.activeChatId;

      // Nếu chưa có session active thì tạo mới
      if (!chatId) {
        const res = await authFetch("/chats", {
          method: "POST",
          body: JSON.stringify({ title: text.slice(0, 44) }),
        });
        const newChat = await res.json();
        newChat.messages = [];
        newChat.code = makeCodeFromId(newChat.session_id);
        chatId = newChat.session_id;
        state.chats = [newChat, ...state.chats];
        state.activeChatId = chatId;
      }

      // Optimistic update: thêm message user vào UI trước
      upsertLocalMessage(chatId, {
        message_id: "tmp-" + Date.now(),
        role: "user",
        content: text,
        sources: [],
        created_at: new Date().toISOString(),
      });

      state.loading = true;
      renderMessagesArea();
      renderTopbar();
      renderChatList();

      // Gửi message tới backend; backend sẽ tự gọi RAG tạo assistant message
      const res2 = await authFetch(`/chats/${chatId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: text }),
      });
      const fullChat = await res2.json();
      fullChat.messages = fullChat.messages || [];
      fullChat.code = makeCodeFromId(fullChat.session_id);

      state.chats = state.chats.map((c) =>
        c.session_id === chatId
          ? { ...c, ...fullChat, messages: fullChat.messages }
          : c
      );
    } catch (err) {
      console.error(err);
      setBanner("error", err.message);
    } finally {
      state.loading = false;
      const sendBtn2 = $("#sendBtn");
      if (sendBtn2) sendBtn2.disabled = true;
      render();
    }
  }

  function upsertLocalMessage(chatId, msg) {
    state.chats = state.chats.map((c) => {
      if (c.session_id !== chatId) return c;
      const messages = c.messages ? [...c.messages] : [];
      // Nếu message tạm trùng id thì replace
      const idx = messages.findIndex((m) => m.message_id === msg.message_id);
      if (idx >= 0) messages[idx] = msg;
      else messages.push(msg);
      return {
        ...c,
        messages,
        metadata: { ...(c.metadata || {}), message_count: messages.length },
      };
    });
  }

  // ---------- RENDER ----------
  const app = $("#app");

  function render() {
    if (state.booting) {
      app.innerHTML = `<div class="login-screen"><p style="color:var(--text-muted);font-size:14px;">Đang tải…</p></div>`;
      return;
    }
    if (state.user) {
      renderAppShell();
    } else {
      renderLogin();
    }
    ensureLucideIcons();
    autoscroll();
  }

  function ensureLucideIcons() {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      try { window.lucide.createIcons(); } catch (_) {}
    }
  }

  function renderLogin() {
    const tpl = $("#login-template").content.cloneNode(true);
    app.innerHTML = "";
    app.appendChild(tpl);

    if (state.authError) {
      const card = $(".login-card", app);
      const notice = document.createElement("div");
      notice.className = "setup-notice";
      notice.innerHTML = `<strong>Không thể đăng nhập</strong>${escapeHtml(state.authError)}`;
      const hintEl = $(".login-hint", app);
      if (hintEl) {
        card.insertBefore(notice, hintEl.nextSibling);
      } else {
        card.appendChild(notice);
      }
    }

    $("#googleLoginBtn", app).addEventListener("click", handleGoogleLogin);
  }

  function renderAppShell() {
    const tpl = $("#app-shell-template").content.cloneNode(true);
    app.innerHTML = "";
    app.appendChild(tpl);

    // Sidebar toggling
    const sidebar = $("#sidebar", app);
    if (!state.sidebarOpen) sidebar.classList.add("closed");

    $("#closeSidebarBtn", app).addEventListener("click", () => {
      state.sidebarOpen = false;
      sidebar.classList.add("closed");
    });
    $("#toggleSidebarBtn", app).addEventListener("click", () => {
      state.sidebarOpen = !state.sidebarOpen;
      sidebar.classList.toggle("closed", !state.sidebarOpen);
    });
    $("#newChatBtn", app).addEventListener("click", handleNewChat);

    // User
    const userBtn = $("#userMenuBtn", app);
    const userMenu = $("#userMenu", app);
    if (state.user) {
      const slot = $("#userAvatarSlot", app);
      if (state.user.picture) {
        const img = document.createElement("img");
        img.className = "user-avatar";
        img.src = state.user.picture;
        img.alt = "";
        img.referrerPolicy = "no-referrer";
        slot.appendChild(img);
      } else {
        const div = document.createElement("div");
        div.className = "user-avatar";
        div.textContent = initialsOf(state.user.name);
        slot.appendChild(div);
      }
      $("#userName", app).textContent = state.user.name || "Người dùng";
      $("#userEmail", app).textContent = state.user.email || "";
    }
    userBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      state.menuOpen = !state.menuOpen;
      userMenu.hidden = !state.menuOpen;
    });
    $("#logoutBtn", app).addEventListener("click", () => handleLogout());

    // Đóng menu user khi click ra ngoài
    document.addEventListener("click", closeUserMenuOnOutside);
    function closeUserMenuOnOutside(ev) {
      if (!state.menuOpen) return;
      if (!userMenu.contains(ev.target) && !userBtn.contains(ev.target)) {
        state.menuOpen = false;
        userMenu.hidden = true;
      }
    }

    renderTopbar();
    renderChatList();
    renderMessagesArea();
    renderComposer();
    renderBanner();
  }

  function renderTopbar() {
    const active = getActiveChat();
    const titleEl = $("#topbarTitle");
    const codeEl = $("#topbarCode");
    if (!titleEl) return;
    if (active) {
      titleEl.textContent = active.title || "Cuộc trò chuyện mới";
      codeEl.textContent = active.code || makeCodeFromId(active.session_id);
    } else {
      titleEl.textContent = "Cuộc trò chuyện mới";
      codeEl.textContent = "";
    }
  }

  function renderChatList() {
    const list = $("#chatListItems");
    if (!list) return;

    if (state.chatsLoading && state.chats.length === 0) {
      list.innerHTML = `<div class="chat-empty">Đang tải hồ sơ…</div>`;
      return;
    }
    if (state.chats.length === 0) {
      list.innerHTML = `<div class="chat-empty">Chưa có hồ sơ nào. Bấm "Hồ sơ mới" để bắt đầu.</div>`;
      return;
    }

    list.innerHTML = state.chats
      .map((c) => {
        const isActive = c.session_id === state.activeChatId;
        return `
          <div class="chat-item-wrap ${isActive ? "active" : ""}" data-chat-id="${c.session_id}">
            <button class="chat-item" type="button" data-action="open" data-chat-id="${c.session_id}">
              <span class="code">${escapeHtml(c.code || makeCodeFromId(c.session_id))}</span>
              <span class="title">${escapeHtml(c.title || "Cuộc trò chuyện mới")}</span>
            </button>
            <button class="chat-delete-btn" type="button" data-action="delete" data-chat-id="${c.session_id}" title="Xóa hồ sơ">
              <i data-lucide="trash-2" width="13" height="13"></i>
            </button>
          </div>
        `;
      })
      .join("");

    // Re-bind events
    $$(".chat-item", list).forEach((el) => {
      el.addEventListener("click", () => selectChat(el.dataset.chatId));
    });
    $$(".chat-delete-btn", list).forEach((el) => {
      el.addEventListener("click", (e) => handleDeleteChat(el.dataset.chatId, e));
    });
    ensureLucideIcons();
  }

  function renderMessagesArea() {
    const area = $("#messagesArea");
    if (!area) return;

    const active = getActiveChat();

    if (!active) {
      area.innerHTML = renderEmptyState();
      ensureLucideIcons();
      bindSuggestionButtons();
      return;
    }

    if (!active.messages || active.messages.length === 0) {
      area.innerHTML = renderEmptyState();
      ensureLucideIcons();
      bindSuggestionButtons();
      return;
    }

    area.innerHTML = `<div class="chat-thread">${renderThread(active)}${
      state.loading ? renderTyping() : ""
    }</div>`;

    ensureLucideIcons();
  }

  function renderEmptyState() {
    const firstName = (state.user?.name || "bạn").split(" ").pop();
    return `
      <div class="empty-state">
        <div class="icon-ring"><i data-lucide="stamp" width="24" height="24"></i></div>
        <h2>Xin chào, ${escapeHtml(firstName)}</h2>
        <p>Đặt câu hỏi pháp lý, hoặc chọn một gợi ý bên dưới để bắt đầu.</p>
        <div class="suggestions-grid">
          ${SUGGESTIONS.map(
            (s) =>
              `<button class="suggestion-btn" type="button" data-suggestion="${escapeHtml(s)}">${escapeHtml(s)}</button>`
          ).join("")}
        </div>
      </div>
    `;
  }

  function bindSuggestionButtons() {
    $$(".suggestion-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const text = btn.getAttribute("data-suggestion") || "";
        if (state.loading) return;
        state.input = text;
        const ta = $("#messageInput");
        if (ta) ta.value = text;
        handleSend();
      });
    });
  }

  function renderThread(chat) {
    return chat.messages
      .map((m) => {
        if (m.role === "user") {
          return `
            <div class="message-row user">
              <div class="message-col">
                <div class="bubble user">${escapeHtml(m.content)}</div>
              </div>
            </div>
          `;
        }
        if (m.role === "assistant") {
          const sources = Array.isArray(m.sources) ? m.sources : [];
          let sourcesHtml = "";
          if (sources.length > 0) {
            sourcesHtml = `
              <details class="sources-card">
                <summary>${sources.length} nguồn tham khảo</summary>
                <ul>
                  ${sources
                    .map((s) => {
                      const title =
                        s.law_title ||
                        s.law_document_type ||
                        s.citation ||
                        "Nguồn";
                      const score =
                        typeof s.score === "number"
                          ? `<span class="source-score">${s.score.toFixed(2)}</span>`
                          : "";
                      return `<li>${escapeHtml(title)}${score}</li>`;
                    })
                    .join("")}
                </ul>
              </details>
            `;
          }
          return `
            <div class="message-row assistant">
              <div class="stamp-avatar"><i data-lucide="stamp" width="14" height="14"></i></div>
              <div class="message-col">
                <div class="bubble assistant">${escapeHtml(m.content)}</div>
                ${sourcesHtml}
              </div>
            </div>
          `;
        }
        // system hoặc khác
        return `
          <div class="message-row assistant">
            <div class="message-col">
              <div class="bubble assistant">${escapeHtml(m.content)}</div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderTyping() {
    return `
      <div class="message-row assistant">
        <div class="stamp-avatar"><i data-lucide="stamp" width="14" height="14"></i></div>
        <div class="typing-bubble">
          <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
        </div>
      </div>
    `;
  }

  function renderComposer() {
    const ta = $("#messageInput");
    const sendBtn = $("#sendBtn");
    if (!ta || !sendBtn) return;

    ta.value = state.input;
    sendBtn.disabled = !state.input.trim() || state.loading;

    ta.oninput = (e) => {
      state.input = e.target.value;
      const btn = $("#sendBtn");
      if (btn) btn.disabled = !state.input.trim() || state.loading;
      autoResize(ta);
    };
    ta.onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    };
    sendBtn.onclick = () => handleSend();
    autoResize(ta);
    setTimeout(() => ta.focus(), 0);
  }

  function autoResize(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
  }

  function renderBanner() {
    const existing = $("#appBanner");
    if (existing) existing.remove();
    if (!state.banner) return;

    const main = $(".main-panel") || app;
    const banner = document.createElement("div");
    banner.id = "appBanner";
    banner.className = `banner ${state.banner.type}`;
    banner.textContent = state.banner.text;
    main.prepend(banner);
  }

  function autoscroll() {
    const area = $("#messagesArea");
    if (area) area.scrollTop = area.scrollHeight;
  }

  // ---------- START ----------
  document.addEventListener("DOMContentLoaded", boot);
})();