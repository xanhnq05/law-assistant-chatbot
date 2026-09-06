"""Tests cho B3 - Embedding."""
from __future__ import annotations

import pytest

from rag.steps.embedding import step_embed_batch, step_embed_cleaned_query, step_embed_question


def test_step_embed_question(mock_engine):
    vec = step_embed_question(mock_engine, "phạt xe máy")
    assert isinstance(vec, list)
    assert len(vec) == 384  # mock dim
    assert all(isinstance(v, float) for v in vec)


def test_step_embed_batch(mock_engine):
    vecs = step_embed_batch(mock_engine, ["a", "b"])
    assert len(vecs) == 1  # mock returns 1 vector for batch input
    assert isinstance(vecs[0], list)


def test_step_embed_cleaned_query_with_terms(mock_engine):
    cleaned = {
        "cleaned_query": "phạt xe máy không nhường đường",
        "key_legal_terms": ["phạt", "xe máy", "không nhường đường"],
    }
    vec = step_embed_cleaned_query(mock_engine, cleaned)
    assert isinstance(vec, list)
    # Verify embedder.encode was called with enriched text
    embedder = mock_engine.get_embedder()
    call_args = embedder.encode.call_args
    assert "Thuật ngữ" in call_args[0][0][0]


def test_step_embed_cleaned_query_no_terms(mock_engine):
    cleaned = {"cleaned_query": "phạt xe máy", "key_legal_terms": []}
    step_embed_cleaned_query(mock_engine, cleaned)
    embedder = mock_engine.get_embedder()
    call_args = embedder.encode.call_args
    assert "Thuật ngữ" not in call_args[0][0][0]


def test_embedder_not_initialized(mock_engine):
    mock_engine.get_embedder.return_value = None
    with pytest.raises(RuntimeError):
        step_embed_question(mock_engine, "test")
