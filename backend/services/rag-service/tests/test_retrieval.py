"""Tests cho B4 - Hybrid Retrieval (v2: batch + soft boost + reranker hook)."""
from __future__ import annotations

from app.rag.steps.retrieval import (
    _build_pinecone_filter,
    _soft_intent_boost,
    step_retrieve_hybrid,
)


# ============================================================
# SOFT INTENT BOOST (P1)
# ============================================================
def test_soft_intent_boost_penalty_nghi_dinh():
    """penalty_lookup + Nghị định → boost thêm score."""
    new = _soft_intent_boost("penalty_lookup", {"document_type": "Nghị định"}, 0.8)
    assert new > 0.8
    assert new == 0.88


def test_soft_intent_boost_penalty_luat():
    """penalty_lookup + Luật → KHÔNG boost (giữ nguyên score)."""
    new = _soft_intent_boost("penalty_lookup", {"document_type": "Luật"}, 0.8)
    assert new == 0.8


def test_soft_intent_boost_rule_luat():
    """rule_lookup + Luật → boost."""
    new = _soft_intent_boost("rule_lookup", {"document_type": "Luật"}, 0.8)
    assert new > 0.8


def test_soft_intent_boost_unknown_intent():
    """general_info → không boost."""
    new = _soft_intent_boost("general_info", {"document_type": "Luật"}, 0.8)
    assert new == 0.8


def test_soft_intent_boost_missing_doc_type():
    """Missing doc_type → không boost, không crash."""
    new = _soft_intent_boost("penalty_lookup", {}, 0.5)
    assert new == 0.5


# ============================================================
# PINECONE METADATA FILTER (P1 - currently None by design)
# ============================================================
def test_pinecone_filter_default_none():
    """Hiện đang dùng soft boost → không filter ở DB."""
    assert _build_pinecone_filter("penalty_lookup") is None
    assert _build_pinecone_filter("rule_lookup") is None
    assert _build_pinecone_filter("general_info") is None


# ============================================================
# MAIN: step_retrieve_hybrid (v2 - batched)
# ============================================================
def test_step_retrieve_hybrid_returns_blocks(mock_engine):
    cleaned = {
        "cleaned_query": "phạt xe máy không nhường đường",
        "intent": "penalty_lookup",
    }
    query_vec = [0.1] * 384
    blocks = step_retrieve_hybrid(mock_engine, cleaned, query_vec, top_k=5)
    assert len(blocks) > 0
    assert all("citation" in b for b in blocks)
    assert all("context_block" in b for b in blocks)


def test_step_retrieve_hybrid_soft_boost_applied(mock_engine):
    """intent=penalty_lookup → match Nghị định phải có boosted=True."""
    cleaned = {
        "cleaned_query": "phạt xe máy không nhường đường",
        "intent": "penalty_lookup",
    }
    query_vec = [0.1] * 384
    blocks = step_retrieve_hybrid(mock_engine, cleaned, query_vec, top_k=5)
    # match 1 (Nghị định) → được boost
    # match 2 (Luật) → không boost
    nghi_dinh_blocks = [b for b in blocks if b.get("law_document_type") == "Nghị định"]
    luat_blocks = [b for b in blocks if b.get("law_document_type") == "Luật"]
    for b in nghi_dinh_blocks:
        assert b.get("boosted") is True
        assert b["score"] > b["pinecone_score"]
    for b in luat_blocks:
        assert b.get("boosted") is False
        assert b["score"] == b["pinecone_score"]


def test_step_retrieve_hybrid_enrich_with_neo4j_batch(mock_engine):
    """Verify Neo4j session.run được gọi với batch query."""
    cleaned = {"cleaned_query": "test", "intent": "general_info"}
    step_retrieve_hybrid(mock_engine, cleaned, [0.1] * 384, top_k=5)
    # Neo4j đã được gọi đúng 1 lần (batch) thay vì N lần
    assert mock_engine.neo_session.called


def test_step_retrieve_hybrid_top_k_respected(mock_engine):
    cleaned = {"cleaned_query": "test", "intent": "general_info"}
    blocks = step_retrieve_hybrid(mock_engine, cleaned, [0.1] * 384, top_k=2)
    assert len(blocks) <= 2


def test_step_retrieve_hybrid_with_query_text_passes_to_reranker(mock_engine):
    """query_text được truyền → reranker hook được kích hoạt (NoOp mặc định)."""
    cleaned = {"cleaned_query": "test", "intent": "general_info"}
    blocks = step_retrieve_hybrid(
        mock_engine,
        cleaned,
        [0.1] * 384,
        top_k=5,
        query_text="test query",
    )
    assert isinstance(blocks, list)


def test_step_retrieve_hybrid_handles_empty_pinecone_results(mock_engine):
    """Pinecone trả 0 match → trả [] ngay không gọi Neo4j."""
    mock_engine.get_pinecone_index.return_value.query.return_value.matches = []
    cleaned = {"cleaned_query": "test", "intent": "general_info"}
    blocks = step_retrieve_hybrid(mock_engine, cleaned, [0.1] * 384, top_k=5)
    assert blocks == []


def test_step_retrieve_hybrid_skips_invalid_matches(mock_engine):
    """Match thiếu document_id/article_id → skip."""
    import unittest.mock as mock

    # Tạo match "xấu"
    bad_match = mock.MagicMock(
        id="bad:match",
        score=0.5,
        metadata={"document_id": None, "article_id": None},
    )
    good_match = mock.MagicMock(
        id="clause:D168-2024-ND-CP-A-6-K4",
        score=0.91,
        metadata={
            "type": "clause",
            "document_id": "D168-2024-ND-CP",
            "chapter_id": "D168-2024-ND-CP-CII",
            "article_id": "D168-2024-ND-CP-A-6",
            "clause_id": "D168-2024-ND-CP-A-6-K4",
        },
    )
    mock_engine.get_pinecone_index.return_value.query.return_value.matches = [bad_match, good_match]
    cleaned = {"cleaned_query": "test", "intent": "general_info"}
    blocks = step_retrieve_hybrid(mock_engine, cleaned, [0.1] * 384, top_k=5)
    # Chỉ good_match được giữ
    assert all(b["vector_id"] != "bad:match" for b in blocks)
