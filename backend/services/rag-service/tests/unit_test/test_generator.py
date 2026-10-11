"""
Tests cho B6 - LLM Generation (cải tiến).

Bao phủ các tính năng mới:
  - Fix history reordering bug
  - Smart context truncation theo evidence boundaries
  - Phân loại lỗi LLM chi tiết (rate-limit / timeout / auth / generic)
  - Tích hợp LegalContext
  - Pre-flight checks (question rỗng, llm None)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.rag.steps.generator import (
    HARD_CONTEXT_LIMIT,
    LLM_ERROR_MSG,
    MAX_HISTORY_PAIRS,
    NO_CONTEXT_MSG,
    SOFT_CONTEXT_LIMIT,
    _build_context_from_evidence,
    _build_history_text,
    _classify_llm_error,
    step_generate_answer,
)


# ============================================================
# FIXTURES
# ============================================================
@pytest.fixture
def mock_llm_factory():
    """Factory tạo mock LLM với content tùy ý."""
    def _make(content: str = "Theo Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4, phạt 4-6 triệu đồng."):
        llm = MagicMock()
        resp = MagicMock()
        resp.content = content
        llm.invoke.return_value = resp
        return llm
    return _make


@pytest.fixture
def sample_evidence():
    """Sample evidence list (output của B5 LegalContext)."""
    return [
        {
            "evidence_id": "EV-001",
            "context_block": (
                "Nghị định 168/2024/NĐ-CP - Xử phạt hành vi không nhường đường\n"
                "  Cơ quan ban hành: Chính phủ | Ngày ban hành: 2024-12-26\n"
                "  Điều 6: Xử phạt hành vi không nhường đường\n"
                "    Khoản 4: Phạt tiền từ 4.000.000đ đến 6.000.000đ"
            ),
            "scores": {"final_score": 0.91},
        },
        {
            "evidence_id": "EV-002",
            "context_block": (
                "Luật 36/2024/QH15 - Trật tự an toàn giao thông đường bộ\n"
                "  Cơ quan ban hành: Quốc hội | Ngày ban hành: 2024-06-27\n"
                "  Điều 15: Quy tắc nhường đường"
            ),
            "scores": {"final_score": 0.85},
        },
        {
            "evidence_id": "EV-003",
            "context_block": "Xử phạt nặng hơn nếu gây tai nạn.",
            "scores": {"final_score": 0.70},
        },
    ]


@pytest.fixture
def mock_legal_context(sample_evidence):
    """Mock LegalContext cho B5 → B6 integration."""
    from app.rag.schemas.legal_context import EvidenceItem, LegalContext
    items = [
        EvidenceItem(
            evidence_id=ev["evidence_id"],
            context_block=ev["context_block"],
        )
        for ev in sample_evidence
    ]
    return items  # trả về list[EvidenceItem] để test trực tiếp


# ============================================================
# PRE-FLIGHT CHECKS
# ============================================================
class TestPreFlight:
    """Kiểm tra validation đầu vào."""

    def test_empty_question_returns_prompt_message(self, mock_llm_factory):
        """Câu hỏi rỗng → trả message yêu cầu nhập."""
        llm = mock_llm_factory()
        answer = step_generate_answer(llm, "", "Có context")
        assert answer == "Vui lòng nhập câu hỏi."

    def test_whitespace_only_question_returns_prompt_message(self, mock_llm_factory):
        """Câu hỏi chỉ có whitespace → trả message yêu cầu nhập."""
        llm = mock_llm_factory()
        answer = step_generate_answer(llm, "   \n  ", "Có context")
        assert answer == "Vui lòng nhập câu hỏi."

    def test_no_llm_raises_runtime_error(self):
        """llm=None → RuntimeError rõ ràng."""
        with pytest.raises(RuntimeError, match="LLM chưa được khởi tạo"):
            step_generate_answer(None, "Câu hỏi?", "Context")

    def test_no_context_returns_fallback(self, mock_llm_factory):
        """Context rỗng + không có legal_context → NO_CONTEXT_MSG."""
        llm = mock_llm_factory()
        answer = step_generate_answer(llm, "Phạt bao nhiêu?", "")
        assert answer == NO_CONTEXT_MSG

    def test_whitespace_context_returns_fallback(self, mock_llm_factory):
        """Context chỉ có whitespace → NO_CONTEXT_MSG."""
        llm = mock_llm_factory()
        answer = step_generate_answer(llm, "test?", "   \n  ")
        assert answer == NO_CONTEXT_MSG


# ============================================================
# BASIC GENERATION (backward compat)
# ============================================================
class TestBasicGeneration:
    """Test generation cơ bản — backward compatible."""

    def test_generate_with_context(self, mock_llm):
        """Có context → LLM được gọi và trả câu trả lời."""
        answer = step_generate_answer(
            mock_llm,
            "Phạt bao nhiêu?",
            "Điều 6 Khoản 4: phạt 4-6 triệu",
        )
        assert "Nghị định 168" in answer
        assert "Điều 6" in answer
        mock_llm.invoke.assert_called_once()

    def test_generate_with_history(self, mock_llm):
        """Có history → LLM nhận prompt có lịch sử hội thoại."""
        from langchain_core.messages import HumanMessage
        history = [
            {"role": "user", "content": "Vượt đèn đỏ phạt bao nhiêu?"},
            {"role": "assistant", "content": "Phạt 4-6 triệu."},
        ]
        step_generate_answer(
            mock_llm,
            "Còn xe máy thì sao?",
            "Context về xe máy",
            history=history,
        )
        # Verify prompt có chứa history
        call_args = mock_llm.invoke.call_args
        messages = call_args[0][0]
        # Tìm HumanMessage (LangChain class)
        human_msg = next(m for m in messages if isinstance(m, HumanMessage))
        assert "Còn xe máy" in human_msg.content
        assert "Vượt đèn đỏ" in human_msg.content
        assert "Lịch sử hội thoại" in human_msg.content


# ============================================================
# P0: HISTORY REORDERING FIX
# ============================================================
class TestHistoryReordering:
    """Verify bug reordering đã fix — giữ đúng thứ tự thời gian."""

    def test_history_chronological_order(self):
        """History giữ đúng thứ tự thời gian (chronological)."""
        history = [
            {"role": "user", "content": "Câu 1"},
            {"role": "assistant", "content": "Trả lời 1"},
            {"role": "user", "content": "Câu 2"},
            {"role": "assistant", "content": "Trả lời 2"},
            {"role": "user", "content": "Câu 3"},
            {"role": "assistant", "content": "Trả lời 3"},
        ]
        text = _build_history_text(history)
        # Câu 1 phải xuất hiện trước Câu 3
        pos_1 = text.find("Câu 1")
        pos_2 = text.find("Câu 2")
        pos_3 = text.find("Câu 3")
        assert pos_1 != -1 and pos_2 != -1 and pos_3 != -1
        assert pos_1 < pos_2 < pos_3, f"History not chronological: 1={pos_1}, 2={pos_2}, 3={pos_3}"

    def test_history_only_keeps_last_n_pairs(self):
        """Chỉ giữ MAX_HISTORY_PAIRS cặp cuối."""
        history = []
        # Tạo 10 cặp (20 msg)
        for i in range(10):
            history.append({"role": "user", "content": f"Câu cũ {i}"})
            history.append({"role": "assistant", "content": f"Trả lời cũ {i}"})

        text = _build_history_text(history)

        # Cặp cuối (Câu cũ 8, 9) phải có
        assert "Câu cũ 8" in text or "Câu cũ 9" in text
        # Cặp cũ (Câu cũ 0, 1) phải bị drop
        assert "Câu cũ 0" not in text
        assert "Câu cũ 1" not in text

    def test_history_empty_returns_empty_string(self):
        """History None hoặc rỗng → trả string rỗng."""
        assert _build_history_text(None) == ""
        assert _build_history_text([]) == ""

    def test_history_handles_unknown_role(self):
        """Role không xác định → fallback dùng [role] label."""
        history = [
            {"role": "system", "content": "System message"},
            {"role": "user", "content": "User message"},
        ]
        text = _build_history_text(history)
        assert "[system]" in text or "System message" in text
        assert "Người dùng" in text

    def test_history_skips_empty_content(self):
        """Message có content rỗng → bỏ qua."""
        history = [
            {"role": "user", "content": ""},
            {"role": "user", "content": "Câu hỏi thật"},
            {"role": "assistant", "content": "   "},
        ]
        text = _build_history_text(history)
        assert "Câu hỏi thật" in text
        assert text.count("Người dùng") == 1

    def test_history_caps_long_content(self):
        """History quá dài → cắt và thêm marker."""
        long_content = "x" * 3000
        history = [
            {"role": "user", "content": long_content},
            {"role": "assistant", "content": long_content},
        ]
        text = _build_history_text(history)
        assert len(text) < MAX_HISTORY_PAIRS * 2000 + 200  # Cho phép buffer nhỏ
        assert "[...lịch sử còn tiếp...]" in text


# ============================================================
# P1: SMART CONTEXT TRUNCATION
# ============================================================
class TestSmartTruncation:
    """Test cắt context theo evidence boundaries (không cắt giữa điều luật)."""

    def test_no_evidence_returns_empty(self):
        """Evidence rỗng → context rỗng + dropped_ids rỗng."""
        ctx, dropped = _build_context_from_evidence([], max_chars=1000)
        assert ctx == ""
        assert dropped == []

    def test_short_context_no_truncation(self):
        """Context ngắn → giữ nguyên, dropped_ids rỗng."""
        evidence = [
            {"evidence_id": "EV-001", "context_block": "Điều 1: Nội dung A"},
            {"evidence_id": "EV-002", "context_block": "Điều 2: Nội dung B"},
        ]
        ctx, dropped = _build_context_from_evidence(evidence, max_chars=1000)
        assert "Điều 1" in ctx
        assert "Điều 2" in ctx
        assert dropped == []

    def test_truncation_respects_evidence_boundary(self):
        """Khi vượt soft limit → evidence bị drop hoặc cắt tại boundary."""
        evidence = [
            {"evidence_id": "EV-001", "context_block": "x" * 5000},  # ~5000 chars
            {"evidence_id": "EV-002", "context_block": "x" * 5000},  # ~5000 chars
            {"evidence_id": "EV-003", "context_block": "x" * 5000},  # ~5000 chars
        ]
        ctx, dropped = _build_context_from_evidence(evidence, max_chars=SOFT_CONTEXT_LIMIT)
        # EV-001 vừa khít (~5000 < 6000), EV-002 vượt → drop
        assert "EV-001" not in dropped  # EV-001 được giữ
        # EV-002 hoặc EV-003 phải bị drop
        assert len(dropped) >= 1
        assert "EV-002" in dropped or "EV-003" in dropped

    def test_hard_limit_prevents_extreme_context(self):
        """Vượt HARD_CONTEXT_LIMIT → drop evidence để bảo vệ LLM."""
        evidence = [
            {"evidence_id": f"EV-{i:03d}", "context_block": "y" * 10000}
            for i in range(3)
        ]
        ctx, dropped = _build_context_from_evidence(evidence, max_chars=SOFT_CONTEXT_LIMIT)
        assert len(ctx) <= HARD_CONTEXT_LIMIT + 100  # Buffer cho separator

    def test_dropped_evidence_ids_tracked(self):
        """Dropped evidence IDs phải được track để B7 có thể report."""
        evidence = [
            {"evidence_id": "EV-001", "context_block": "short"},
            {"evidence_id": "EV-002", "context_block": "x" * 50000},  # Quá lớn
            {"evidence_id": "EV-003", "context_block": "x" * 50000},
        ]
        ctx, dropped = _build_context_from_evidence(evidence, max_chars=SOFT_CONTEXT_LIMIT)
        # EV-001 giữ, EV-002/003 phải drop do vượt hard limit
        assert "EV-001" not in dropped
        assert "EV-002" in dropped
        assert "EV-003" in dropped


# ============================================================
# P2: ERROR CLASSIFICATION
# ============================================================
class TestErrorClassification:
    """Test phân loại lỗi LLM chi tiết."""

    def test_rate_limit_returns_user_friendly_message(self):
        """Rate limit (429) → message bảo user đợi."""
        exc = Exception("Rate limit exceeded (429)")
        msg, level = _classify_llm_error(exc)
        assert "30 giây" in msg or "bận" in msg
        assert level == "warning"

    def test_timeout_returns_user_friendly_message(self):
        """Timeout → message bảo user thử lại."""
        exc = Exception("Request timed out")
        msg, level = _classify_llm_error(exc)
        assert "lâu" in msg or "thử lại" in msg
        assert level == "warning"

    def test_auth_error_returns_generic_error(self):
        """Auth error (401) → generic error message, log error."""
        exc = Exception("Unauthorized: invalid api key")
        msg, level = _classify_llm_error(exc)
        assert msg == LLM_ERROR_MSG
        assert level == "error"

    def test_model_not_found_returns_generic_error(self):
        """Model not found (404) → generic error, log error."""
        exc = Exception("Model 'foo' not found (404)")
        msg, level = _classify_llm_error(exc)
        assert msg == LLM_ERROR_MSG
        assert level == "error"

    def test_unknown_exception_returns_generic_error(self):
        """Exception không rõ loại → generic error."""
        exc = Exception("Some random error XYZABC")
        msg, level = _classify_llm_error(exc)
        assert msg == LLM_ERROR_MSG
        assert level == "error"


class TestLLMErrorHandling:
    """Test LLM exception được handle đúng cách trong step_generate_answer."""

    def test_llm_exception_returns_user_message(self, mock_llm_factory):
        """LLM throw exception → trả message phù hợp, không crash."""
        llm = MagicMock()
        llm.invoke.side_effect = Exception("Rate limit (429)")
        answer = step_generate_answer(llm, "Test", "Context")
        assert "30 giây" in answer or "bận" in answer

    def test_llm_returns_empty_content(self, mock_llm_factory):
        """LLM trả content rỗng → NO_CONTEXT_MSG."""
        llm = MagicMock()
        resp = MagicMock()
        resp.content = ""
        llm.invoke.return_value = resp
        answer = step_generate_answer(llm, "Test", "Context")
        assert answer == NO_CONTEXT_MSG

    def test_llm_returns_whitespace_content(self, mock_llm_factory):
        """LLM trả content chỉ whitespace → NO_CONTEXT_MSG."""
        llm = MagicMock()
        resp = MagicMock()
        resp.content = "   \n  "
        llm.invoke.return_value = resp
        answer = step_generate_answer(llm, "Test", "Context")
        assert answer == NO_CONTEXT_MSG


# ============================================================
# P3: LEGALCONTEXT INTEGRATION
# ============================================================
class TestLegalContextIntegration:
    """Test B6 nhận LegalContext từ B5 và dùng nó để truncate thông minh."""

    @staticmethod
    def _build_legal_context(evidence_items):
        """Helper: build LegalContext object từ list EvidenceItem."""
        from app.rag.schemas.legal_context import LegalContext, RequestInfo
        return LegalContext(
            request=RequestInfo(
                original_query="test",
                normalized_query="test",
                retrieval_query="test",
            ),
            evidence=evidence_items,
        )

    def test_with_legal_context_uses_evidence_boundaries(self, mock_llm_factory, sample_evidence):
        """Khi có legal_context → context build từ evidence (không dùng context_text)."""
        from langchain_core.messages import HumanMessage
        from app.rag.schemas.legal_context import EvidenceItem
        items = [
            EvidenceItem(evidence_id=ev["evidence_id"], context_block=ev["context_block"])
            for ev in sample_evidence
        ]
        lc = self._build_legal_context(items)

        llm = mock_llm_factory("Câu trả lời mới")
        # Truyền legal_context → context_text sẽ bị ignore
        answer = step_generate_answer(
            llm,
            "Test?",
            "CONTEXT_TEXT_SHOULD_BE_IGNORED",  # Nếu bị ignore thì không xuất hiện trong prompt
            legal_context=lc,
        )
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        human_msg = next(m for m in messages if isinstance(m, HumanMessage))
        # Placeholder KHÔNG được xuất hiện trong HumanMessage
        assert "CONTEXT_TEXT_SHOULD_BE_IGNORED" not in human_msg.content
        # Evidence phải xuất hiện
        assert "Nghị định 168" in human_msg.content

    def test_without_legal_context_uses_context_text(self, mock_llm_factory):
        """Không có legal_context → dùng context_text như cũ."""
        llm = mock_llm_factory("OK")
        step_generate_answer(
            llm,
            "Test?",
            "CONTEXT_FROM_TEXT",
            legal_context=None,
        )
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        # Tìm HumanMessage (có chứa câu hỏi), không phải SystemMessage
        human_msg = next(
            m for m in messages
            if hasattr(m, "content") and "Test?" in str(m.content)
        )
        assert "CONTEXT_FROM_TEXT" in human_msg.content

    def test_legal_context_with_empty_evidence_falls_back(self, mock_llm_factory):
        """legal_context có evidence rỗng → fallback dùng context_text."""
        lc = self._build_legal_context([])  # evidence rỗng

        llm = mock_llm_factory("OK")
        step_generate_answer(
            llm,
            "Test?",
            "CONTEXT_FALLBACK",
            legal_context=lc,
        )
        # Vì evidence rỗng → vẫn dùng context_text
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        human_msg = next(
            m for m in messages
            if hasattr(m, "content") and "Test?" in str(m.content)
        )
        assert "CONTEXT_FALLBACK" in human_msg.content


# ============================================================
# HARD LIMIT FALLBACK
# ============================================================
class TestHardLimitFallback:
    """Test fallback char-based truncation khi không có LegalContext."""

    def test_context_exceeds_hard_limit_truncated(self, mock_llm_factory):
        """Context > HARD_CONTEXT_LIMIT → cắt theo char."""
        long_context = "x" * (HARD_CONTEXT_LIMIT + 5000)
        llm = mock_llm_factory("OK")
        step_generate_answer(llm, "Test?", long_context)
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        human_msg = next(
            m for m in messages
            if hasattr(m, "content") and "Test?" in str(m.content)
        )
        # Prompt không được chứa full long_context
        assert len(human_msg.content) < len(long_context) + 500

    def test_context_within_hard_limit_intact(self, mock_llm_factory):
        """Context < HARD_CONTEXT_LIMIT → giữ nguyên."""
        medium_context = "Context vừa phải " * 100  # ~1700 chars
        llm = mock_llm_factory("OK")
        step_generate_answer(llm, "Test?", medium_context)
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        human_msg = next(
            m for m in messages
            if hasattr(m, "content") and "Test?" in str(m.content)
        )
        assert "Context vừa phải" in human_msg.content


# ============================================================
# PROMPT STRUCTURE
# ============================================================
class TestPromptStructure:
    """Test cấu trúc prompt đúng format."""

    def test_system_message_uses_prompt_constant(self, mock_llm_factory):
        """System message dùng SYSTEM_ANSWER_GENERATION."""
        from app.rag.prompts.generator import SYSTEM_ANSWER_GENERATION
        llm = mock_llm_factory("OK")
        step_generate_answer(llm, "Test?", "Context")
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        sys_msg = next(m for m in messages if "trợ lý" in str(m.content).lower())
        assert sys_msg.content == SYSTEM_ANSWER_GENERATION

    def test_user_prompt_contains_question(self, mock_llm_factory):
        """User prompt phải chứa câu hỏi."""
        llm = mock_llm_factory("OK")
        step_generate_answer(llm, "Câu hỏi đặc biệt ABC123", "Context")
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        human_msg = next(m for m in messages if "ABC123" in str(m.content))
        assert "ABC123" in human_msg.content

    def test_user_prompt_contains_context(self, mock_llm_factory):
        """User prompt phải chứa context."""
        llm = mock_llm_factory("OK")
        step_generate_answer(llm, "Test?", "CONTEXT_UNIQUE_MARKER_XYZ")
        call_args = llm.invoke.call_args
        messages = call_args[0][0]
        human_msg = next(m for m in messages if "CONTEXT_UNIQUE_MARKER_XYZ" in str(m.content))
        assert "CONTEXT_UNIQUE_MARKER_XYZ" in human_msg.content


# ============================================================
# EDGE CASES
# ============================================================
class TestEdgeCases:
    """Test các trường hợp biên."""

    def test_unicode_question(self, mock_llm_factory):
        """Câu hỏi có ký tự unicode/emoji."""
        llm = mock_llm_factory("OK")
        answer = step_generate_answer(llm, "Phạt bao nhiêu khi 🚗 vượt đèn đỏ?", "Context")
        assert answer  # Chỉ cần không crash

    def test_very_long_question(self, mock_llm_factory):
        """Câu hỏi rất dài."""
        llm = mock_llm_factory("OK")
        long_q = "Phạt bao nhiêu " * 100
        answer = step_generate_answer(llm, long_q, "Context")
        assert answer

    def test_history_with_odd_count(self, mock_llm_factory):
        """History có số lẻ message (không phải cặp)."""
        history = [
            {"role": "user", "content": "Câu 1"},
            {"role": "assistant", "content": "Trả lời 1"},
            {"role": "user", "content": "Câu 2"},  # Không có reply
        ]
        text = _build_history_text(history)
        assert "Câu 1" in text
        assert "Câu 2" in text
        assert "Trả lời 1" in text

    def test_malformed_history_messages(self, mock_llm_factory):
        """History message thiếu field role/content."""
        history = [
            {},  # rỗng
            {"role": "user"},  # thiếu content
            {"content": "orphan message"},  # thiếu role
            {"role": "user", "content": "valid"},
        ]
        # Không crash
        text = _build_history_text(history)
        assert "valid" in text
