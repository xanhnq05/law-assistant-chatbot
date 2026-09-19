import { chatApi } from "@/lib/services";

/**
 * Chat service - gọi API tới chat-service (port 8002).
 *
 * Tất cả endpoints yêu cầu JWT (Authorization: Bearer token).
 * axios chatApi tự gắn token. Nếu 401 → caller handle (clear token, về guest).
 *
 * QUAN TRỌNG: Backend trả về field `message_id`, `session_id`, `created_at`
 * (snake_case). Frontend dùng `id`, `createdAt` (camelCase).
 */

export interface ChatSessionResponse {
  id: string;
  title: string;
  messages: ChatMessageResponse[];
  createdAt: string;
  updatedAt: string;
}

export interface ChatMessageResponse {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceResponse[];
  createdAt: string;
}

export interface SourceResponse {
  title?: string;
  url?: string;
  snippet?: string;
  score?: number;
}

const CHAT_API = {
  list: "/chats/",
  create: "/chats/",
  get: (id: string) => `/chats/${id}`,
  updateTitle: (id: string) => `/chats/${id}`,
  delete: (id: string) => `/chats/${id}`,
  addMessage: (sessionId: string) => `/chats/${sessionId}/messages`,
};

// ============================================================
// Mappers: snake_case (backend) → camelCase (frontend)
// ============================================================
function mapMessage(m: any): ChatMessageResponse {
  return {
    id: m.message_id ?? m.id ?? "",
    role: m.role,
    content: m.content,
    sources: m.sources,
    createdAt: m.created_at ?? m.createdAt ?? new Date().toISOString(),
  };
}

function mapSession(s: any): ChatSessionResponse {
  return {
    id: s.session_id ?? s.id ?? "",
    title: s.title ?? "Đoạn chat mới",
    messages: Array.isArray(s.messages) ? s.messages.map(mapMessage) : [],
    createdAt: s.created_at ?? s.createdAt ?? new Date().toISOString(),
    updatedAt: s.updated_at ?? s.updatedAt ?? new Date().toISOString(),
  };
}

export const chatService = {
  /** Lấy toàn bộ lịch sử chat của user */
  async getHistory(): Promise<ChatSessionResponse[]> {
    const { data } = await chatApi.get<any[]>(CHAT_API.list);
    return data.map(mapSession);
  },

  /** Tạo session chat mới */
  async createSession(title?: string): Promise<ChatSessionResponse> {
    const { data } = await chatApi.post<any>(CHAT_API.create, { title });
    return mapSession(data);
  },

  /** Lấy 1 session */
  async getSession(sessionId: string): Promise<ChatSessionResponse> {
    const { data } = await chatApi.get<any>(CHAT_API.get(sessionId));
    return mapSession(data);
  },

  /** Đổi title session */
  async updateTitle(
    sessionId: string,
    title: string
  ): Promise<ChatSessionResponse> {
    const { data } = await chatApi.patch<any>(CHAT_API.updateTitle(sessionId), {
      title,
    });
    return mapSession(data);
  },

  /** Xoá session */
  async deleteSession(sessionId: string): Promise<void> {
    await chatApi.delete(CHAT_API.delete(sessionId));
  },

  /** Gửi tin nhắn + nhận reply (RAG tự động sinh assistant message) */
  async sendMessage(
    sessionId: string,
    content: string
  ): Promise<ChatSessionResponse> {
    const { data } = await chatApi.post<any>(CHAT_API.addMessage(sessionId), {
      role: "user",
      content,
      sources: [],
    });
    return mapSession(data);
  },
};
