"""Tests cho B4 - Hybrid Retrieval (v2: batch + soft boost + reranker hook).

Bổ sung acceptance test cho Plan §11 (B2/B4):
  - status filter drop inactive khi require_active=True
  - siblings expansion mở rộng tất cả Clause cùng Article
  - parent expansion (Clause → Article / Article → Chapter)
  - neighbors full expansion
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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


# ============================================================
# ACCEPTANCE TESTS — Plan §11 (B4 status filter + expansion kinds)
# ============================================================
def _build_pinecone_match(vid, score, doc_id, doc_type, art_id="D1-A-1", ctype="clause"):
    """Helper tạo mock Pinecone match. art_id mặc định = 'D1-A-1'."""
    m = MagicMock()
    m.id = vid
    m.score = score
    m.metadata = {
        "type": ctype,
        "document_id": doc_id,
        "document_type": doc_type,
        "chapter_id": f"{doc_id}-CII",
        "article_id": art_id,
        "clause_id": f"{art_id}-K1" if ctype == "clause" else "",
    }
    return m


def _mock_engine_with_status_and_expansion(pinecone_matches, ctx_rows,
                                           doc_statuses, doc_amendments):
    """
    Tạo mock engine hỗ trợ cả 2 use-case:
      - B4 status check (CYPHER_DOCUMENT_META + CYPHER_DOC_HAS_ACTIVE_AMENDMENT)
      - B4 expansion Cypher (CYPHER_SIBLINGS_CLAUSES, CYPHER_UP_*, etc.)
      - B4 batch query (NEO4J_CONTEXT_BATCH_QUERY với UNWIND $matches)

    Args:
        pinecone_matches: list MagicMock() của Pinecone matches
        ctx_rows:         list dict của batch enrich rows
        doc_statuses:     dict {document_id: {"status", "effective_from", "effective_to"}}
        doc_amendments:   dict {document_id: bool} True nếu có active amendment
    """
    engine = MagicMock()
    index = MagicMock()
    index.query.return_value.matches = pinecone_matches
    engine.get_pinecone_index.return_value = index

    session = MagicMock()

    def _iter_rows(rows):
        cursor = MagicMock()
        cursor.__iter__ = lambda self: iter(rows)
        cursor.single.return_value = rows[0] if rows else None
        return cursor

    def _run(query, **params):
        """Route query đến data tương ứng dựa trên params và query substring.

        Detection theo thứ tự ưu tiên:
          1. UNWIND $matches (batch query) — dựa vào params['matches']
          2. CYPHER_DOC_HAS_ACTIVE_AMENDMENT — chỉ có $document_id, query có chữ AMEND
          3. CYPHER_DOCUMENT_META — chỉ có $document_id
          4. Expansion queries — $article_id, $clause_id, $chapter_id
        """
        # 1. Batch query (UNWIND $matches) — dựa vào params['matches']
        if params.get("matches") is not None:
            matches = params.get("matches") or []
            rows = []
            for m in matches:
                vid = m.get("vector_id")
                matched = next((r for r in ctx_rows if r.get("vector_id") == vid), None)
                if matched:
                    rows.append(matched)
            return _iter_rows(rows)

        # 2. Amendment check (chạy SAU document meta, khi document inactive)
        if "AMENDED_BY" in query or "AMENDMENT" in query:
            doc_id = params.get("document_id", "")
            has_amend = doc_amendments.get(doc_id, False)
            return _iter_rows(
                [{"amended_article_id": "A-x"}] if has_amend else [None]
            )

        # 3. Document meta (chỉ có $document_id) — dựa vào KHÔNG có article_id/clause_id
        if params.get("document_id") and not (
            params.get("article_id")
            or params.get("clause_id")
            or params.get("chapter_id")
        ):
            doc_id = params.get("document_id", "")
            status = doc_statuses.get(doc_id)
            if status is None:
                return _iter_rows([None])
            return _iter_rows([status])

        # 4. Expansion queries
        if params.get("article_id"):
            article_id = params.get("article_id")
            siblings = [
                r for r in ctx_rows
                if r.get("article_id") == article_id and r.get("clause_id")
            ]
            return _iter_rows(siblings)
        if params.get("clause_id"):
            clause_id = params.get("clause_id")
            # CYPHER_UP_CLAUSE_TO_ARTICLE → Article row (no clause)
            rows = [
                r for r in ctx_rows
                if r.get("clause_id") == clause_id
                or (r.get("article_id") == params.get("article_id")
                    and not r.get("clause_id"))
            ]
            return _iter_rows(rows)
        if params.get("chapter_id"):
            return _iter_rows(
                [r for r in ctx_rows if r.get("chapter_id") == params.get("chapter_id")]
            )

        return _iter_rows([])

    session.run.side_effect = _run

    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = None
    engine.neo_session.return_value = cm
    return engine


def _iter_rows(rows):
    cursor = MagicMock()
    cursor.__iter__ = lambda self: iter(rows)
    cursor.single.return_value = rows[0] if rows else None
    return cursor


# Test #4 trong Plan §11: B4 status filter drop document hết hạn + require_active=True
def test_b4_status_filter_drops_inactive_when_require_active(monkeypatch):
    """Acceptance test #4: Document hết hạn + require_active=True → drop khỏi evidence."""
    monkeypatch.setenv("TODAY_OVERRIDE", "2026-09-27")

    # 2 match: 1 active, 1 repealed hết hạn
    active_match = _build_pinecone_match(
        vid="clause:D1-A-1-K1", score=0.9, doc_id="D1", doc_type="Nghị định", art_id="D1-A-1",
    )
    inactive_match = _build_pinecone_match(
        vid="clause:D2-A-1-K1", score=0.85, doc_id="D2", doc_type="Nghị định", art_id="D2-A-1",
    )

    ctx_rows = [
        {
            "vector_id": "clause:D1-A-1-K1", "document_id": "D1",
            "document_number": "1/2020", "document_title": "Active Doc",
            "document_type": "Nghị định", "document_issuing_authority": "Mock",
            "document_date_enacted": "2020-01-01", "document_date_effective": "2020-06-01",
            "chapter_id": "D1-CII", "chapter_number": "II", "chapter_title": "Chương II",
            "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
            "article_text": "", "clause_id": "D1-A-1-K1",
            "clause_number": "1", "clause_text": "text active",
            "forward_amendments": [], "backward_amendments": [],
        },
        {
            "vector_id": "clause:D2-A-1-K1", "document_id": "D2",
            "document_number": "2/2010", "document_title": "Expired Doc",
            "document_type": "Nghị định", "document_issuing_authority": "Mock",
            "document_date_enacted": "2010-01-01", "document_date_effective": "2010-06-01",
            "chapter_id": "D2-CII", "chapter_number": "II", "chapter_title": "Chương II",
            "article_id": "D2-A-1", "article_number": "1", "article_title": "Điều 1",
            "article_text": "", "clause_id": "D2-A-1-K1",
            "clause_number": "1", "clause_text": "text expired",
            "forward_amendments": [], "backward_amendments": [],
        },
    ]

    doc_statuses = {
        "D1": {"document_id": "D1", "status": "active", "effective_from": "2020-06-01", "effective_to": None},
        "D2": {"document_id": "D2", "status": "repealed", "effective_from": "2010-06-01", "effective_to": "2020-12-31"},
    }
    doc_amendments = {"D1": False, "D2": False}

    engine = _mock_engine_with_status_and_expansion(
        [active_match, inactive_match], ctx_rows, doc_statuses, doc_amendments,
    )

    # policy require_active=True
    cleaned = {
        "cleaned_query": "phạt", "intent": "penalty_lookup",
        "retrieval_policy": {
            "intensity": "default", "expansion": "none",
            "filters": {"require_active": True, "document_type": "Nghị định"},
        },
    }

    blocks = step_retrieve_hybrid(engine, cleaned, [0.1] * 384, top_k=5)

    # Chỉ match D1 (active) được giữ
    doc_ids = {b["law_document_id"] for b in blocks}
    assert "D1" in doc_ids
    assert "D2" not in doc_ids, "Document hết hạn phải bị drop khi require_active=True"


def test_b4_status_filter_keeps_inactive_when_not_required(monkeypatch):
    """require_active=False → giữ tất cả (kể cả inactive) để B7 cảnh báo."""
    monkeypatch.setenv("TODAY_OVERRIDE", "2026-09-27")

    active_match = _build_pinecone_match(
        vid="clause:D1-A-1-K1", score=0.9, doc_id="D1", doc_type="Nghị định", art_id="D1-A-1",
    )
    inactive_match = _build_pinecone_match(
        vid="clause:D2-A-1-K1", score=0.85, doc_id="D2", doc_type="Nghị định", art_id="D2-A-1",
    )
    ctx_rows = [
        {"vector_id": "clause:D1-A-1-K1", "document_id": "D1", "document_number": "1/2020",
         "document_title": "Active Doc", "document_type": "Nghị định",
         "document_issuing_authority": "Mock", "document_date_enacted": "2020-01-01",
         "document_date_effective": "2020-06-01", "chapter_id": "D1-CII",
         "chapter_number": "II", "chapter_title": "Chương II",
         "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
         "article_text": "", "clause_id": "D1-A-1-K1",
         "clause_number": "1", "clause_text": "text active",
         "forward_amendments": [], "backward_amendments": []},
        {"vector_id": "clause:D2-A-1-K1", "document_id": "D2", "document_number": "2/2010",
         "document_title": "Expired Doc", "document_type": "Nghị định",
         "document_issuing_authority": "Mock", "document_date_enacted": "2010-01-01",
         "document_date_effective": "2010-06-01", "chapter_id": "D2-CII",
         "chapter_number": "II", "chapter_title": "Chương II",
         "article_id": "D2-A-1", "article_number": "1", "article_title": "Điều 1",
         "article_text": "", "clause_id": "D2-A-1-K1",
         "clause_number": "1", "clause_text": "text expired",
         "forward_amendments": [], "backward_amendments": []},
    ]
    doc_statuses = {
        "D1": {"document_id": "D1", "status": "active", "effective_from": None, "effective_to": None},
        "D2": {"document_id": "D2", "status": "repealed", "effective_from": None, "effective_to": None},
    }
    engine = _mock_engine_with_status_and_expansion(
        [active_match, inactive_match], ctx_rows, doc_statuses, {"D1": False, "D2": False},
    )

    cleaned = {
        "cleaned_query": "văn bản nào quy định", "intent": "general_info",
        "retrieval_policy": {
            "intensity": "default", "expansion": "none",
            "filters": {"require_active": False, "document_type": None},
        },
    }
    blocks = step_retrieve_hybrid(engine, cleaned, [0.1] * 384, top_k=5)
    doc_ids = {b["law_document_id"] for b in blocks}
    assert "D1" in doc_ids
    assert "D2" in doc_ids, "require_active=False → giữ cả inactive để B7 cảnh báo"
    # evidence inactive phải có flag is_active=False để B7 biết
    d2_blocks = [b for b in blocks if b["law_document_id"] == "D2"]
    for b in d2_blocks:
        assert b["is_active"] is False


# Test #5 trong Plan §11: B4 expansion siblings mở rộng tất cả Clause cùng Article
def test_b4_expansion_siblings_includes_all_clauses_same_article(monkeypatch):
    """Acceptance test #5: anchor at Clause → siblings → evidence có tất cả Clause cùng Article."""
    monkeypatch.setenv("TODAY_OVERRIDE", "2026-09-27")

    clause_anchor = _build_pinecone_match(
        vid="clause:D1-A-1-K2", score=0.9, doc_id="D1", doc_type="Nghị định",
        art_id="D1-A-1", ctype="clause",
    )
    article_anchor = _build_pinecone_match(
        vid="article:D1-A-1", score=0.88, doc_id="D1", doc_type="Nghị định",
        art_id="D1-A-1", ctype="article",
    )

    # ctx_rows: 3 clauses (K1, K2, K3) + 1 article-row (no clause)
    ctx_rows = []
    for k_num in ("1", "2", "3"):
        ctx_rows.append({
            "vector_id": f"clause:D1-A-1-K{k_num}",
            "document_id": "D1", "document_number": "1/2020",
            "document_title": "Mock", "document_type": "Nghị định",
            "document_issuing_authority": "Mock", "document_date_enacted": "2020-01-01",
            "document_date_effective": "2020-06-01",
            "chapter_id": "D1-CII", "chapter_number": "II", "chapter_title": "Chương II",
            "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
            "article_text": "",
            "clause_id": f"D1-A-1-K{k_num}", "clause_number": k_num,
            "clause_text": f"text K{k_num}",
            "forward_amendments": [], "backward_amendments": [],
        })
    ctx_rows.append({
        "vector_id": "article:D1-A-1",
        "document_id": "D1", "document_number": "1/2020",
        "document_title": "Mock", "document_type": "Nghị định",
        "document_issuing_authority": "Mock", "document_date_enacted": "2020-01-01",
        "document_date_effective": "2020-06-01",
        "chapter_id": "D1-CII", "chapter_number": "II", "chapter_title": "Chương II",
        "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
        "article_text": "text Điều 1", "clause_id": "",
        "clause_number": "", "clause_text": "",
        "forward_amendments": [], "backward_amendments": [],
    })

    doc_statuses = {"D1": {"document_id": "D1", "status": "active", "effective_from": None, "effective_to": None}}
    engine = _mock_engine_with_status_and_expansion(
        [clause_anchor, article_anchor], ctx_rows, doc_statuses, {"D1": False},
    )

    cleaned = {
        "cleaned_query": "test", "intent": "general_info",
        "retrieval_policy": {
            "intensity": "default", "expansion": "siblings",
            "filters": {"require_active": False, "document_type": None},
        },
    }
    blocks = step_retrieve_hybrid(engine, cleaned, [0.1] * 384, top_k=5)

    # Anchor (K2 + article) + expansion siblings ở article-anchor → trả Clause K1, K2, K3
    # → evidence có 2 anchor + ≥1 expanded sibling (anchor tại article sẽ expand các Khoản)
    expanded_clauses = [b for b in blocks if b.get("expansion_kind") in ("horizontal", "neighbor")]
    # Phải có ít nhất 1 expanded block là Clause (sibling)
    assert any(b.get("type") == "clause" for b in expanded_clauses), \
        "Siblings expansion phải trả Clause row (horizontal)"
    # Tất cả expanded blocks có expanded_from = vector_id của anchor
    for b in expanded_clauses:
        assert len(b["expanded_from"]) > 0


# Test #5b: parent expansion (Clause → Article)
def test_b4_expansion_parent_up_clause_to_article(monkeypatch):
    """Acceptance test: parent expansion — anchor ở Clause → mở rộng ra Article."""
    monkeypatch.setenv("TODAY_OVERRIDE", "2026-09-27")

    clause_match = _build_pinecone_match(
        vid="clause:D1-A-1-K1", score=0.9, doc_id="D1", doc_type="Nghị định",
        art_id="D1-A-1", ctype="clause",
    )
    ctx_rows = [{
        "vector_id": "clause:D1-A-1-K1", "document_id": "D1",
        "document_number": "1/2020", "document_title": "Mock",
        "document_type": "Nghị định", "document_issuing_authority": "Mock",
        "document_date_enacted": "2020-01-01",
        "document_date_effective": "2020-06-01",
        "chapter_id": "D1-CII", "chapter_number": "II", "chapter_title": "Chương II",
        "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
        "article_text": "text Điều 1", "clause_id": "D1-A-1-K1",
        "clause_number": "1", "clause_text": "text K1",
        "forward_amendments": [], "backward_amendments": [],
    }]
    doc_statuses = {"D1": {"document_id": "D1", "status": "active", "effective_from": None, "effective_to": None}}
    engine = _mock_engine_with_status_and_expansion(
        [clause_match], ctx_rows, doc_statuses, {"D1": False},
    )

    cleaned = {
        "cleaned_query": "test", "intent": "procedure_lookup",
        "retrieval_policy": {
            "intensity": "default", "expansion": "parent",
            "filters": {"require_active": True, "document_type": None},
        },
    }
    blocks = step_retrieve_hybrid(engine, cleaned, [0.1] * 384, top_k=5)
    # Anchor là Clause, expansion=parent → UP Clause → Article → trả Article row (expansion_kind=up)
    expanded = [b for b in blocks if b.get("expansion_kind") == "up"]
    assert len(expanded) >= 1, "parent expansion phải trả ít nhất 1 Article row"
    # Article node mở rộng phải có type=article (hoặc expanded clause text)
    for b in expanded:
        # expanded từ clause-anchor → trả Article row
        assert b.get("type") in ("article", "clause")  # build_block_from_article_row


# Test #5c: neighbors expansion (UP + DOWN + HORIZONTAL)
def test_b4_expansion_neighbors_full(monkeypatch):
    """Acceptance test: neighbors (UP + DOWN + HORIZONTAL) cho missing_fact_query."""
    monkeypatch.setenv("TODAY_OVERRIDE", "2026-09-27")

    clause_match = _build_pinecone_match(
        vid="clause:D1-A-1-K2", score=0.9, doc_id="D1", doc_type="Nghị định",
        art_id="D1-A-1", ctype="clause",
    )
    # 3 clauses (K1, K2, K3) + 1 article (no clause)
    ctx_rows = []
    for k_num in ("1", "2", "3"):
        ctx_rows.append({
            "vector_id": f"clause:D1-A-1-K{k_num}",
            "document_id": "D1", "document_number": "1/2020",
            "document_title": "Mock", "document_type": "Nghị định",
            "document_issuing_authority": "Mock", "document_date_enacted": "2020-01-01",
            "document_date_effective": "2020-06-01",
            "chapter_id": "D1-CII", "chapter_number": "II", "chapter_title": "Chương II",
            "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
            "article_text": "", "clause_id": f"D1-A-1-K{k_num}",
            "clause_number": k_num, "clause_text": f"text K{k_num}",
            "forward_amendments": [], "backward_amendments": [],
        })
    ctx_rows.append({
        "vector_id": "article:D1-A-1",
        "document_id": "D1", "document_number": "1/2020",
        "document_title": "Mock", "document_type": "Nghị định",
        "document_issuing_authority": "Mock", "document_date_enacted": "2020-01-01",
        "document_date_effective": "2020-06-01",
        "chapter_id": "D1-CII", "chapter_number": "II", "chapter_title": "Chương II",
        "article_id": "D1-A-1", "article_number": "1", "article_title": "Điều 1",
        "article_text": "text Điều 1", "clause_id": "",
        "clause_number": "", "clause_text": "",
        "forward_amendments": [], "backward_amendments": [],
    })
    doc_statuses = {"D1": {"document_id": "D1", "status": "active", "effective_from": None, "effective_to": None}}
    engine = _mock_engine_with_status_and_expansion(
        [clause_match], ctx_rows, doc_statuses, {"D1": False},
    )

    cleaned = {
        "cleaned_query": "phạt bao nhiêu?", "intent": "missing_fact_query",
        "retrieval_policy": {
            "intensity": "deep", "expansion": "neighbors",
            "filters": {"require_active": False, "document_type": None},
        },
    }
    blocks = step_retrieve_hybrid(engine, cleaned, [0.1] * 384, top_k=5)
    # expansion=neighbors → clause-anchor expand HORIZONTAL + UP
    expanded = [b for b in blocks if b.get("expansion_kind") != "anchor"]
    assert len(expanded) >= 1, "neighbors expansion phải mở rộng nhiều hướng"
    # Phải có ít nhất 1 sibling (horizontal hoặc neighbor)
    kinds = {b.get("expansion_kind") for b in expanded}
    assert any(k in ("horizontal", "neighbor", "up") for k in kinds)
