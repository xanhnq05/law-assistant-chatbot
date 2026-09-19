import { RAG_SERVICE_URL } from "@/lib/services";

/**
 * RAG service — gọi trực tiếp rag-service:8003 (không qua Vite proxy).
 *
 * Chỉ dùng cho GUEST MODE (browser → rag-service trực tiếp, không cần JWT).
 * Auth mode: chat-service gọi RAG nội bộ, frontend không cần gọi riêng.
 *
 * Note: gọi trực tiếp port 8003 từ browser có thể bị CORS nếu backend
 * không cho phép. rag-service đã whitelist localhost:5500/5173 nên OK.
 */

export interface RagSource {
  citation?: string;
  score?: number;
  context_block?: string;
  law_document_type?: string;
  law_document_number?: string;
  law_title?: string;
  [key: string]: unknown;
}

export interface RagResponse {
  answer: string;
  sources: RagSource[];
  verification?: {
    status: string;
    confidence: number;
    [key: string]: unknown;
  };
  debug?: Record<string, unknown>;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * Gửi câu hỏi → rag-service → trả answer + sources.
 *
 * @param question    Câu hỏi hiện tại
 * @param history     Lịch sử hội thoại gần đây (tối đa 6 msg = 3 cặp)
 * @param top_k       Số nguồn trích dẫn tối đa (mặc định 5)
 */
export async function ragAsk(
  question: string,
  history: HistoryMessage[] = [],
  top_k: number = 5
): Promise<RagResponse> {
  const res = await fetch(`${RAG_SERVICE_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, top_k, verify: false, history }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail || "RAG request failed");
  }
  return res.json() as Promise<RagResponse>;
}

/** Health check cho rag-service (dùng cho diagnostics) */
export async function ragPing(): Promise<boolean> {
  try {
    const res = await fetch(`${RAG_SERVICE_URL}/`, { method: "GET" });
    return res.ok;
  } catch {
    return false;
  }
}
