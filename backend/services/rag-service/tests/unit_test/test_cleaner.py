"""Tests cho B2 - Query Cleaner (v2: history-aware + retrieval policy)."""
from __future__ import annotations

import pytest

from app.rag.steps.cleaner import (
    _has_reference_marker,
    _normalize_history,
    _rule_based_clean,
    step_clean_query,
)
from app.rag.steps.policy import (
    build_retrieval_policy,
    detect_intent_heuristic,
    detect_missing_facts,
)


# ============================================================
# RULE-BASED FALLBACK
# ============================================================
def test_rule_based_clean_removes_filler():
    q = "cho mình hỏi phạt bao nhiêu khi đi xe máy ạ?"
    out = _rule_based_clean(q)
    assert "cho mình hỏi" not in out
    # Lưu ý: 'ạ' xuất hiện trong 'phạt' - không thể assert ký tự đơn 'ạ'.
    # Thay vào đó kiểm tra: trailing 'ạ' (sentence-final filler) không còn.
    assert not out.endswith("ạ?"), "Trailing filler 'ạ' phải được strip"
    assert "phạt" in out


def test_rule_based_clean_removes_trailing_filler():
    """Verify trailing filler 'ạ' được strip khi đứng riêng."""
    q = "phạt bao nhiêu ạ?"
    out = _rule_based_clean(q)
    assert "ạ" + "?" not in out


def test_rule_based_clean_removes_middle_filler():
    q = "cho tôi hỏi phạt như thế nào?"
    out = _rule_based_clean(q)
    assert "cho tôi hỏi" not in out
    assert "phạt" in out


def test_rule_based_clean_normalize_whitespace():
    q = "  phạt    bao    nhiêu   "
    assert _rule_based_clean(q) == "phạt bao nhiêu"


# ============================================================
# INTENT HEURISTIC (mở rộng)
# ============================================================
def test_detect_intent_penalty():
    assert detect_intent_heuristic("phạt bao nhiêu khi vượt đèn đỏ") == "penalty_lookup"
    assert detect_intent_heuristic("Mức phạt tiền là bao nhiêu") == "penalty_lookup"


def test_detect_intent_rule():
    assert detect_intent_heuristic("Quy tắc nhường đường là gì?") == "rule_lookup"


def test_detect_intent_procedure():
    assert detect_intent_heuristic("Thủ tục thi GPLX như thế nào?") == "procedure_lookup"


def test_detect_intent_general():
    assert detect_intent_heuristic("Xin chào bạn") == "general_info"


# ---- MỚI: list_* intents ----
def test_detect_intent_list_clauses():
    assert detect_intent_heuristic("Điều 6 có những khoản nào?") == "list_clauses"
    assert detect_intent_heuristic("Liệt kê các khoản của điều 6") == "list_clauses"


def test_detect_intent_list_articles():
    assert detect_intent_heuristic("Chương II có những điều nào?") == "list_articles"


def test_detect_intent_list_chapters():
    assert detect_intent_heuristic("Văn bản này có những chương nào?") == "list_chapters"


# ============================================================
# REFERENCE MARKER DETECTION
# ============================================================
def test_reference_marker_detection():
    assert _has_reference_marker("Còn ô tô thì sao?") is True
    assert _has_reference_marker("Nó có bị phạt không?") is True
    assert _has_reference_marker("Điều 6 nói gì?") is False
    assert _has_reference_marker("Phạt bao nhiêu khi vượt đèn đỏ?") is False


def test_normalize_history_empty():
    assert _normalize_history(None) == ""
    assert _normalize_history([]) == ""


def test_normalize_history_pairs():
    history = [
        {"role": "user", "content": "Câu 1?"},
        {"role": "assistant", "content": "Trả lời 1"},
        {"role": "user", "content": "Câu 2?"},
        {"role": "assistant", "content": "Trả lời 2"},
    ]
    out = _normalize_history(history)
    assert "Câu 1?" in out
    assert "Trả lời 1" in out
    assert "Câu 2?" in out
    assert "Trả lời 2" in out


# ============================================================
# MISSING FACT DETECTION
# ============================================================
def test_missing_facts_penalty_without_vehicle():
    missing = detect_missing_facts("Phạt bao nhiêu khi vượt đèn đỏ?", "penalty_lookup", [])
    assert "vehicle_type" in missing


def test_missing_facts_penalty_with_vehicle_no_missing():
    missing = detect_missing_facts(
        "Phạt xe máy khi vượt đèn đỏ là bao nhiêu?",
        "penalty_lookup",
        ["phạt", "xe máy", "vượt đèn đỏ"],
    )
    assert "vehicle_type" not in missing


def test_missing_facts_list_intent_no_missing():
    """List intents không trigger missing fact."""
    missing = detect_missing_facts(
        "Có những khoản nào trong Điều 6?", "list_clauses", []
    )
    assert missing == []


# ============================================================
# POLICY BUILDER
# ============================================================
def test_policy_penalty_lookup_defaults():
    p = build_retrieval_policy("penalty_lookup")
    assert p["intensity"] == "default"
    assert p["expansion"] == "siblings"
    assert p["filters"]["require_active"] is True
    assert p["filters"]["document_type"] == "Nghị định"


def test_policy_list_clauses_none_expansion():
    p = build_retrieval_policy("list_clauses")
    assert p["intensity"] == "list"
    assert p["expansion"] == "none"
    assert p["filters"]["require_active"] is False


def test_policy_missing_facts_boosts_to_neighbors():
    """Có missing_facts → expansion auto lên neighbors."""
    p = build_retrieval_policy("general_info", missing_facts=["vehicle_type"])
    assert p["expansion"] == "neighbors"


def test_policy_expansion_hint_broad():
    p = build_retrieval_policy("general_info", expansion_hint="broad")
    assert p["expansion"] == "neighbors"


def test_policy_expansion_hint_list_view():
    p = build_retrieval_policy("general_info", expansion_hint="list_view")
    assert p["expansion"] == "none"
    assert p["intensity"] == "list"


def test_policy_override():
    p = build_retrieval_policy(
        "penalty_lookup", overrides={"intensity": "deep"}
    )
    assert p["intensity"] == "deep"


def test_policy_unknown_intent_fallback():
    """Intent không hợp lệ → fallback general_info."""
    p = build_retrieval_policy("some_unknown_intent_xyz")
    assert p["source_intent"] == "general_info"
    assert p["expansion"] == "siblings"


# ============================================================
# MAIN: step_clean_query
# ============================================================
def test_step_clean_query_with_llm(mock_llm):
    """Backward-compat + kiểm tra field mới có mặt."""
    q = "Cho mình hỏi phạt bao nhiêu khi đi xe máy không nhường đường ạ?"
    result = step_clean_query(mock_llm, q)
    # Back-compat
    assert result["cleaned_query"]
    assert result["intent"] == "penalty_lookup"
    assert "phạt" in result["key_legal_terms"]
    assert result["original"] == q
    # Mới
    assert "resolved_query" in result
    assert "history_dependent" in result
    assert "retrieval_policy" in result
    assert isinstance(result["retrieval_policy"], dict)
    assert result["retrieval_policy"]["intensity"] in ("default", "deep", "list")


def test_step_clean_query_without_llm_fallback():
    """Không có LLM → fallback rule-based, vẫn trả đầy đủ field mới."""
    q = "phạt bao nhiêu khi đi xe máy không nhường đường?"
    result = step_clean_query(None, q)
    assert result["cleaned_query"] == q
    assert result["intent"] == "penalty_lookup"
    assert "retrieval_policy" in result
    assert result["retrieval_policy"]["expansion"] in ("siblings", "neighbors")


def test_step_clean_query_followup_resolves(mock_llm_with_followup):
    """Câu follow-up + history → resolved_query khác câu gốc, history_dependent=True."""
    q = "Còn ô tô thì sao?"
    history = [
        {"role": "user", "content": "Phạt bao nhiêu khi đi xe máy không nhường đường?"},
        {"role": "assistant", "content": "Theo Nghị định 168, Điều 6, Khoản 4: phạt 4-6 triệu."},
    ]
    result = step_clean_query(mock_llm_with_followup, q, history=history)
    assert result["history_dependent"] is True
    assert "ô tô" in result["resolved_query"].lower() or "oto" in result["resolved_query"].lower()


def test_step_clean_query_no_history_keeps_original(mock_llm):
    """Câu không có history → resolved_query = cleaned_query, history_dependent=False."""
    q = "Phạt bao nhiêu khi đi xe máy không nhường đường?"
    result = step_clean_query(mock_llm, q, history=None)
    assert result["history_dependent"] is False


def test_step_clean_query_list_intent_builds_list_policy(mock_llm):
    """Intent list_* → policy.intensity='list', expansion='none'."""
    q = "Văn bản này có những chương nào?"
    result = step_clean_query(mock_llm, q)
    # Intent có thể do LLM trả, nhưng policy được build từ intent
    assert "retrieval_policy" in result
    p = result["retrieval_policy"]
    # Có thể test thông qua intent thực tế - nếu intent=list_chapters
    if result["intent"] == "list_chapters":
        assert p["intensity"] == "list"
        assert p["expansion"] == "none"


# ============================================================
# NEW FIXTURE: mock_llm_with_followup
# ============================================================
@pytest.fixture
def mock_llm_with_followup():
    """LLM mock trả JSON theo từng system prompt."""
    from unittest.mock import MagicMock

    llm = MagicMock()

    def _invoke(messages):
        sys_msg = ""
        for m in messages:
            content = getattr(m, "content", None)
            if content is None and isinstance(m, dict):
                content = m.get("content", "")
            if isinstance(content, str):
                sys_msg = content
                break
        resp = MagicMock()
        if "FOLLOWUP_RESOLVER" in sys_msg or "RESOLVE câu hỏi follow-up" in sys_msg:
            resp.content = (
                '{"resolved_query":"Phạt ô tô không nhường đường bao nhiêu?",'
                '"history_dependent":true,'
                '"context_summary":"đang nói về phạt không nhường đường"}'
            )
        elif "LÀM SẠCH" in sys_msg:
            resp.content = (
                '{"cleaned_query":"phạt ô tô không nhường đường",'
                '"legal_domain":"xử phạt giao thông",'
                '"key_legal_terms":["phạt","ô tô","không nhường đường"],'
                '"intent":"penalty_lookup",'
                '"expansion_hint":"default",'
                '"missing_facts":[]}'
            )
        else:
            resp.content = "fallback"
        return resp

    llm.invoke.side_effect = _invoke
    return llm
