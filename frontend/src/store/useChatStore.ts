import { create } from "zustand";
import { persist } from "zustand/middleware";

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

  // Guest chat (không cần backend)
  addGuestMessage: (content: string) => void;
  resetGuestChat: () => void;

  // Authenticated chat (cần backend)
  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  setActiveSession: (id: string | null) => void;
  addMessage: (sessionId: string, message: Message) => void;
  updateSessionTitle: (sessionId: string, title: string) => void;
  deleteSession: (sessionId: string) => void;
  setSending: (val: boolean) => void;

  // Guest limit helpers
  canSendGuestMessage: () => boolean;
  getGuestRemaining: () => number;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,
      guestMessageCount: 0,
      sending: false,

      // ── Guest ──────────────────────────────────────────────────────────────

      addGuestMessage(content: string) {
        const { guestMessageCount } = get();
        if (guestMessageCount >= MAX_GUEST_MESSAGES) return;

        const now = new Date().toISOString();
        const userMsg: Message = {
          id: `guest-${Date.now()}`,
          role: "user",
          content,
          createdAt: now,
        };

        // Auto-reply placeholder
        const assistantMsg: Message = {
          id: `guest-${Date.now()}-a`,
          role: "assistant",
          content:
            "Cảm ơn bạn! Đây là tin nhắn tự động từ chế độ guest. Vui lòng đăng nhập để tiếp tục trò chuyện.",
          createdAt: now,
        };

        set((state) => ({
          guestMessageCount: state.guestMessageCount + 1,
          // Guest dùng session tạm id = "guest"
          sessions:
            state.sessions.length === 0
              ? [
                  {
                    id: "guest",
                    title: "Cuộc trò chuyện",
                    messages: [userMsg, assistantMsg],
                    createdAt: now,
                    updatedAt: now,
                  },
                ]
              : state.sessions.map((s) =>
                  s.id === "guest"
                    ? {
                        ...s,
                        messages: [...s.messages, userMsg, assistantMsg],
                        updatedAt: now,
                      }
                    : s
                ),
          activeSessionId: state.activeSessionId ?? "guest",
        }));
      },

      resetGuestChat() {
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== "guest"),
          guestMessageCount: 0,
          activeSessionId:
            state.activeSessionId === "guest"
              ? null
              : state.activeSessionId,
        }));
      },

      // ── Authenticated ─────────────────────────────────────────────────────

      setSessions(sessions) {
        set({ sessions });
        if (sessions.length > 0 && !get().activeSessionId) {
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
    }),
    {
      name: "chat-storage",
      partialize: (state) => ({
        sessions: state.sessions,
        activeSessionId: state.activeSessionId,
        guestMessageCount: state.guestMessageCount,
      }),
    }
  )
);

export { MAX_GUEST_MESSAGES };
