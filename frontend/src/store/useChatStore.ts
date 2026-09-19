import { create } from "zustand";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceRef[];
  createdAt?: string;
}

export interface SourceRef {
  title?: string;
  url?: string;
  snippet?: string;
  score?: number;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: string;
  updatedAt: string;
}

const MAX_GUEST_MESSAGES = 3;

interface ChatState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  guestMessageCount: number;
  sending: boolean;

  // Guest chat (chỉ tồn tại trong tab hiện tại, không persist, không lưu DB)
  addGuestUserMessage: (content: string) => Message;
  addGuestAssistantMessage: (content: string, sources?: SourceRef[]) => void;
  resetGuestChat: () => void;

  // Authenticated chat (persist + DB)
  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  setActiveSession: (id: string | null) => void;
  addMessage: (sessionId: string, message: Message) => void;
  updateSessionTitle: (sessionId: string, title: string) => void;
  deleteSession: (sessionId: string) => void;
  setSending: (val: boolean) => void;
  clearAllSessions: () => void;

  // Guest helpers
  canSendGuestMessage: () => boolean;
  getGuestRemaining: () => number;
}

/**
 * Chat store — CHÚ Ý: KHÔNG dùng `persist` middleware nữa.
 *
 * Lý do:
 * - Guest session KHÔNG được persist (ChatGPT-style: reload = mất sạch).
 *   Nếu persist → sau reload vẫn thấy "Trò chuyện với AI" + messages cũ → trái UX.
 * - Auth sessions được quản lý qua backend (`GET /chats/`), nên không cần
 *   cache trong localStorage để tránh state drift.
 *
 * Mỗi lần load app, auth sessions sẽ được fetch lại từ backend (đã handle
 * trong ChatPage.useEffect). Guest session mặc định trống.
 */
export const useChatStore = create<ChatState>()((set, get) => ({
  sessions: [],
  activeSessionId: null,
  guestMessageCount: 0,
  sending: false,

  // ── Guest ──────────────────────────────────────────────────────────────

  addGuestUserMessage(content: string): Message {
    const { guestMessageCount } = get();
    if (guestMessageCount >= MAX_GUEST_MESSAGES) {
      throw new Error("Guest message limit reached");
    }

    const now = new Date().toISOString();
    const userMsg: Message = {
      id: `guest-${Date.now()}`,
      role: "user",
      content,
      createdAt: now,
    };

    set((state) => ({
      guestMessageCount: state.guestMessageCount + 1,
      sessions:
        state.sessions.length === 0 ||
        state.sessions.every((s) => s.id !== "guest")
          ? [
              {
                id: "guest",
                title: "Trò chuyện với AI",
                messages: [userMsg],
                createdAt: now,
                updatedAt: now,
              },
            ]
          : state.sessions.map((s) =>
              s.id === "guest"
                ? { ...s, messages: [...s.messages, userMsg], updatedAt: now }
                : s
            ),
      activeSessionId: "guest",
    }));

    return userMsg;
  },

  addGuestAssistantMessage(content: string, sources?: SourceRef[]) {
    const now = new Date().toISOString();
    const assistantMsg: Message = {
      id: `guest-${Date.now()}`,
      role: "assistant",
      content,
      sources,
      createdAt: now,
    };

    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === "guest"
          ? { ...s, messages: [...s.messages, assistantMsg], updatedAt: now }
          : s
      ),
    }));
  },

  resetGuestChat() {
    set({
      sessions: get().sessions.filter((s) => s.id !== "guest"),
      guestMessageCount: 0,
      activeSessionId: get().activeSessionId === "guest" ? null : get().activeSessionId,
    });
  },

  // ── Authenticated ─────────────────────────────────────────────────────

  setSessions(sessions) {
    set({ sessions });
    // Không auto-set activeSessionId nếu đã có session khác (guest)
    const currentActive = get().activeSessionId;
    if (
      sessions.length > 0 &&
      (!currentActive ||
        currentActive === "guest" ||
        !sessions.find((s) => s.id === currentActive))
    ) {
      set({ activeSessionId: sessions[0].id });
    }
  },

  addSession(session) {
    set((state) => ({
      sessions: [session, ...state.sessions],
      activeSessionId: session.id,
    }));
  },

  setActiveSession(id) {
    set({ activeSessionId: id });
  },

  addMessage(sessionId, message) {
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === sessionId
          ? {
              ...s,
              messages: [...s.messages, message],
              updatedAt: new Date().toISOString(),
            }
          : s
      ),
    }));
  },

  updateSessionTitle(sessionId, title) {
    set((state) => ({
      sessions: state.sessions.map((s) =>
        s.id === sessionId ? { ...s, title } : s
      ),
    }));
  },

  deleteSession(sessionId) {
    set((state) => {
      const remaining = state.sessions.filter((s) => s.id !== sessionId);
      return {
        sessions: remaining,
        activeSessionId:
          state.activeSessionId === sessionId
            ? remaining[0]?.id ?? null
            : state.activeSessionId,
      };
    });
  },

  clearAllSessions() {
    set({
      sessions: [],
      activeSessionId: null,
      guestMessageCount: 0,
    });
  },

  setSending(val) {
    set({ sending: val });
  },

  // ── Guest helpers ──────────────────────────────────────────────────────

  canSendGuestMessage() {
    return get().guestMessageCount < MAX_GUEST_MESSAGES;
  },

  getGuestRemaining() {
    return Math.max(0, MAX_GUEST_MESSAGES - get().guestMessageCount);
  },
}));

export { MAX_GUEST_MESSAGES };
