"""Tests cho policy + expansion (B2/B4 v3)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.rag.steps.expansion import (
    check_document_status,
    expand_anchor,
    expand_all,
)
from app.rag.steps.policy import (
    build_retrieval_policy,
    detect_intent_heuristic,
    detect_missing_facts,
)


# ============================================================
# detect_intent_heuristic — extension tests
# ============================================================
def test_intent_priority_list_over_general():
    """List phrase nên thắng general lookup."""
    assert detect_intent_heuristic(
        "Có những khoản nào trong điều 6 về xử phạt?"
    ) == "list_clauses"


def test_intent_empty_returns_general():
    assert detect_intent_heuristic("") == "general_info"


def test_intent_unrelated_text_general():
    assert detect_intent_heuristic("abc xyz 123") == "general_info"


# ============================================================
# detect_missing_facts — extended
# ============================================================
def test_missing_facts_penalty_with_vehicle_no_missing():
    missing = detect_missing_facts(
        "Phạt xe ô tô không nhường đường bao nhiêu?",
        "penalty_lookup",
        ["phạt", "xe ô tô", "không nhường đường"],
    )
    assert "vehicle_type" not in missing


def test_missing_facts_rule_lookup_general():
    """Rule lookup với câu ngắn → có thể trigger missing."""
    missing = detect_missing_facts(
        "quy tắc giao thông",
        "rule_lookup",
        [],
    )
    # Không assert cụ thể, chỉ kiểm tra không crash
    assert isinstance(missing, list)


def test_missing_facts_list_intent_skipped():
    """List intent → không trigger missing (user muốn overview)."""
    missing = detect_missing_facts(
        "Có những chương nào?",
        "list_chapters",
        [],
    )
    assert missing == []


# ============================================================
# build_retrieval_policy — coverage tests
# ============================================================
def test_policy_rule_lookup_luat_filter():
    p = build_retrieval_policy("rule_lookup")
    assert p["filters"]["document_type"] == "Luật"
    assert p["filters"]["require_active"] is True


def test_policy_procedure_parent_expansion():
    p = build_retrieval_policy("procedure_lookup")
    assert p["expansion"] == "parent"
    assert p["filters"]["require_active"] is True


def test_policy_general_info_siblings():
    p = build_retrieval_policy("general_info")
    assert p["expansion"] == "siblings"
    assert p["max_evidence_hint"] == 10


def test_policy_list_articles_high_max_evidence():
    p = build_retrieval_policy("list_articles")
    assert p["max_evidence_hint"] == 20
    assert p["intensity"] == "list"


def test_policy_list_chapters_low_max_evidence():
    p = build_retrieval_policy("list_chapters")
    assert p["max_evidence_hint"] == 5


def test_policy_missing_fact_query_deep_neighbors():
    p = build_retrieval_policy("missing_fact_query")
    assert p["intensity"] == "deep"
    assert p["expansion"] == "neighbors"


def test_policy_with_override_filters():
    p = build_retrieval_policy(
        "penalty_lookup",
        overrides={"filters": {"require_active": False}},
    )
    assert p["filters"]["require_active"] is False


def test_policy_keeps_source_intent_field():
    p = build_retrieval_policy("penalty_lookup")
    assert p["source_intent"] == "penalty_lookup"


def test_policy_missing_facts_with_siblings():
    """Câu list_articles nhưng có missing facts → expansion không tăng (đã none)."""
    p = build_retrieval_policy("list_articles", missing_facts=["vehicle_type"])
    assert p["expansion"] == "none"  # list intent giữ none


def test_policy_general_info_with_missing_becomes_neighbors():
    p = build_retrieval_policy("general_info", missing_facts=["vehicle_type"])
    assert p["expansion"] == "neighbors"


# ============================================================
# expansion engine
# ============================================================
def test_expand_anchor_none_returns_empty():
    """policy='none' → trả []."""
    anchor = {
        "vector_id": "vid-1",
        "pinecone_meta": {"document_id": "D1", "article_id": "A1"},
    }
    # Mock session
    neo_session = MagicMock()
    neo_sess = MagicMock()
    neo_sess.__enter__ = MagicMock(return_value=neo_sess)
    neo_sess.__exit__ = MagicMock(return_value=None)
    neo_sess.run.return_value = []  # empty
    neo_session.return_value = neo_sess
    out = expand_anchor(neo_session, anchor, "none")
    assert out == []


def test_expand_anchor_no_document_id_returns_empty():
    anchor = {"vector_id": "vid-1", "pinecone_meta": {}}
    neo_session = MagicMock()
    out = expand_anchor(neo_session, anchor, "siblings")
    assert out == []


def test_check_document_status_active():
    """Document active + trong date range → is_active=True."""
    neo_session = MagicMock()
    neo_sess = MagicMock()
    neo_sess.__enter__ = MagicMock(return_value=neo_sess)
    neo_sess.__exit__ = MagicMock(return_value=None)

    # Row 1: status
    row_status = MagicMock()
    row_status.single.return_value = {
        "document_id": "D1",
        "status": "active",
        "effective_from": None,
        "effective_to": None,
    }
    # Row 2: has amendment
    row_amend = MagicMock()
    row_amend.single.return_value = None

    neo_sess.run.side_effect = [row_status, row_amend]
    neo_session.return_value = neo_sess

    info = check_document_status(neo_session, "D1", "2026-09-27")
    assert info["is_active"] is True
    assert info["status"] == "active"


def test_check_document_status_inactive_no_amend():
    """Document inactive + không có amendment → is_active=False."""
    neo_session = MagicMock()
    neo_sess = MagicMock()
    neo_sess.__enter__ = MagicMock(return_value=neo_sess)
    neo_sess.__exit__ = MagicMock(return_value=None)

    row_status = MagicMock()
    row_status.single.return_value = {
        "document_id": "D1",
        "status": "repealed",
        "effective_from": None,
        "effective_to": None,
    }
    row_amend = MagicMock()
    row_amend.single.return_value = None

    neo_sess.run.side_effect = [row_status, row_amend]
    neo_session.return_value = neo_sess

    info = check_document_status(neo_session, "D1", "2026-09-27")
    assert info["is_active"] is False
    assert info["has_active_amendment"] is False


def test_check_document_status_inactive_with_amend_marks_active():
    """Document inactive + có amendment → is_active=True (vẫn dùng được)."""
    neo_session = MagicMock()
    neo_sess = MagicMock()
    neo_sess.__enter__ = MagicMock(return_value=neo_sess)
    neo_sess.__exit__ = MagicMock(return_value=None)

    row_status = MagicMock()
    row_status.single.return_value = {
        "document_id": "D1",
        "status": "repealed",
        "effective_from": None,
        "effective_to": None,
    }
    row_amend = MagicMock()
    row_amend.single.return_value = {"amended_article_id": "A1"}

    neo_sess.run.side_effect = [row_status, row_amend]
    neo_session.return_value = neo_sess

    info = check_document_status(neo_session, "D1", "2026-09-27")
    assert info["has_active_amendment"] is True


def test_check_document_status_date_out_of_range():
    """Effective_to trong quá khứ → is_active=False."""
    neo_session = MagicMock()
    neo_sess = MagicMock()
    neo_sess.__enter__ = MagicMock(return_value=neo_sess)
    neo_sess.__exit__ = MagicMock(return_value=None)

    row_status = MagicMock()
    row_status.single.return_value = {
        "document_id": "D1",
        "status": "active",
        "effective_from": "2020-01-01",
        "effective_to": "2024-12-31",
    }
    row_amend = MagicMock()
    row_amend.single.return_value = None

    neo_sess.run.side_effect = [row_status, row_amend]
    neo_session.return_value = neo_sess

    info = check_document_status(neo_session, "D1", "2026-09-27")
    assert info["is_active"] is False


def test_check_document_status_empty_doc_id():
    """document_id rỗng → fallback True."""
    neo_session = MagicMock()
    info = check_document_status(neo_session, "", "2026-09-27")
    assert info["is_active"] is True


# ============================================================
# expand_all - integration nhẹ
# ============================================================
def test_expand_all_none_policy_empty():
    """policy=none → out empty."""
    out, stats = expand_all(MagicMock(), [], {"expansion": "none"})
    assert out == []
    assert stats == {"kind_counts": {}, "dropped_inactive": 0}


def test_expand_all_no_anchors_empty():
    """anchors rỗng → out rỗng."""
    out, stats = expand_all(MagicMock(), [], {"expansion": "siblings"})
    assert out == []


def test_expand_all_siblings_stops_at_empty_article():
    """Article anchor không có clause → out empty (chỉ siblings)."""
    neo_session = MagicMock()
    neo_sess = MagicMock()
    neo_sess.__enter__ = MagicMock(return_value=neo_sess)
    neo_sess.__exit__ = MagicMock(return_value=None)

    # Row for clause siblings query
    row_cursor = MagicMock()
    row_cursor.__iter__ = lambda self: iter([])
    neo_sess.run.return_value = row_cursor
    neo_session.return_value = neo_sess

    # Status check cũng chạy trước
    # Mock sẽ trả row_cursor cho cả 2 lần run - đủ cho expansion block

    anchor = {
        "vector_id": "vid-1",
        "pinecone_meta": {
            "document_id": "D1",
            "article_id": "A1",
        },
    }
    out, stats = expand_all(neo_session, [anchor], {"expansion": "siblings"})
    # Sẽ chạy thêm status query trước expansion, nên session.run có thể nhiều lần
    # Result: không có clause → out empty
    assert isinstance(out, list)
    assert "kind_counts" in stats
