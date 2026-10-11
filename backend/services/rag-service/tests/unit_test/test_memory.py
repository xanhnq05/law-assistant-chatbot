"""Tests cho Conversation Memory (in-process layer)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.rag.memory import (
    MAX_HISTORY_FOR_QUERY,
    MAX_MESSAGES_PER_SESSION,
    ConversationMemory,
    get_memory,
)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def memory():
    """Fresh in-memory store mỗi test."""
    mem = ConversationMemory()
    mem.clear_all()
    return mem


# ============================================================
# Singleton + basic API
# ============================================================
def test_get_memory_singleton():
    a = get_memory()
    b = get_memory()
    assert a is b


def test_add_message_and_retrieve(memory):
    memory.add_message("s1", "user", "Hello")
    memory.add_message("s1", "assistant", "Chào bạn")
    history = memory.get_history_for_query("s1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_get_history_empty_session(memory):
    assert memory.get_history_for_query("nonexistent") == []


# ============================================================
# FIFO trimming
# ============================================================
def test_max_messages_trim(memory):
    """Vượt MAX_MESSAGES → FIFO trim."""
    for i in range(MAX_MESSAGES_PER_SESSION + 5):
        memory.add_message("s1", "user", f"msg-{i}")
    msgs = memory.get_session_messages("s1")
    assert len(msgs) <= MAX_MESSAGES_PER_SESSION
    # Phải giữ các msg mới nhất
    last = msgs[-1]["content"]
    assert last == f"msg-{MAX_MESSAGES_PER_SESSION + 4}"


def test_history_query_limit(memory):
    """get_history_for_query giới hạn max_msgs."""
    for i in range(20):
        memory.add_message("s1", "user", f"msg-{i}")
        memory.add_message("s1", "assistant", f"reply-{i}")
    history = memory.get_history_for_query("s1")
    assert len(history) <= MAX_HISTORY_FOR_QUERY


# ============================================================
# add_exchange helper
# ============================================================
def test_add_exchange(memory):
    memory.add_exchange("s1", "Q1?", "A1", intent="penalty_lookup")
    history = memory.get_history_for_query("s1")
    assert len(history) == 2
    assert history[0]["content"] == "Q1?"
    assert history[1]["content"] == "A1"
    # Metadata lưu trong msg
    msgs = memory.get_session_messages("s1")
    assert msgs[0]["metadata"].get("intent") == "penalty_lookup"


# ============================================================
# Summary management
# ============================================================
def test_set_and_get_summary(memory):
    memory.set_summary("s1", "User hỏi về phạt giao thông.")
    assert memory.get_context_summary("s1") == "User hỏi về phạt giao thông."


def test_needs_summary_after_threshold(memory):
    """Đạt SUMMARY_THRESHOLD_MESSAGES → needs_summary=True."""
    for i in range(8):
        memory.add_message("s1", "user", f"msg-{i}")
    assert memory.needs_summary("s1") is True


def test_set_summary_clears_needs_summary(memory):
    memory.add_message("s1", "user", "a")
    memory.add_message("s1", "user", "b")
    memory.add_message("s1", "user", "c")
    memory.add_message("s1", "user", "d")
    memory.set_summary("s1", "summary set")
    assert memory.needs_summary("s1") is False


# ============================================================
# Session ops
# ============================================================
def test_delete_session(memory):
    memory.add_message("s1", "user", "hi")
    assert memory.delete("s1") is True
    assert memory.get("s1") is None


def test_delete_nonexistent_returns_false(memory):
    assert memory.delete("nope") is False


def test_clear_all(memory):
    memory.add_message("s1", "user", "a")
    memory.add_message("s2", "user", "b")
    memory.clear_all()
    assert memory.get("s1") is None
    assert memory.get("s2") is None


def test_stats(memory):
    memory.add_message("s1", "user", "a")
    memory.add_message("s1", "assistant", "b")
    memory.add_message("s2", "user", "c")
    stats = memory.stats()
    assert stats["session_count"] == 2
    sids = {s["session_id"] for s in stats["sessions"]}
    assert sids == {"s1", "s2"}


# ============================================================
# Default session_id fallback
# ============================================================
def test_empty_session_id_uses_default(memory):
    mem = memory
    mem.add_message("", "user", "hi")  # empty string
    assert mem.get("default") is not None


# ============================================================
# Helper: get_session_messages (test-only)
# ============================================================
def test_get_session_messages_with_metadata(memory):
    memory.add_message("s1", "user", "Q?", {"custom_key": "value"})
    msgs = memory.get_session_messages("s1")
    assert msgs[0]["metadata"].get("custom_key") == "value"


# ============================================================
# Integration với Session to_history format
# ============================================================
def test_session_to_history_format():
    from app.rag.memory import Session
    sess = Session(session_id="x")
    sess.messages = [
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
        {"role": "user", "content": "Q2"},
    ]
    history = sess.to_history(max_msgs=2)
    assert len(history) == 2
    # Phải trả format {role, content} thuần, KHÔNG có ts/metadata
    assert set(history[0].keys()) == {"role", "content"}
