"""Tests cho B6 - LLM Generation."""
from __future__ import annotations

from rag.steps.generator import NO_CONTEXT_MSG, step_generate_answer


def test_generate_answer_with_context(mock_llm):
    answer = step_generate_answer(
        mock_llm,
        "Phạt bao nhiêu?",
        "Điều 6 Khoản 4: phạt 4-6 triệu",
    )
    assert "Nghị định 168" in answer
    assert "Điều 6" in answer


def test_generate_answer_no_context_returns_fallback(mock_llm):
    answer = step_generate_answer(mock_llm, "Phạt bao nhiêu?", "")
    assert answer == NO_CONTEXT_MSG


def test_generate_answer_empty_context_whitespace(mock_llm):
    answer = step_generate_answer(mock_llm, "test?", "   \n  ")
    assert answer == NO_CONTEXT_MSG


def test_generate_answer_no_llm_raises():
    import pytest
    with pytest.raises(RuntimeError):
        step_generate_answer(None, "test", "ctx")
