"""Tests cho full 7-step pipeline orchestrator."""
from __future__ import annotations

from rag.orchestrator import run_pipeline


def test_run_pipeline_full(mock_engine):
    """End-to-end: câu hỏi → answer + verification."""
    response = run_pipeline(
        engine=mock_engine,
        question="Phạt bao nhiêu khi đi xe máy không nhường đường?",
        top_k=5,
        verify=True,
    )
    assert response.answer
    assert "Điều 6" in response.answer or "phạt" in response.answer.lower()
    assert len(response.sources) >= 1
    assert response.verification is not None
    assert response.verification.has_citation is True
    assert response.debug["cleaned_query"]
    assert response.debug["intent"] == "penalty_lookup"


def test_run_pipeline_verify_disabled(mock_engine):
    response = run_pipeline(
        engine=mock_engine,
        question="test",
        top_k=5,
        verify=False,
    )
    # Verification disabled → WARN + flag
    assert response.verification.status.value == "warn"
    assert "verification_disabled" in response.verification.issues


def test_run_pipeline_top_k_respected(mock_engine):
    response = run_pipeline(
        engine=mock_engine,
        question="test",
        top_k=1,
    )
    assert len(response.sources) <= 1


def test_run_pipeline_engine_not_initialized(mock_llm):
    """Engine chưa init → raise."""
    from rag.engine import RagEngine
    import pytest

    engine = RagEngine()
    engine._neo_client = None  # chưa init
    # Mock llm is None
    engine.llm = None
    engine.verifier_llm = None

    with pytest.raises(RuntimeError):
        run_pipeline(engine, "test")
