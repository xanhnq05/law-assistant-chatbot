"""Tests cho B2 - Query Cleaner."""
from __future__ import annotations

from rag.steps.cleaner import (
    _detect_intent_heuristic,
    _extract_citations,
    _rule_based_clean,
    step_clean_query,
)


def test_rule_based_clean_removes_filler():
    q = "cho mình hỏi phạt bao nhiêu khi đi xe máy ạ?"
    out = _rule_based_clean(q)
    assert "cho mình hỏi" not in out
    assert "ạ" not in out
    assert "phạt" in out


def test_rule_based_clean_normalize_whitespace():
    q = "  phạt    bao    nhiêu   "
    assert _rule_based_clean(q) == "phạt bao nhiêu"


def test_detect_intent_penalty():
    assert _detect_intent_heuristic("phạt bao nhiêu khi vượt đèn đỏ") == "penalty_lookup"
    assert _detect_intent_heuristic("Mức phạt tiền là bao nhiêu") == "penalty_lookup"


def test_detect_intent_rule():
    assert _detect_intent_heuristic("Quy tắc nhường đường là gì?") == "rule_lookup"


def test_detect_intent_procedure():
    assert _detect_intent_heuristic("Thủ tục thi GPLX như thế nào?") == "procedure_lookup"


def test_detect_intent_general():
    assert _detect_intent_heuristic("Xin chào bạn") == "general_info"


def test_extract_citations_single():
    text = "Theo Điều 6 Khoản 4 phạt tiền 4-6 triệu"
    cits = _extract_citations(text)
    assert len(cits) == 1
    assert cits[0]["article"] == "6"
    assert cits[0]["clause"] == "4"


def test_extract_citations_multiple():
    text = "Điều 6 Khoản 4 Điểm a và Điều 7 Khoản 1"
    cits = _extract_citations(text)
    assert len(cits) == 2


def test_step_clean_query_with_llm(mock_llm):
    q = "Cho mình hỏi phạt bao nhiêu khi đi xe máy không nhường đường ạ?"
    result = step_clean_query(mock_llm, q)
    assert result["cleaned_query"]
    assert "phạt" in result["cleaned_query"].lower() or "xe" in result["cleaned_query"].lower()
    assert result["intent"] == "penalty_lookup"
    assert "phạt" in result["key_legal_terms"]


def test_step_clean_query_without_llm_fallback():
    q = "phạt bao nhiêu khi đi xe máy không nhường đường?"
    result = step_clean_query(None, q)
    assert result["cleaned_query"] == q  # no filler to remove
    assert result["intent"] == "penalty_lookup"
