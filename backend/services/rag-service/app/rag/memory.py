"""
Conversation Memory Manager.

Responsibilities:
  1. In-process cache (LRU + TTL) cho active sessions — singleton.
  2. MongoDB persistence (best-effort fallback) — optional, không break nếu down.
  3. Background auto-summarization khi session vượt threshold.

Theo HANDOVER_NHA.md: dev1 đã để skeleton in-process. Dev2 bổ sung:
  - MongoDB persistence layer
  - Background thread cho summary
  - Hook tở integration LLM cho summary (dùng Groq fast model)

Public API:
  - ConversationMemory  (singleton)
  - get_memory()        (accessor)
  - shutdown_memory()   (cleanup background thread khi service shutdown)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("rag-service")

# ============================================================
# CONSTANTS
# ============================================================
MAX_MESSAGES_PER_SESSION = 20       # FIFO trim khi vượt
MAX_HISTORY_FOR_QUERY = 6          # 3 cặp user/assistant cho multi-turn
SESSION_IDLE_TTL_SECONDS = 2 * 3600 # 2 giờ
SUMMARY_TRIGGER_MESSAGES = 10      # Khi >= 10 msg → trigger summary
MAX_SESSIONS_IN_MEMORY = 500       # LRU cap

SUMMARY_PROMPT = """Bạn là trợ lý pháp lý. Tóm tắt ngắn gọn (≤ 200 từ) cuộc hội thoại sau
thành các ý chính, giữ lại:
  - Câu hỏi pháp luật đã hỏi
  - Điều luật / Nghị định đã được trích dẫn
  - Kết luận / mức phạt / quy định quan trọng

Không thêm thông tin ngoài cuộc hội thoại.

Cuộc hội thoại:
{transcript}

Tóm tắt (tiếng Việt, ngắn gọn):"""


# ============================================================
# SESSION MODEL
# ============================================================
@dataclass
class Message:
    role: str
    content: str
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=str(data.get("role", "")),
            content=str(data.get("content", "")),
            created_at=float(data.get("created_at") or time.time()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass
class Session:
    session_id: str
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    needs_summary: bool = False

    def touch(self) -> None:
        self.last_active = time.time()

    def is_expired(self, ttl_seconds: int = SESSION_IDLE_TTL_SECONDS) -> bool:
        return (time.time() - self.last_active) > ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "messages": [m.to_dict() for m in self.messages],
            "summary": self.summary,
            "created_at": self.created_at,
            "last_active": self.last_active,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return cls(
            session_id=str(data.get("session_id", "")),
            messages=[Message.from_dict(m) for m in (data.get("messages") or [])],
            summary=str(data.get("summary") or ""),
            created_at=float(data.get("created_at") or time.time()),
            last_active=float(data.get("last_active") or time.time()),
            needs_summary=False,
        )


# ============================================================
# OPTIONAL MONGODB PERSISTENCE
# ============================================================
class _MongoPersistence:
    """Best-effort MongoDB persistence layer.

    Lazy-import pymongo để tránh crash nếu chưa cài. Mọi lỗi đều log +
    silently skip — in-process cache vẫn hoạt động bình thường.
    """

    def __init__(self, uri: str | None, db_name: str = "rag_memory") -> None:
        self._client = None
        self._db = None
        self._enabled = False
        self._uri = uri

        if not uri:
            log.info("[Memory] MongoDB persistence disabled (no URI)")
            return

        try:
            from pymongo import MongoClient  # type: ignore

            self._client = MongoClient(uri, serverSelectionTimeoutMS=2000)
            # Ping để verify connection ngay tại startup
            self._client.admin.command("ping")
            self._db = self._client[db_name]
            self._enabled = True
            log.info("[Memory] MongoDB persistence enabled (db=%s)", db_name)
        except Exception as exc:
            log.warning(
                "[Memory] MongoDB unavailable, falling back to in-process only: %s",
                exc,
            )
            self._client = None
            self._db = None
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _conv_collection(self):
        if self._db is None:
            return None
        return self._db["conversations"]

    def _msg_collection(self):
        if self._db is None:
            return None
        return self._db["messages"]

    def load_session(self, session_id: str) -> Session | None:
        if not self._enabled:
            return None
        try:
            coll = self._conv_collection()
            if coll is None:
                return None
            doc = coll.find_one({"conversation_id": session_id})
            if not doc:
                return None
            # Load messages
            msg_coll = self._msg_collection()
            msgs: list[Message] = []
            if msg_coll is not None:
                for m in msg_coll.find({"conversation_id": session_id}).sort("created_at", 1):
                    msgs.append(Message.from_dict({
                        "role": m.get("role"),
                        "content": m.get("content"),
                        "created_at": m.get("created_at"),
                        "metadata": m.get("metadata") or {},
                    }))
            return Session(
                session_id=session_id,
                messages=msgs,
                summary=str(doc.get("summary") or ""),
                created_at=float(doc.get("created_at") or time.time()),
                last_active=float(doc.get("updated_at") or time.time()),
            )
        except Exception as exc:
            log.warning("[Memory] Mongo load failed for %s: %s", session_id, exc)
            return None

    def save_session(self, session: Session) -> None:
        if not self._enabled:
            return
        try:
            conv_coll = self._conv_collection()
            if conv_coll is not None:
                conv_coll.update_one(
                    {"conversation_id": session.session_id},
                    {
                        "$set": {
                            "conversation_id": session.session_id,
                            "summary": session.summary,
                            "created_at": session.created_at,
                            "updated_at": session.last_active,
                        }
                    },
                    upsert=True,
                )
            msg_coll = self._msg_collection()
            if msg_coll is not None:
                # Chỉ insert các message mới (có created_at > max trong DB)
                existing_max = 0.0
                for d in msg_coll.find({"conversation_id": session.session_id}).sort(
                    "created_at", -1
                ).limit(1):
                    existing_max = float(d.get("created_at") or 0.0)
                    break
                new_docs = [
                    {
                        "conversation_id": session.session_id,
                        "role": m.role,
                        "content": m.content,
                        "created_at": m.created_at,
                        "metadata": m.metadata,
                    }
                    for m in session.messages
                    if m.created_at > existing_max
                ]
                if new_docs:
                    msg_coll.insert_many(new_docs, ordered=False)
        except Exception as exc:
            log.warning("[Memory] Mongo save failed for %s: %s", session.session_id, exc)

    def save_summary(self, session_id: str, summary: str) -> None:
        if not self._enabled:
            return
        try:
            conv_coll = self._conv_collection()
            if conv_coll is None:
                return
            conv_coll.update_one(
                {"conversation_id": session_id},
                {"$set": {"summary": summary, "updated_at": time.time()}},
                upsert=True,
            )
        except Exception as exc:
            log.warning("[Memory] Mongo save_summary failed: %s", exc)


# ============================================================
# BACKGROUND SUMMARIZER
# ============================================================
class _BackgroundSummarizer:
    """Background thread auto-summarize khi session vượt threshold.

    Dùng daemon thread đơn giản — không cần Redis/Celery cho in-process service.
    Có thể bị disable qua `enabled=False` (cho test).
    """

    def __init__(self, memory: "ConversationMemory", llm_provider=None) -> None:
        self._memory = memory
        self._llm_provider = llm_provider
        self._queue: dict[str, Session] = {}  # session_id → session (dedupe)
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.enabled = True

    def set_llm_provider(self, provider) -> None:
        """Set/get LLM callable: (transcript: str) -> summary: str."""
        self._llm_provider = provider

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._worker, name="MemorySummarizer", daemon=True
        )
        self._thread.start()
        log.info("[Memory] Background summarizer started")

    def stop(self) -> None:
        self._stop.set()
        with self._cv:
            self._cv.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("[Memory] Background summarizer stopped")

    def enqueue(self, session: Session) -> None:
        if not self.enabled:
            return
        with self._cv:
            self._queue[session.session_id] = session
            self._cv.notify()

    def _worker(self) -> None:
        """Pull sessions từ queue và summarize."""
        while not self._stop.is_set():
            with self._cv:
                while not self._queue and not self._stop.is_set():
                    self._cv.wait(timeout=1.0)
                if self._stop.is_set():
                    return
                # Pop one session (FIFO-ish: lấy cuối dict = last inserted)
                session_id, session = next(reversed(self._queue.items()))
                self._queue.pop(session_id, None)

            # Summarize ngoài lock
            try:
                self._do_summarize(session)
            except Exception as exc:
                log.warning("[Memory] Summarization failed for %s: %s", session_id, exc)

    def _do_summarize(self, session: Session) -> None:
        """Gọi LLM (hoặc fallback heuristic) để summarize."""
        transcript = self._build_transcript(session)
        summary = ""

        if self._llm_provider is not None:
            try:
                summary = str(self._llm_provider(transcript)).strip()[:1000]
            except Exception as exc:
                log.warning("[Memory] LLM summarize failed, using heuristic: %s", exc)

        if not summary:
            summary = self._heuristic_summarize(session)

        # Re-fetch session (có thể đã thay đổi) → update summary
        current = self._memory.get(session.session_id)
        if current is None:
            return
        current.summary = summary
        current.needs_summary = False
        # Persist to MongoDB
        self._memory._mongo.save_summary(session.session_id, summary)
        log.info("[Memory] Summarized session=%s (len=%d)", session.session_id, len(summary))

    @staticmethod
    def _build_transcript(session: Session) -> str:
        lines: list[str] = []
        for m in session.messages[-20:]:
            role_label = "Người dùng" if m.role == "user" else "Trợ lý"
            lines.append(f"{role_label}: {m.content}")
        return "\n".join(lines)

    @staticmethod
    def _heuristic_summarize(session: Session) -> str:
        """Fallback summarize khi không có LLM."""
        last_user = next(
            (m.content for m in reversed(session.messages) if m.role == "user"),
            "",
        )
        last_assistant = next(
            (m.content for m in reversed(session.messages) if m.role == "assistant"),
            "",
        )
        parts: list[str] = []
        if last_user:
            parts.append(f"Câu hỏi gần nhất: {last_user[:200]}")
        if last_assistant:
            parts.append(f"Trả lời: {last_assistant[:300]}")
        parts.append(f"Tổng số lượt trao đổi: {len(session.messages) // 2}")
        return "\n".join(parts)


# ============================================================
# MAIN: ConversationMemory
# ============================================================
class ConversationMemory:
    """Singleton conversation memory manager.

    Architecture:
      - In-process LRU cache (OrderedDict) cho active sessions.
      - Optional MongoDB persistence (best-effort fallback).
      - Background thread auto-summarization.
    """

    def __init__(self, mongo_uri: str | None = None) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.RLock()
        self._mongo = _MongoPersistence(mongo_uri)
        self._summarizer = _BackgroundSummarizer(memory=self)
        self._summarizer.start()

    # ── Session ops ────────────────────────────────────────────────────
    def get_or_create(self, session_id: str) -> Session:
        """Get session nếu tồn tại (LRU touch), else create mới + load từ Mongo."""
        if not session_id:
            session_id = "default"
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess is not None:
                if sess.is_expired():
                    log.info("[Memory] Session %s expired; resetting", session_id)
                    self._sessions.pop(session_id, None)
                    sess = None
                else:
                    sess.touch()
                    self._sessions.move_to_end(session_id)
                    return sess

            # Try load from Mongo first
            if self._mongo.enabled:
                loaded = self._mongo.load_session(session_id)
                if loaded is not None:
                    sess = loaded
            if sess is None:
                sess = Session(session_id=session_id)

            self._sessions[session_id] = sess
            self._evict_if_needed()
            return sess

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            sess = self._sessions.get(session_id)
            if sess and not sess.is_expired():
                sess.touch()
                self._sessions.move_to_end(session_id)
                return sess
            return None

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def clear_all(self) -> None:
        with self._lock:
            self._sessions.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_sessions": len(self._sessions),
                "mongo_enabled": self._mongo.enabled,
                "summarizer_queue_size": len(self._summarizer._queue),
            }

    # ── Message ops ────────────────────────────────────────────────────
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        sess = self.get_or_create(session_id)
        msg = Message(
            role=str(role),
            content=str(content),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            sess.messages.append(msg)
            sess.needs_summary = len(sess.messages) >= SUMMARY_TRIGGER_MESSAGES
            # FIFO trim
            if len(sess.messages) > MAX_MESSAGES_PER_SESSION:
                sess.messages = sess.messages[-MAX_MESSAGES_PER_SESSION:]
            sess.touch()
            # Persist (best-effort)
            self._mongo.save_session(sess)
        # Enqueue summarization nếu cần
        if sess.needs_summary:
            self._summarizer.enqueue(sess)
        return msg

    def add_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        **metadata: Any,
    ) -> None:
        """Convenience: add cả user + assistant message cùng lúc."""
        meta = dict(metadata) if metadata else None
        self.add_message(session_id, "user", user_message, meta)
        self.add_message(session_id, "assistant", assistant_message, meta)

    # ── Retrieve cho query ─────────────────────────────────────────────
    def get_history_for_query(
        self,
        session_id: str,
        max_msgs: int = MAX_HISTORY_FOR_QUERY,
    ) -> list[dict[str, str]]:
        sess = self.get(session_id)
        if sess is None:
            return []
        recent = sess.messages[-max_msgs:]
        return [{"role": m.role, "content": m.content} for m in recent]

    def get_context_summary(self, session_id: str) -> str:
        sess = self.get(session_id)
        if sess is None:
            return ""
        return sess.summary

    # ── Summary management ─────────────────────────────────────────────
    def set_summary(self, session_id: str, summary: str) -> None:
        sess = self.get_or_create(session_id)
        sess.summary = str(summary)
        self._mongo.save_summary(session_id, summary)

    def needs_summary(self, session_id: str) -> bool:
        sess = self.get(session_id)
        return sess.needs_summary if sess else False

    def set_llm_for_summary(self, provider) -> None:
        """Inject LLM callable cho summarizer.

        `provider(transcript: str) -> summary: str`
        """
        self._summarizer.set_llm_provider(provider)

    # ── Lifecycle ──────────────────────────────────────────────────────
    def shutdown(self) -> None:
        self._summarizer.stop()

    def _evict_if_needed(self) -> None:
        if len(self._sessions) <= MAX_SESSIONS_IN_MEMORY:
            return
        # Pop oldest (FIFO từ OrderedDict)
        for _ in range(len(self._sessions) - MAX_SESSIONS_IN_MEMORY):
            self._sessions.popitem(last=False)


# ============================================================
# SINGLETON
# ============================================================
_memory_singleton: ConversationMemory | None = None
_singleton_lock = threading.Lock()


def get_memory() -> ConversationMemory:
    """Get singleton ConversationMemory instance."""
    global _memory_singleton
    if _memory_singleton is None:
        with _singleton_lock:
            if _memory_singleton is None:
                from app.core.config import MONGODB_URI

                _memory_singleton = ConversationMemory(mongo_uri=MONGODB_URI)
    return _memory_singleton


def shutdown_memory() -> None:
    """Cleanup background thread. Gọi khi service shutdown."""
    global _memory_singleton
    if _memory_singleton is not None:
        _memory_singleton.shutdown()
        _memory_singleton = None