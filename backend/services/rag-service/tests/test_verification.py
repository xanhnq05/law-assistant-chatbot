"""Tests cho B7 - Symbolic Verification."""
from __future__ import annotations

from core.models import VerificationStatus
from rag.steps.verification import (
    _extract_citations,
    _rule_based_score,
    step_verify_answer,
)


# ============================================================
# CITATION EXTRACTION
# ============================================================
def test_extract_citations_full():
    text = "Điều 6, Khoản 4, Điểm a"
    cits = _extract_citations(text)
    assert len(cits) == 1
    assert cits[0] == {"article": "6", "clause": "4", "point": "a"}


def test_extract_citations_article_only():
    text = "Điều 15"
    cits = _extract_citations(text)
    assert len(cits) == 1
    assert cits[0]["article"] == "15"
    assert cits[0]["clause"] == ""


def test_extract_citations_dedup():
    text = "Điều 6 Khoản 4 và Điều 6 Khoản 4"
    cits = _extract_citations(text)
    assert len(cits) == 1


def test_extract_citations_no_match():
    cits = _extract_citations("Xin chào bạn")
    assert cits == []


# ============================================================
# RULE-BASED SCORE
# ============================================================
def test_rule_score_empty_answer():
    r = _rule_based_score("", [{"article_number": "6"}])
    assert r["has_citation"] is False
    assert r["score"] == 0.0
    assert "empty_answer" in r["issues"]


def test_rule_score_no_citation():
    r = _rule_based_score("Câu trả lời bình thường không có citation", [])
    assert r["has_citation"] is False
    assert "no_citation_detected" in r["issues"]


def test_rule_score_with_valid_citation():
    blocks = [{"article_number": "6", "clause_number": "4", "context_block": "x" * 60}]
    answer = "Theo Điều 6 Khoản 4 phạt 4-6 triệu"
    r = _rule_based_score(answer, blocks)
    assert r["has_citation"] is True
    assert r["cites_valid_doc"] is True
    assert r["score"] >= 0.7


def test_rule_score_with_invalid_citation():
    blocks = [{"article_number": "6", "clause_number": "4", "context_block": "x" * 60}]
    answer = "Theo Điều 999 Khoản 1 phạt tiền"  # Điều 999 không tồn tại
    r = _rule_based_score(answer, blocks)
    assert r["has_citation"] is True
    assert r["cites_valid_doc"] is False
    assert "citation_not_in_context" in r["issues"]


def test_rule_score_fallback_message():
    r = _rule_based_score("Xin lỗi tôi không tìm thấy thông tin", [])
    assert "fallback_no_context" in r["issues"]
    assert r["score"] <= 0.4


# ============================================================
# STEP VERIFY ANSWER (full)
# ============================================================
def test_step_verify_pass(mock_llm, sample_context_blocks):
    answer = "Theo Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4, phạt 4-6 triệu"
    r = step_verify_answer(mock_llm, "Phạt bao nhiêu?", answer, sample_context_blocks)
    assert r.status == VerificationStatus.PASS
    assert r.confidence > 0.6
    assert r.has_citation is True
    assert r.cites_valid_doc is True


def test_step_verify_warn_or_fail_no_citation(mock_llm, sample_context_blocks):
    answer = "Phạt tiền tùy trường hợp"  # không có citation
    r = step_verify_answer(mock_llm, "Phạt bao nhiêu?", answer, sample_context_blocks)
    assert r.status in (VerificationStatus.WARN, VerificationStatus.FAIL)
    assert r.has_citation is False


def test_step_verify_with_invalid_citation(mock_llm, sample_context_blocks):
    answer = "Theo Điều 999, phạt rất nặng"  # Điều 999 không có trong context
    r = step_verify_answer(mock_llm, "Phạt bao nhiêu?", answer, sample_context_blocks)
    assert r.cites_valid_doc is False
    assert "citation_not_in_context" in r.issues


def test_step_verify_with_empty_context(mock_llm):
    answer = "Theo Điều 6, phạt tiền"
    r = step_verify_answer(mock_llm, "test", answer, [])
    # Citation không match với context rỗng
    assert r.cites_valid_doc is False
    assert r.status in (VerificationStatus.WARN, VerificationStatus.FAIL)


def test_step_verify_without_llm_judge(sample_context_blocks):
    """Tắt LLM-as-Judge, chỉ chạy rule-based."""
    answer = "Theo Điều 6 Khoản 4 phạt 4-6 triệu"
    r = step_verify_answer(
        verifier_llm=None,
        question="Phạt bao nhiêu?",
        answer=answer,
        context_blocks=sample_context_blocks,
        use_llm_judge=False,
    )
    assert r.llm_judge_used is False
    assert r.llm_judge_reason is None


def test_step_verify_llm_judge_called(mock_llm, sample_context_blocks):
    answer = "Theo Điều 6 Khoản 4 phạt 4-6 triệu"
    r = step_verify_answer(
        mock_llm,
        "Phạt bao nhiêu?",
        answer,
        sample_context_blocks,
        use_llm_judge=True,
    )
    assert r.llm_judge_used is True
    assert r.llm_judge_reason is not None
