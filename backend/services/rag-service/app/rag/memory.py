"""
Conversation Memory — In-session memory layer.

Theo PDF "tổng hợp sửa đổi các bước":
  - Hệ thống hỗ trợ nhớ ngữ cảnh trong cùng phiên chat.
  - Không đưa toàn bộ lịch sử vào prompt mỗi lần. Thiết kế gồm:
      Recent Messages + Conversation Summary
  - Memory chỉ giúp hiểu ngữ cảnh, KHÔNG dùng làm nguồn pháp luật.
  - Lưu trữ: MongoDB (theo PDF), nhưng đợt này dùng in-process store
    (TTL + max messages) — khi nào integrate MongoDB sẽ làm sau.

Public API:
  - memory_store: singleton ConversationMemory (in-process).
  - get_history_for_session(session_id) -> list[dict]
  - add_message(session_id, role, content, metadata=None)
  - summarize_session(session_id) -> str  (tóm tắt để đưa cho B2/Follow-up)

Thiết kế:
  - Session = 1 phiên chat (định danh bằng session_id).
  - Mỗi session có:
      messages: list[{role, content, ts, metadata}]
      summary:  str (optional - rolling summary của các turn cũ)
      created_at, updated_at
  - Max messages: MAX_MESSAGES_PER_SESSION (FIFO trimming)
  - TTL:        SESSION_TTL_SECONDS (auto cleanup)
  - Concurrency: dùng threading.Lock cho thread-safe.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("rag-service")


# ============================================================
# CONFIG (có thể override qua ENV sau)
# ============================================================
MAX_MESSAGES_PER_SESSION = 20            # giữ 20 msg gần nhất = 10 cặp
MAX_HISTORY_FOR_QUERY = 6                # chỉ gửi 6 msg = 3 cặp cho B2
SESSION_TTL_SECONDS = 60 * 60 * 2        # 2 giờ idle → auto cleanup
SUMMARY_THRESHOLD_MESSAGES = 8           # từ msg thứ 8 trở đi sẽ tóm tắt


# ============================================================
# DATA MODEL
# ============================================================
@dataclass
class Session:
    """Một phiên chat trong memory."""
    session_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_history(self, max_msgs: int = MAX_HISTORY_FOR_QUERY) -> list[dict[str, str]]:
        """Trả về format {role, content} tương thích ChatRequest.history."""
        recent = self.messages[-max_msgs:]
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    def get_messages(self) -> list[dict[str, Any]]:
        """Trả về toàn bộ messages (raw, kèm ts/metadata). Cho internal/test."""
        return list(self.messages)


# ============================================================
# CONVERSATION MEMORY (in-process store)
# ============================================================
class ConversationMemory:
    """
    Singleton in-memory store cho conversation memory.

    Lưu ý: Đây là implementation IN-PROCESS dùng cho development/testing.
    Production nên tích hợp MongoDB (theo PDF) - xem notes ở cuối file.
    """

    _instance: "ConversationMemory | None" = None
    _lock_inst = threading.Lock()

    def __new__(cls) -> "ConversationMemory":
        # Singleton pattern thread-safe
        if cls._instance is None:
            with cls._lock_inst:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()
        self._initialized = True
        log.info("ConversationMemory initialized (in-process store).")

    # ============================================================
    # SESSION OPS
    # ============================================================
    def get_or_create(self, session_id: str) -> Session:
        """Lấy session nếu có, tạo mới nếu không. Auto-cleanup expired sessions."""
        if not session_id:
            session_id = "default"
        with self._lock:
            self._cleanup_expired()
            sess = self._sessions.get(session_id)
            if sess is None:
                sess = Session(session_id=session_id)
                self._sessions[session_id] = sess
            sess.updated_at = time.time()
            return sess

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def get_session_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Lấy toàn bộ messages (raw) của 1 session (cho test/debug)."""
        sess = self.get(session_id)
        if sess is None:
            return []
        return sess.get_messages()

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def stats(self) -> dict[str, Any]:
        """Snapshot stats (cho debug)."""
        with self._lock:
            return {
                "session_count": len(self._sessions),
                "sessions": [
                    {
                        "session_id": s.session_id,
                        "message_count": len(s.messages),
                        "has_summary": bool(s.summary),
                        "updated_at": s.updated_at,
                    }
                    for s in self._sessions.values()
                ],
            }

    # ============================================================
    # MESSAGE OPS
    # ============================================================
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Thêm 1 message vào session.

        Args:
            session_id: id của session.
            role:       "user" | "assistant".
            content:    nội dung text.
            metadata:   optional (vd: retrieval_policy, evidence_count,...).
        """
        sess = self.get_or_create(session_id)
        with self._lock:
            sess.messages.append({
                "role": role,
                "content": content,
                "ts": time.time(),
                "metadata": dict(metadata or {}),
            })
            sess.updated_at = time.time()

            # FIFO trim
            if len(sess.messages) > MAX_MESSAGES_PER_SESSION:
                sess.messages = sess.messages[-MAX_MESSAGES_PER_SESSION:]

            # Nếu quá nhiều msg → đánh dấu cần summarize (lazy — sẽ chạy khi get_history)
            if len(sess.messages) >= SUMMARY_THRESHOLD_MESSAGES and not sess.summary:
                sess.metadata["needs_summary"] = True

    def add_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        **metadata: Any,
    ) -> None:
        """Convenience: add cả 1 cặp user/assistant cùng lúc."""
        self.add_message(session_id, "user", user_message, metadata)
        self.add_message(session_id, "assistant", assistant_message, metadata)

    # ============================================================
    # RETRIEVE FOR QUERY
    # ============================================================
    def get_history_for_query(
        self,
        session_id: str,
        max_msgs: int = MAX_HISTORY_FOR_QUERY,
    ) -> list[dict[str, str]]:
        """Lấy history format {role, content} (cho ChatRequest.history)."""
        sess = self.get(session_id)
        if sess is None:
            return []
        return sess.to_history(max_msgs)

    def get_context_summary(self, session_id: str) -> str:
        """Trả về summary của session (nếu có)."""
        sess = self.get(session_id)
        if sess is None:
            return ""
        return sess.summary

    # ============================================================
    # SUMMARIZATION (MỚI)
    # ============================================================
    def set_summary(self, session_id: str, summary: str) -> None:
        """Set thủ công summary (thường được LLM gọi từ bên ngoài)."""
        sess = self.get_or_create(session_id)
        with self._lock:
            sess.summary = summary
            sess.metadata.pop("needs_summary", None)
            sess.updated_at = time.time()

    def needs_summary(self, session_id: str) -> bool:
        sess = self.get(session_id)
        if sess is None:
            return False
        return sess.metadata.get("needs_summary", False)

    # ============================================================
    # CLEANUP
    # ============================================================
    def _cleanup_expired(self) -> None:
        """Xóa sessions idle quá lâu."""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if (now - s.updated_at) > SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]
        if expired:
            log.info("Cleaned up %d expired sessions", len(expired))


# ============================================================
# SINGLETON ACCESSOR
# ============================================================
def get_memory() -> ConversationMemory:
    """Lấy singleton ConversationMemory."""
    return ConversationMemory()


# ============================================================
# NOTES (cho sau này — không implement trong đợt này)
# ============================================================
"""
Tích hợp MongoDB (khi cần):
  - Schema:
      conversations
      ├── conversation_id (UUID)
      ├── user_id
      ├── summary (optional)
      ├── created_at, updated_at
      messages
      ├── message_id
      ├── conversation_id (FK)
      ├── role
      ├── content
      ├── created_at
      └── metadata (JSON)
  - Hiện tại in-process đủ dùng cho 1 process rag-service + dev/testing.
  - Production multi-instance → cần MongoDB hoặc Redis.

Tích hợp summarization (cho sau):
  - Background job: scan "needs_summary" sessions, gọi LLM tóm tắt
    messages cũ thành 1-2 câu, lưu vào Session.summary.
  - Khi build prompt cho B2/B6, ghép summary + recent messages.
  - Hiện tại: chỉ còn recent messages (không summarize tự động).
"""
