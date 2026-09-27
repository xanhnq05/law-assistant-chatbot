"""
Tests cho B7 - Symbolic Verification (cải tiến).

Bao phủ các tính năng mới:
  P7: Multi-pattern citation regex (match nhiều format)
  P8: Enhanced context_grounded check
  P9: Amendments compliance check (REPEALS/REPLACES)
  P13: Friendly status messages
  P14: Weighted scoring + strict status logic
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.models import VerificationResult, VerificationStatus
from app.rag.steps.verification import (
    _STATUS_MESSAGES,
    _build_status_message,
    _check_amendments_compliance,
    _context_has_citation,
    _extract_citations,
    _llm_judge,
    _parse_llm_json,
    _rule_based_score,
    step_verify_answer,
)


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture
def sample_context_blocks():
    """Mock output của B4 (Hybrid Retrieval) - shape thực tế."""
    return [
        {
            "score": 0.91,
            "citation": "Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4",
            "context_block": (
                "Nghị định 168/2024/NĐ-CP - Xử phạt hành vi không nhường đường\n"
                "  Cơ quan ban hành: Chính phủ | Ngày ban hành: 2024-12-26\n"
                "  Chương II: VI PHẠM QUY TẮC GIAO THÔNG\n"
                "  Điều 6: Xử phạt hành vi không nhường đường\n"
                "    Khoản 4: Phạt tiền từ 4.000.000đ đến 6.000.000đ"
            ),
            "article_number": "6",
            "article_title": "Xử phạt hành vi không nhường đường",
            "clause_number": "4",
            "point_number": "",
            "related_amendments": [],
        },
        {
            "score": 0.85,
            "citation": "Luật 36/2024/QH15 - Điều 15",
            "context_block": (
                "Luật 36/2024/QH15 - Trật tự an toàn giao thông đường bộ\n"
                "  Cơ quan ban hành: Quốc hội | Ngày ban hành: 2024-06-27\n"
                "  Điều 15: Quy tắc nhường đường"
            ),
            "article_number": "15",
            "article_title": "Quy tắc nhường đường",
            "clause_number": "",
            "point_number": "",
            "related_amendments": [
                {
                    "type": "REPEALS",
                    "target_document_type": "Luật",
                    "target_number": "10/2009/QH12",
                    "target_label": "Luật 10/2009/QH12",
                    "reason": "Bị thay thế bởi Luật 36/2024/QH15",
                },
            ],
        },
    ]


@pytest.fixture
def good_answer():
    """Câu trả lời tốt - đầy đủ citation, grounded, friendly."""
    return (
        "Theo Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4, hành vi không nhường đường "
        "bị phạt tiền từ 4.000.000đ đến 6.000.000đ. Đây là quy định rõ ràng về "
        "xử phạt hành vi không nhường đường đối với phương tiện tham gia giao thông."
    )


@pytest.fixture
def mock_verifier_llm():
    """Mock verifier LLM trả về JSON hợp lệ (B7 LLM-as-Judge)."""
    llm = MagicMock()
    resp = MagicMock()
    resp.content = (
        '{"is_grounded":true,"has_citation":true,"citation_correct":true,'
        '"addresses_question":true,"confidence":0.85,"issues":[],"reason":"OK"}'
    )
    llm.invoke.return_value = resp
    return llm


@pytest.fixture
def mock_verifier_llm_factory():
    """Factory mock verifier LLM với response tùy ý."""
    def _make(
        is_grounded=True,
        has_citation=True,
        citation_correct=True,
        addresses_question=True,
        confidence=0.85,
        issues=None,
        reason="OK",
        raise_error=False,
    ):
        llm = MagicMock()
        if raise_error:
            llm.invoke.side_effect = Exception("API timeout")
            return llm
        resp = MagicMock()
        resp.content = (
            f'{{"is_grounded":{str(is_grounded).lower()},'
            f'"has_citation":{str(has_citation).lower()},'
            f'"citation_correct":{str(citation_correct).lower()},'
            f'"addresses_question":{str(addresses_question).lower()},'
            f'"confidence":{confidence},'
            f'"issues":{json_dumps(issues or [])},'
            f'"reason":"{reason}"}}'
        )
        llm.invoke.return_value = resp
        return llm
    return _make


def json_dumps(obj):
    """Helper: dump list thành JSON string."""
    import json
    return json.dumps(obj, ensure_ascii=False)


# ============================================================
# P7: MULTI-PATTERN CITATION EXTRACTION
# ============================================================
class TestCitationExtraction:
    """Test các pattern citation regex mới."""

    # --- Pattern chuẩn ---
    def test_standard_pattern_full(self):
        """'Điều 6, Khoản 4, Điểm a' → match đầy đủ."""
        cits = _extract_citations("Điều 6, Khoản 4, Điểm a")
        assert len(cits) == 1
        assert cits[0] == {"article": "6", "clause": "4", "point": "a"}

    def test_standard_pattern_no_comma(self):
        """'Điều 6 Khoản 4' (không có dấu phẩy) → match."""
        cits = _extract_citations("Điều 6 Khoản 4")
        assert len(cits) == 1
        assert cits[0]["article"] == "6"
        assert cits[0]["clause"] == "4"

    def test_standard_pattern_article_only(self):
        """'Điều 15' → match article only."""
        cits = _extract_citations("Điều 15")
        assert len(cits) == 1
        assert cits[0]["article"] == "15"
        assert cits[0]["clause"] == ""

    # --- Pattern đảo thứ tự ---
    def test_reverse_pattern_khoan_dieu(self):
        """'Khoản 4 Điều 6' → match (đảo thứ tự)."""
        cits = _extract_citations("Theo Khoản 4 Điều 6 Nghị định 168")
        # Phải có ít nhất 1 citation với article=6, clause=4
        valid = [c for c in cits if c["article"] == "6" and c["clause"] == "4"]
        assert len(valid) >= 1, f"Expected citation (6, 4), got {cits}"

    # --- Pattern viết tắt ---
    def test_abbreviated_pattern_dot(self):
        """'Điều 6.4' → match article=6, clause=4."""
        cits = _extract_citations("Theo Điều 6.4 thì phạt 5 triệu")
        valid = [c for c in cits if c["article"] == "6" and c["clause"] == "4"]
        assert len(valid) >= 1, f"Expected citation (6, 4), got {cits}"

    # --- Pattern có ngoặc ---
    def test_parenthesized_pattern(self):
        """'Điều 6 Khoản 4 (Điểm a)' → match đầy đủ 3 levels."""
        cits = _extract_citations("Điều 6 Khoản 4 (Điểm a)")
        valid = [
            c for c in cits
            if c["article"] == "6" and c["clause"] == "4" and c["point"] == "a"
        ]
        assert len(valid) >= 1, f"Expected citation (6, 4, a), got {cits}"

    # --- Edge cases ---
    def test_no_match_returns_empty(self):
        """Không có citation → trả list rỗng."""
        assert _extract_citations("Xin chào bạn") == []
        assert _extract_citations("") == []

    def test_dedup_same_citation(self):
        """Cùng citation xuất hiện 2 lần → chỉ giữ 1."""
        cits = _extract_citations("Điều 6 Khoản 4 và Điều 6 Khoản 4")
        assert len(cits) == 1

    def test_multiple_distinct_citations(self):
        """Nhiều citation khác nhau → giữ tất cả."""
        cits = _extract_citations("Điều 6 Khoản 4 và Điều 7 Khoản 2")
        assert len(cits) == 2
        assert {c["article"] for c in cits} == {"6", "7"}

    def test_lowercase_works(self):
        """Lowercase (in hoa/thường) đều match."""
        cits = _extract_citations("điều 6 khoản 4 điểm a")
        assert len(cits) >= 1
        assert cits[0]["article"] == "6"


# ============================================================
# CONTEXT_HAS_CITATION (helper)
# ============================================================
class TestContextHasCitation:
    """Test matching citation với context_blocks."""

    def test_match_article_clause(self):
        """Citation article+clause match context."""
        ctx = [{"article_number": "6", "clause_number": "4", "point_number": ""}]
        cit = {"article": "6", "clause": "4", "point": ""}
        assert _context_has_citation(ctx, cit) is True

    def test_mismatch_clause_fails(self):
        """Article match nhưng clause không match → fail."""
        ctx = [{"article_number": "6", "clause_number": "4", "point_number": ""}]
        cit = {"article": "6", "clause": "5", "point": ""}
        assert _context_has_citation(ctx, cit) is False

    def test_match_article_only(self):
        """Citation chỉ có article (không có clause) → match article."""
        ctx = [{"article_number": "6", "clause_number": "4", "point_number": ""}]
        cit = {"article": "6", "clause": "", "point": ""}
        assert _context_has_citation(ctx, cit) is True

    def test_article_not_in_context(self):
        """Article không tồn tại trong context → fail."""
        ctx = [{"article_number": "6", "clause_number": "4", "point_number": ""}]
        cit = {"article": "99", "clause": "", "point": ""}
        assert _context_has_citation(ctx, cit) is False


# ============================================================
# P9: AMENDMENTS COMPLIANCE CHECK
# ============================================================
class TestAmendmentsCompliance:
    """Test verify LLM không trích dẫn văn bản REPEALS/REPLACES."""

    def test_repealed_doc_without_ack_flagged(self):
        """Trích dẫn văn bản đã REPEALS mà không acknowledge → warning."""
        answer = "Theo Nghị định 123, Điều 4 thì phạt 1 triệu."
        ctx = [{
            "article_number": "4",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "123",
                "target_label": "Nghị định 123",
            }]
        }]
        result = _check_amendments_compliance(answer, ctx)
        assert result["is_compliant"] is False
        assert len(result["warnings"]) >= 1
        assert any("123" in w for w in result["warnings"])

    def test_repealed_doc_with_ack_ok(self):
        """Trích dẫn văn bản REPEALS + acknowledge → compliant."""
        answer = (
            "Theo Nghị định 123 (đã được thay thế), Điều 4 thì phạt 1 triệu."
        )
        ctx = [{
            "article_number": "4",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "123",
                "target_label": "Nghị định 123",
            }]
        }]
        result = _check_amendments_compliance(answer, ctx)
        assert result["is_compliant"] is True
        assert result["warnings"] == []

    def test_replaces_relationship_checked(self):
        """REPLACES relationship cũng được check."""
        answer = "Theo Luật 10, Điều 5 thì phạt tiền."  # Đề cập Luật 10, không acknowledge
        ctx = [{
            "article_number": "5",
            "related_amendments": [{
                "type": "REPLACES",
                "target_document_type": "Luật",
                "target_number": "10",
                "target_label": "Luật 10/2009/QH12",
            }]
        }]
        result = _check_amendments_compliance(answer, ctx)
        # Match thông qua "Luật 10" trong answer
        assert result["is_compliant"] is False
        assert any("10" in w for w in result["warnings"])

    def test_no_amendments_means_compliant(self):
        """Context không có amendments → compliant."""
        answer = "Theo Điều 6 phạt 5 triệu."
        ctx = [{"article_number": "6", "related_amendments": []}]
        result = _check_amendments_compliance(answer, ctx)
        assert result["is_compliant"] is True

    def test_no_mention_no_warning(self):
        """Answer không đề cập văn bản REPEALS → không warning."""
        answer = "Theo Nghị định 168, Điều 6 thì phạt 5 triệu."
        ctx = [{
            "article_number": "6",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "123",
                "target_label": "Nghị định 123",
            }]
        }]
        result = _check_amendments_compliance(answer, ctx)
        assert result["is_compliant"] is True

    def test_short_number_no_false_positive(self):
        """Số hiệu ngắn (vd '168') không bị match nhầm trong text khác."""
        answer = "168 giờ qua đã xảy ra vụ việc."
        ctx = [{
            "article_number": "5",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "168",
                "target_label": "Nghị định 168",
            }]
        }]
        result = _check_amendments_compliance(answer, ctx)
        # "168" xuất hiện nhưng KHÔNG có prefix "Nghị định" → không match
        assert result["is_compliant"] is True


# ============================================================
# RULE-BASED SCORING (P8, P14)
# ============================================================
class TestRuleBasedScoring:
    """Test rule-based score + amendments integration."""

    def test_empty_answer_zero_score(self):
        """Answer rỗng → score=0."""
        r = _rule_based_score("", [{"article_number": "6"}])
        assert r["score"] == 0.0
        assert "empty_answer" in r["issues"]

    def test_no_citation_detected(self):
        """Không có citation → issue 'no_citation_detected'."""
        r = _rule_based_score("Câu trả lời bình thường", [])
        assert r["has_citation"] is False
        assert any("trích dẫn" in i.lower() for i in r["issues"])

    def test_valid_citation_high_score(self):
        """Citation valid + grounded → score cao (>= 0.7)."""
        blocks = [{
            "article_number": "6",
            "clause_number": "4",
            "article_title": "Xử phạt hành vi không nhường đường",
            "context_block": (
                "Điều 6 Nghị định 168 - Xử phạt hành vi không nhường đường. "
                "Khoản 4: Phạt tiền từ 4 triệu đến 6 triệu đồng. " * 3
            ),
        }]
        answer = (
            "Theo Điều 6 Khoản 4 phạt 4-6 triệu đồng. "
            "Đây là quy định về xử phạt hành vi không nhường đường."
        )
        r = _rule_based_score(answer, blocks)
        assert r["has_citation"] is True
        assert r["cites_valid_doc"] is True
        assert r["context_grounded"] is True
        assert r["amendments_compliant"] is True
        assert r["score"] >= 0.8

    def test_invalid_citation_lower_score(self):
        """Citation trỏ đến điều không tồn tại → score thấp hơn."""
        blocks = [{
            "article_number": "6",
            "clause_number": "4",
            "context_block": "x" * 100,
        }]
        answer = "Theo Điều 999 Khoản 1 phạt tiền."
        r = _rule_based_score(answer, blocks)
        assert r["has_citation"] is True
        assert r["cites_valid_doc"] is False
        assert r["score"] < 0.7

    def test_fallback_message_capped(self):
        """Answer 'không tìm thấy' → score bị cap ở 0.4."""
        r = _rule_based_score(
            "Xin lỗi tôi không tìm thấy thông tin",
            [{"article_number": "6"}],
        )
        assert any("fallback" in i.lower() for i in r["issues"])
        assert r["score"] <= 0.4

    def test_amendments_violation_lowers_score(self):
        """Vi phạm amendments (REPEALS không acknowledge) → score giảm."""
        blocks = [{
            "article_number": "4",
            "context_block": "Điều 4 Nghị định 168 về xử phạt. " * 3,
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "123",
                "target_label": "Nghị định 123",
            }],
        }]
        answer = (
            "Theo Nghị định 123, Điều 4 thì phạt 1 triệu. "
            "Đây là quy định về xử phạt hành vi."
        )
        r = _rule_based_score(answer, blocks)
        assert r["amendments_compliant"] is False
        # 15% amendments score bị trừ
        assert r["score"] < 1.0

    def test_p8_enhanced_grounded_via_title(self):
        """P8: Ground via article_title (≥10 chars)."""
        blocks = [{
            "article_number": "6",
            "article_title": "Xử phạt hành vi không nhường đường",
            "context_block": "x" * 100,  # Không có content hữu ích
        }]
        answer = (
            "Theo Điều 6 thì phạt về xử phạt hành vi không nhường đường. "
            "Mức phạt dao động tùy trường hợp cụ thể."
        )
        r = _rule_based_score(answer, blocks)
        # Article title xuất hiện trong answer → grounded=True
        assert r["context_grounded"] is True


# ============================================================
# LLM JUDGE + JSON PARSER
# ============================================================
class TestJSONParser:
    """Test parser JSON robust."""

    def test_parse_plain_json(self):
        """JSON thuần → parse OK."""
        result = _parse_llm_json('{"is_grounded": true}')
        assert result == {"is_grounded": True}

    def test_parse_markdown_fenced_json(self):
        """JSON trong markdown fence → parse OK."""
        result = _parse_llm_json('```json\n{"is_grounded": true}\n```')
        assert result == {"is_grounded": True}

    def test_parse_trailing_commas(self):
        """JSON có trailing commas → parse OK."""
        result = _parse_llm_json('{"is_grounded": true, "issues": [],}')
        assert result is not None
        assert result["is_grounded"] is True

    def test_parse_json_in_text(self):
        """JSON lẫn trong text → fallback regex tìm được."""
        result = _parse_llm_json(
            'Some text here\n{"is_grounded": true, "confidence": 0.5}\nEnd'
        )
        assert result is not None
        assert result["confidence"] == 0.5

    def test_parse_invalid_returns_none(self):
        """Text không có JSON → trả None."""
        assert _parse_llm_json("Just plain text") is None
        assert _parse_llm_json("") is None


class TestLLMJudge:
    """Test LLM-as-Judge integration."""

    def test_llm_judge_success(self, mock_verifier_llm_factory):
        """Mock LLM trả JSON hợp lệ → judge thành công."""
        llm = mock_verifier_llm_factory(confidence=0.9)
        result = _llm_judge(llm, "Q?", "A", [{"citation": "X", "context_block": "ctx"}])
        assert result["is_grounded"] is True
        assert result["confidence"] == 0.9
        assert "issues" in result

    def test_llm_judge_exception_handled(self, mock_verifier_llm_factory):
        """LLM throw exception → judge trả default failed."""
        llm = mock_verifier_llm_factory(raise_error=True)
        result = _llm_judge(llm, "Q?", "A", [])
        assert result["is_grounded"] is False
        assert result["issues"] == ["llm_judge_failed"]

    def test_llm_judge_bad_json(self):
        """LLM trả content không phải JSON → judge trả default failed."""
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "Not JSON at all, just text"
        llm.invoke.return_value = resp
        result = _llm_judge(llm, "Q?", "A", [])
        assert result["is_grounded"] is False
        assert result["issues"] == ["llm_judge_failed"]


# ============================================================
# FRIENDLY OUTPUT MESSAGES (P13)
# ============================================================
class TestFriendlyMessages:
    """Test message thân thiện cho user."""

    def test_pass_message(self):
        """Status PASS → message tích cực."""
        msg = _build_status_message(VerificationStatus.PASS, [])
        assert "✅" in msg
        assert "Đạt" in msg

    def test_warn_message(self):
        """Status WARN → message cảnh báo."""
        msg = _build_status_message(VerificationStatus.WARN, [])
        assert "⚠️" in msg
        assert "Cảnh báo" in msg or "cảnh báo" in msg

    def test_fail_message(self):
        """Status FAIL → message thất bại."""
        msg = _build_status_message(VerificationStatus.FAIL, [])
        assert "❌" in msg
        assert "Không đạt" in msg or "không đạt" in msg

    def test_issues_listed(self):
        """Issues được list dạng bullet."""
        msg = _build_status_message(
            VerificationStatus.FAIL,
            ["Issue 1", "Issue 2"],
        )
        assert "• Issue 1" in msg
        assert "• Issue 2" in msg


# ============================================================
# STEP VERIFY ANSWER - FULL PIPELINE
# ============================================================
class TestStepVerifyAnswer:
    """Test step_verify_answer tích hợp đầy đủ."""

    def test_pass_full_match(self, mock_verifier_llm_factory, sample_context_blocks, good_answer):
        """Answer tốt + context match → PASS."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(
            llm,
            "Phạt bao nhiêu?",
            good_answer,
            sample_context_blocks,
        )
        assert r.status == VerificationStatus.PASS
        assert r.confidence > 0.6
        assert r.has_citation is True
        assert r.cites_valid_doc is True

    def test_fail_no_citation(self, mock_verifier_llm_factory, sample_context_blocks):
        """Không có citation → FAIL (theo strict status logic)."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(
            llm,
            "Phạt bao nhiêu?",
            "Phạt tiền tùy trường hợp.",
            sample_context_blocks,
        )
        assert r.status == VerificationStatus.FAIL
        assert r.has_citation is False
        assert any("trích dẫn" in i.lower() for i in r.issues)

    def test_fail_invalid_citation(self, mock_verifier_llm_factory, sample_context_blocks):
        """Citation trỏ đến điều không tồn tại → FAIL (strict)."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(
            llm,
            "Phạt bao nhiêu?",
            "Theo Điều 999 Khoản 1 phạt rất nặng.",
            sample_context_blocks,
        )
        assert r.cites_valid_doc is False
        assert r.status == VerificationStatus.FAIL

    def test_warn_with_partial_match(self, mock_verifier_llm_factory, sample_context_blocks):
        """Citation hợp lệ nhưng không grounded → FAIL theo strict."""
        llm = mock_verifier_llm_factory()
        # Có citation hợp lệ nhưng nội dung "lung tung"
        answer = "Theo Điều 6 thì trời sẽ mưa to."
        r = step_verify_answer(
            llm,
            "Phạt bao nhiêu?",
            answer,
            sample_context_blocks,
        )
        # context_grounded=False → FAIL
        assert r.status == VerificationStatus.FAIL
        assert r.context_grounded is False

    def test_without_llm_judge(self, sample_context_blocks, good_answer):
        """Tắt LLM judge → chỉ chạy rule-based."""
        r = step_verify_answer(
            verifier_llm=None,
            question="Phạt bao nhiêu?",
            answer=good_answer,
            context_blocks=sample_context_blocks,
            use_llm_judge=False,
        )
        assert r.llm_judge_used is False
        assert r.llm_judge_reason is None

    def test_with_llm_judge(self, mock_verifier_llm, sample_context_blocks, good_answer):
        """Bật LLM judge → có llm_reason."""
        r = step_verify_answer(
            mock_verifier_llm,
            "Phạt bao nhiêu?",
            good_answer,
            sample_context_blocks,
            use_llm_judge=True,
        )
        assert r.llm_judge_used is True
        assert r.llm_judge_reason is not None

    def test_with_legal_context(self, mock_verifier_llm_factory, good_answer):
        """legal_context thay thế context_blocks."""
        from app.rag.schemas.legal_context import EvidenceItem, LegalContext, RequestInfo

        items = [
            EvidenceItem(
                evidence_id="EV-001",
                context_block=(
                    "Điều 6 Nghị định 168 - Xử phạt hành vi không nhường đường. "
                    "Khoản 4: Phạt tiền từ 4-6 triệu đồng. " * 2
                ),
                metadata={
                    "article_number": "6",
                    "clause_number": "4",
                    "article_title": "Xử phạt hành vi không nhường đường",
                    "related_amendments": [],
                },
            )
        ]
        lc = LegalContext(
            request=RequestInfo(
                original_query="test",
                normalized_query="test",
                retrieval_query="test",
            ),
            evidence=items,
        )

        llm = mock_verifier_llm_factory()
        r = step_verify_answer(
            llm,
            "Phạt bao nhiêu?",
            good_answer,
            legal_context=lc,
        )
        # Evidence từ legal_context được convert → vẫn verify OK
        assert r.cites_valid_doc is True

    def test_amendments_violation_warns(self, mock_verifier_llm_factory):
        """Verify câu trả lời trích dẫn văn bản REPEALS không acknowledge."""
        llm = mock_verifier_llm_factory()
        ctx = [{
            "article_number": "4",
            "context_block": "Điều 4 Nghị định 168. " * 5,
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "123",
                "target_label": "Nghị định 123",
            }],
        }]
        answer = (
            "Theo Nghị định 123, Điều 4 thì phạt 1 triệu. "
            "Đây là quy định về xử phạt hành vi cụ thể."
        )
        r = step_verify_answer(llm, "Test?", answer, ctx)
        # amendments_compliant=False → không phải PASS
        assert r.status != VerificationStatus.PASS
        assert any("123" in i or "thay thế" in i.lower() for i in r.issues)

    def test_returns_verification_result_type(self, mock_verifier_llm_factory, sample_context_blocks, good_answer):
        """Return type phải là VerificationResult."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(llm, "Q?", good_answer, sample_context_blocks)
        assert isinstance(r, VerificationResult)

    def test_confidence_in_valid_range(self, mock_verifier_llm_factory, sample_context_blocks, good_answer):
        """Confidence phải nằm trong [0.0, 1.0]."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(llm, "Q?", good_answer, sample_context_blocks)
        assert 0.0 <= r.confidence <= 1.0


# ============================================================
# EDGE CASES
# ============================================================
class TestEdgeCases:
    """Test các trường hợp biên."""

    def test_answer_with_unicode(self, mock_verifier_llm_factory, sample_context_blocks):
        """Câu trả lời có ký tự đặc biệt / emoji."""
        llm = mock_verifier_llm_factory()
        answer = (
            "Theo Điều 6, Khoản 4, Nghị định 168 ⚠️ phạt từ 4-6 triệu 💰. "
            "Đây là quy định về xử phạt."
        )
        r = step_verify_answer(llm, "Q?", answer, sample_context_blocks)
        assert r is not None

    def test_answer_with_only_whitespace(self, mock_verifier_llm_factory, sample_context_blocks):
        """Câu trả lời chỉ có whitespace → empty handling."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(llm, "Q?", "   \n  ", sample_context_blocks)
        # Empty answer → score thấp
        assert r.confidence < 0.5
        assert r.status == VerificationStatus.FAIL

    def test_very_long_answer(self, mock_verifier_llm_factory, sample_context_blocks):
        """Câu trả lời rất dài."""
        llm = mock_verifier_llm_factory()
        long_answer = "Theo Điều 6 Khoản 4 phạt. " * 500
        r = step_verify_answer(llm, "Q?", long_answer, sample_context_blocks)
        assert r is not None

    def test_context_with_special_amendments(self, mock_verifier_llm_factory):
        """Context có amendment với type khác (không phải REPEALS/REPLACES)."""
        llm = mock_verifier_llm_factory()
        ctx = [{
            "article_number": "6",
            "context_block": "Điều 6 Nghị định 168. " * 5,
            "related_amendments": [
                {"type": "AMENDS", "target_label": "Điều 5"},
                {"type": "ADDS", "target_label": "Khoản mới"},
            ],
        }]
        answer = "Theo Điều 6 thì phạt tiền. Nội dung về xử phạt hành chính."
        r = step_verify_answer(llm, "Q?", answer, ctx)
        # AMENDS/ADDS không trigger compliance check → compliant=True
        assert any(
            "trích dẫn" in i.lower() or "xử phạt" in i.lower()
            for i in r.issues
        ) or r.cites_valid_doc is True

    def test_amendments_malformed(self, mock_verifier_llm_factory):
        """Amendment thiếu fields → không crash."""
        llm = mock_verifier_llm_factory()
        ctx = [{
            "article_number": "6",
            "context_block": "Điều 6. " * 5,
            "related_amendments": [
                {"type": "REPEALS"},  # Thiếu target_*
            ],
        }]
        answer = "Theo Điều 6 phạt tiền."
        r = step_verify_answer(llm, "Q?", answer, ctx)
        # Không crash
        assert r is not None


# ============================================================
# COVERAGE: Helper functions + defensive branches
# ============================================================
class TestDocPrefixHelper:
    """Test helper _extract_doc_prefix (debug/logging)."""

    def test_extract_nghi_dinh(self):
        """Trích xuất 'Nghị định' prefix."""
        from app.rag.steps.verification import _extract_doc_prefix
        result = _extract_doc_prefix("Nghị định 168/2024/NĐ-CP về xử phạt")
        # Lưu ý: split()[0] chỉ lấy "Nghị", không phải "Nghị định"
        assert "168/2024/NĐ-CP" in result
        assert result.startswith("Nghị")

    def test_extract_luat(self):
        """Trích xuất 'Luật' prefix."""
        from app.rag.steps.verification import _extract_doc_prefix
        result = _extract_doc_prefix("Luật 36/2024/QH15")
        assert result == "Luật 36/2024/QH15"

    def test_no_match_returns_none(self):
        """Không có prefix → None."""
        from app.rag.steps.verification import _extract_doc_prefix
        assert _extract_doc_prefix("abc def ghi") is None

    def test_empty_input_returns_none(self):
        """Input rỗng → None (defensive)."""
        from app.rag.steps.verification import _extract_doc_prefix
        assert _extract_doc_prefix("") is None
        assert _extract_doc_prefix(None) is None


class TestCoverageHelpers:
    """Test các branch defensive chưa cover."""

    def test_parse_uppercase_json_marker(self):
        """```JSON (uppercase) → strip OK."""
        result = _parse_llm_json('```JSON\n{"x": 1}\n```')
        assert result == {"x": 1}

    def test_parse_json_in_text_with_exception(self):
        """JSON trong text mà parse fail → trả None."""
        # Nội dung có dạng "{...}" nhưng JSON invalid
        result = _parse_llm_json("text {not valid json} more text")
        assert result is None

    def test_llm_judge_dict_response(self):
        """LLM trả dict trực tiếp (không phải object với .content)."""
        llm = MagicMock()
        # Trả về dict, không phải MagicMock có .content
        llm.invoke.return_value = {
            "content": '{"is_grounded": true, "confidence": 0.7}'
        }
        result = _llm_judge(llm, "Q?", "A", [])
        assert result["is_grounded"] is True
        assert result["confidence"] == 0.7

    def test_llm_judge_object_without_content(self):
        """LLM trả object không có .content → fallback empty."""
        llm = MagicMock()
        resp = MagicMock(spec=[])  # spec=[] → không có .content
        llm.invoke.return_value = resp
        result = _llm_judge(llm, "Q?", "A", [])
        # content="" → parse fail → fallback
        assert result["issues"] == ["llm_judge_failed"]

    def test_context_has_citation_clause_in_citation_but_not_in_ctx(self):
        """Citation có clause, context không có clause → vẫn match."""
        # Clause in citation nhưng context.clause_number rỗng → match article
        ctx = [{"article_number": "6", "clause_number": "", "point_number": ""}]
        cit = {"article": "6", "clause": "4", "point": ""}
        assert _context_has_citation(ctx, cit) is True

    def test_context_has_citation_point_mismatch(self):
        """Citation có point, context có point khác → fail."""
        ctx = [{"article_number": "6", "clause_number": "4", "point_number": "a"}]
        cit = {"article": "6", "clause": "4", "point": "b"}
        assert _context_has_citation(ctx, cit) is False


class TestAmendmentsBranches:
    """Cover các sub-branch trong _check_amendments_compliance."""

    def test_target_full_match(self):
        """'Nghị định 123' (full doc_type + number) trong answer → match."""
        answer = "Nghị định 123 quy định rõ về xử phạt."  # Không acknowledge
        ctx = [{
            "article_number": "5",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "123",
                "target_label": "Nghị định 123",
            }],
        }]
        result = _check_amendments_compliance(answer, ctx)
        # "nghị định 123" trong answer → mentioned=True
        assert result["is_compliant"] is False

    def test_target_number_with_so_prefix(self):
        """'Số 168' format → detect."""
        answer = "Theo văn bản số 168 thì phạt tiền."  # Không acknowledge
        ctx = [{
            "article_number": "5",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Nghị định",
                "target_number": "168",
                "target_label": "Nghị định 168",
            }],
        }]
        result = _check_amendments_compliance(answer, ctx)
        assert result["is_compliant"] is False

    def test_amendments_other_type_ignored(self):
        """Amendment type AMENDS/ADDS → không check compliance."""
        answer = "Nội dung bình thường"
        ctx = [{
            "article_number": "5",
            "related_amendments": [
                {"type": "AMENDS", "target_label": "Điều 5"},
                {"type": "ADDS", "target_label": "Khoản mới"},
                {"type": "REFERENCES", "target_label": "Điều 10"},
            ],
        }]
        result = _check_amendments_compliance(answer, ctx)
        # Không có REPEALS/REPLACES → compliant
        assert result["is_compliant"] is True


class TestStatusBranches:
    """Test các status branch (PASS/WARN/FAIL transition)."""

    def test_warn_status_when_partial_match(self, mock_verifier_llm_factory):
        """Score ở khoảng giữa → WARN (không FAIL do có citation valid)."""
        llm = mock_verifier_llm_factory(confidence=0.2)  # LLM judge thấp
        # Citation valid nhưng nội dung "nửa vời" → 1 signal → không grounded
        # Nhưng có citation hợp lệ
        ctx = [{
            "article_number": "6",
            "clause_number": "4",
            "context_block": "Điều 6 về xử phạt. " * 10,
            "related_amendments": [],
        }]
        # Answer có citation hợp lệ nhưng không có content match
        answer = "Theo Điều 6 Khoản 4 thì phạt tiền."
        r = step_verify_answer(
            llm,
            "Q?",
            answer,
            ctx,
            use_llm_judge=True,
        )
        # Context grounded = False (chỉ có 1 signal: article_number)
        # → FAIL theo strict logic
        assert r.status == VerificationStatus.FAIL

    def test_low_score_fail(self, mock_verifier_llm_factory):
        """Score rất thấp + LLM judge thấp → FAIL."""
        llm = mock_verifier_llm_factory(confidence=0.0)
        ctx = [{"article_number": "6", "context_block": "Điều 6. " * 5}]
        answer = "Tôi không tìm thấy thông tin."
        r = step_verify_answer(llm, "Q?", answer, ctx, use_llm_judge=True)
        # fallback_no_context → capped 0.4 → score < 0.5 threshold
        assert r.status == VerificationStatus.FAIL


class TestEvidenceToBlock:
    """Test B5 integration: EvidenceItem → context_block."""

    def test_evidence_with_metadata(self):
        """Evidence có metadata → merge vào block."""
        from app.rag.steps.verification import _evidence_to_block
        from app.rag.schemas.legal_context import EvidenceItem, StableId

        ev = EvidenceItem(
            evidence_id="EV-001",
            context_block="Điều 6...",
            metadata={
                "article_number": "6",
                "extra_field": "value",
            },
            stable_id=StableId(),
        )
        block = _evidence_to_block(ev)
        assert block["article_number"] == "6"
        assert block["extra_field"] == "value"
        assert block["evidence_id"] == "EV-001"

    def test_evidence_without_metadata(self):
        """Evidence metadata={} + stable_id có fields → block populate từ stable_id."""
        from app.rag.steps.verification import _evidence_to_block
        from app.rag.schemas.legal_context import EvidenceItem, StableId

        ev = EvidenceItem(
            evidence_id="EV-002",
            context_block="Điều 6...",
            metadata={},  # Pydantic yêu cầu dict, không chấp nhận None
            stable_id=StableId(
                article_id="art-123",
                clause_id="clause-456",
                document_id="doc-789",
            ),
        )
        block = _evidence_to_block(ev)
        assert block["article_id"] == "art-123"
        assert block["clause_id"] == "clause-456"
        assert block["law_document_id"] == "doc-789"
        assert block["evidence_id"] == "EV-002"

    def test_evidence_with_existing_article_id_not_overwritten(self):
        """Metadata đã có article_id → KHÔNG overwrite."""
        from app.rag.steps.verification import _evidence_to_block
        from app.rag.schemas.legal_context import EvidenceItem, StableId

        ev = EvidenceItem(
            evidence_id="EV-003",
            context_block="...",
            metadata={"article_id": "existing-id"},
            stable_id=StableId(article_id="new-id"),
        )
        block = _evidence_to_block(ev)
        assert block["article_id"] == "existing-id"  # Không bị overwrite


class TestFinalCoverage:
    """Cover các defensive branch còn lại → 100%."""

    def test_extract_citations_empty_groups(self):
        """Pattern match nhưng groups rỗng → skip (defensive)."""
        # Khó test trực tiếp vì regex có groups bắt buộc
        # Test gián tiếp: chuỗi đặc biệt không crash
        result = _extract_citations("Điều ")
        assert result == []

    def test_context_has_citation_empty_article(self):
        """Citation không có article → return False (defensive)."""
        cit = {"article": "", "clause": "", "point": ""}
        assert _context_has_citation([{"article_number": "6"}], cit) is False

    def test_amendments_short_number_regex(self):
        """Short number với prefix đầy đủ → regex match."""
        # target_number="5" (chỉ 1 ký tự) → regex vẫn match
        answer = "Theo Luật 5 thì quy định rõ."  # Luật 5 (không acknowledge)
        ctx = [{
            "article_number": "1",
            "related_amendments": [{
                "type": "REPEALS",
                "target_document_type": "Luật",
                "target_number": "5",
                "target_label": "Luật 5",
            }],
        }]
        result = _check_amendments_compliance(answer, ctx)
        # "Luật 5" trong answer → mentioned → not compliant
        assert result["is_compliant"] is False

    def test_content_match_different_lengths(self):
        """Content body match ở nhiều length (30/50/80) → grounded=True."""
        # Body phải đủ dài để match length 30+80
        ctx = [{
            "article_number": "6",
            "context_block": (
                "Điều 6\n"
                + "Nội dung xử phạt chi tiết theo quy định pháp luật. " * 3
            ),
            "article_title": "",  # Không có title → phụ thuộc vào content
        }]
        answer = (
            "Theo Điều 6 thì áp dụng. "
            "Nội dung xử phạt chi tiết theo quy định pháp luật. " * 3
        )
        r = _rule_based_score(answer, [ctx[0]])
        # 2 signals: article + content_match → grounded=True
        assert r["context_grounded"] is True

    def test_step_verify_with_none_context_blocks(self, mock_verifier_llm_factory):
        """context_blocks=None → fallback []."""
        llm = mock_verifier_llm_factory()
        answer = "Theo Điều 6 thì phạt."
        r = step_verify_answer(
            llm,
            "Q?",
            answer,
            context_blocks=None,  # Truyền None
        )
        assert r is not None

    def test_step_verify_llm_judge_with_issues(self, mock_verifier_llm_factory):
        """LLM judge trả issues → thêm vào issues list."""
        llm = mock_verifier_llm_factory(
            confidence=0.5,
            issues=["potential_hallucination", "unclear_citation"],
        )
        ctx = [{"article_number": "6", "context_block": "Điều 6. " * 5}]
        answer = "Theo Điều 6 thì phạt tiền."
        r = step_verify_answer(
            llm,
            "Q?",
            answer,
            ctx,
            use_llm_judge=True,
        )
        # Issues phải được tag [LLM Judge]
        assert any("[LLM Judge]" in i for i in r.issues)
        assert any("potential_hallucination" in i for i in r.issues)

    def test_warn_status_partial_score(self, mock_verifier_llm_factory):
        """Citation valid + có content match → grounded=True → PASS."""
        # Mock LLM, disable LLM judge để final_score = rule_score
        llm = mock_verifier_llm_factory()
        ctx = [{
            "article_number": "6",
            "context_block": (
                "Điều 6\n"
                + "Nội dung xử phạt chi tiết theo quy định. " * 5
            ),
            "article_title": "",
        }]
        answer = (
            "Theo Điều 6 thì phạt tiền. "
            "Nội dung xử phạt chi tiết theo quy định. " * 5
        )
        r = step_verify_answer(
            llm,
            "Q?",
            answer,
            ctx,
            use_llm_judge=False,
        )
        # Citation valid + article match + content match → 3 signals → grounded
        # Score = 0.30 + 0.25 + 0.30 + 0.15 = 1.0 → PASS
        assert r.status == VerificationStatus.PASS

    def test_fail_low_score_fallback(self, mock_verifier_llm_factory):
        """Fallback answer → FAIL (score capped 0.4)."""
        llm = mock_verifier_llm_factory()
        r = step_verify_answer(
            llm,
            "Q?",
            "Tôi không đủ thông tin để trả lời.",
            [{"article_number": "6"}],
            use_llm_judge=False,
        )
        # fallback_no_context → score ≤ 0.4 → FAIL
        assert r.status == VerificationStatus.FAIL
        assert any("fallback" in i.lower() for i in r.issues)
