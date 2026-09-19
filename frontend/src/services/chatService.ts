import { axiosInstance } from "@/lib/axios";

/**
 * Chat service - gọi API tới backend chat-service.
 *
 * Tất cả endpoints đều yêu cầu JWT (Authorization: Bearer token).
 * axiosInstance đã tự gắn token + handle refresh tự động.
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
  list: "/api/chats/",
  create: "/api/chats/",
  get: (id: string) => `/api/chats/${id}`,
  updateTitle: (id: string) => `/api/chats/${id}`,
  delete: (id: string) => `/api/chats/${id}`,
  addMessage: (sessionId: string) => `/api/chats/${sessionId}/messages`,
};

export const chatService = {
  /** Lấy toàn bộ lịch sử chat của user */
  async getHistory(): Promise<ChatSessionResponse[]> {
    const { data } = await axiosInstance.get<ChatSessionResponse[]>(CHAT_API.list);
    return data;
  },

  /** Tạo session chat mới */
  async createSession(title?: string): Promise<ChatSessionResponse> {
    const { data } = await axiosInstance.post<ChatSessionResponse>(
      CHAT_API.create,
      { title }
    );
    return data;
  },

  /** Lấy 1 session */
  async getSession(sessionId: string): Promise<ChatSessionResponse> {
    const { data } = await axiosInstance.get<ChatSessionResponse>(
      CHAT_API.get(sessionId)
    );
    return data;
  },

  /** Đổi title session */
  async updateTitle(
    sessionId: string,
    title: string
  ): Promise<ChatSessionResponse> {
    const { data } = await axiosInstance.patch<ChatSessionResponse>(
      CHAT_API.updateTitle(sessionId),
      { title }
    );
    return data;
  },

  /** Xoá session */
  async deleteSession(sessionId: string): Promise<void> {
    await axiosInstance.delete(CHAT_API.delete(sessionId));
  },

  /** Gửi tin nhắn + nhận reply (RAG tự động sinh assistant message) */
  async sendMessage(
    sessionId: string,
    content: string
  ): Promise<ChatSessionResponse> {
    const { data } = await axiosInstance.post<ChatSessionResponse>(
      CHAT_API.addMessage(sessionId),
      {
        role: "user",
        content,
        sources: [],
      }
    );
    return data;
  },
};
