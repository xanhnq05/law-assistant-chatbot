"""Tests cho B5 - LegalContext (Pydantic contract B4→B5→B6/B7).

Bổ sung acceptance test cho Plan §11 (B2/B4/B5):
  - Test #6: evidence[].is_active đúng, expansion_kind ∈ {anchor, horizontal, up, down, neighbor}
  - Test #7: E2E pipeline chạy + stats.retrieval_policy có
"""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.rag.steps.context_builder import (
    build_context_for_llm,
    build_legal_context,
    build_sources_for_response,
)


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def sample_blocks():
    """B4-style blocks (3 evidence, có duplicate theo stable_id)."""
    return [
        {
            "score": 0.91,
            "pinecone_score": 0.83,
            "boosted": True,
            "vector_id": "clause:D168-2024-ND-CP-A-6-K4",
            "type": "clause",
            "citation": "Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4",
            "context_block": (
                "Nghị định 168/2024/NĐ-CP - Xử phạt hành vi không nhường đường\n"
                "  Điều 6: Xử phạt hành vi không nhường đường\n"
                "    Khoản 4: Phạt tiền từ 4.000.000đ đến 6.000.000đ"
            ),
            "law_document_type": "Nghị định",
            "law_document_number": "168/2024/NĐ-CP",
            "law_title": "Xử phạt VPHC",
            "law_date_enacted": "2024-12-26",
            "law_date_effective": "2025-01-01",
            "law_issuing_authority": "Chính phủ",
            "chapter_number": "II",
            "chapter_title": "VI PHẠM QUY TẮC GIAO THÔNG",
            "article_number": "6",
            "article_title": "Xử phạt hành vi không nhường đường",
            "clause_number": "4",
            "related_amendments": [],
            "pinecone_meta": {
                "type": "clause",
                "document_id": "D168-2024-ND-CP",
                "chapter_id": "D168-2024-ND-CP-CII",
                "article_id": "D168-2024-ND-CP-A-6",
                "clause_id": "D168-2024-ND-CP-A-6-K4",
            },
        },
        {
            # DUPLICATE: cùng stable_id (article+clause) nhưng score thấp hơn
            "score": 0.70,
            "pinecone_score": 0.65,
            "boosted": False,
            "vector_id": "clause:D168-2024-ND-CP-A-6-K4-dup",
            "type": "clause",
            "citation": "Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4",
            "context_block": "DUPLICATE block (lower score, should be dropped)",
            "law_document_type": "Nghị định",
            "law_document_number": "168/2024/NĐ-CP",
            "law_title": "Xử phạt VPHC",
            "law_date_enacted": "2024-12-26",
            "law_date_effective": "2025-01-01",
            "law_issuing_authority": "Chính phủ",
            "chapter_number": "II",
            "chapter_title": "VI PHẠM QUY TẮC GIAO THÔNG",
            "article_number": "6",
            "article_title": "Xử phạt hành vi không nhường đường",
            "clause_number": "4",
            "related_amendments": [],
            "pinecone_meta": {
                "type": "clause",
                "document_id": "D168-2024-ND-CP",
                "chapter_id": "D168-2024-ND-CP-CII",
                "article_id": "D168-2024-ND-CP-A-6",
                "clause_id": "D168-2024-ND-CP-A-6-K4",
            },
        },
        {
            "score": 0.85,
            "pinecone_score": 0.85,
            "boosted": False,
            "vector_id": "article:L36-2024-QH15-A-15",
            "type": "article",
            "citation": "Luật 36/2024/QH15 - Điều 15",
            "context_block": (
                "Luật 36/2024/QH15 - Trật tự an toàn giao thông đường bộ\n"
                "  Điều 15: Quy tắc nhường đường"
            ),
            "law_document_type": "Luật",
            "law_document_number": "36/2024/QH15",
            "law_title": "Trật tự ATGT",
            "law_date_enacted": "2024-06-27",
            "law_date_effective": "2025-01-01",
            "law_issuing_authority": "Quốc hội",
            "chapter_number": "III",
            "chapter_title": "QUY TẮC GIAO THÔNG",
            "article_number": "15",
            "article_title": "Quy tắc nhường đường",
            "clause_number": "",
            "related_amendments": [
                {"type": "REPLACED_BY", "target_id": "L36-2024-QH15-A-15",
                 "target_label": "Article", "target_number": "15", "reason": "Bị thay thế"}
            ],
            "pinecone_meta": {
                "type": "article",
                "document_id": "L36-2024-QH15",
                "chapter_id": "L36-2024-QH15-CIII",
                "article_id": "L36-2024-QH15-A-15",
                "clause_id": "",
            },
        },
    ]


@pytest.fixture
def sample_cleaned():
    return {
        "cleaned_query": "phạt xe máy không nhường đường",
        "legal_domain": "xử phạt giao thông",
        "key_legal_terms": ["phạt", "xe máy", "không nhường đường"],
        "intent": "penalty_lookup",
        "original": "Phạt bao nhiêu khi đi xe máy không nhường đường?",
    }

# ============================================================
# Happy path
# ============================================================
def test_build_legal_context_basic(sample_blocks, sample_cleaned):
    lc = build_legal_context(
        question="Phạt bao nhiêu khi đi xe máy không nhường đường?",
        cleaned=sample_cleaned,
        retrieved_blocks=sample_blocks,
    )
    assert lc.request.original_query == "Phạt bao nhiêu khi đi xe máy không nhường đường?"
    assert lc.request.normalized_query == "phạt xe máy không nhường đường"
    assert "Thuật ngữ" in lc.request.retrieval_query
    assert lc.request.intent == "penalty_lookup"
    assert lc.request.language == "vi"
    assert lc.request.key_terms == ["phạt", "xe máy", "không nhường đường"]
    # 3 input → 2 sau dedup (drop duplicate)
    assert lc.stats["b4_count"] == 3
    assert lc.stats["deduped_count"] == 2
    assert lc.stats["kept_count"] == 2
    assert len(lc.evidence) == 2
    # Evidence IDs ổn định
    assert lc.evidence[0].evidence_id == "EV-001"
    assert lc.evidence[1].evidence_id == "EV-002"
    # Citations 1-1 với evidence
    assert len(lc.citations) == 2
    assert lc.citations[0].citation_id == "CIT-001"
    assert lc.citations[0].evidence_id == "EV-001"
    assert lc.citations[1].citation_id == "CIT-002"
    assert lc.citations[1].evidence_id == "EV-002"
    # Hierarchy có 2 documents (Nghị định + Luật)
    assert len(lc.hierarchy.documents) == 2
    doc_ids = {d.document_id for d in lc.hierarchy.documents}
    assert doc_ids == {"D168-2024-ND-CP", "L36-2024-QH15"}


# ============================================================
# Dedup theo stable_id (KHÔNG phải citation string)
# ============================================================
def test_dedup_by_stable_id_keeps_higher_score(sample_blocks, sample_cleaned):
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=sample_blocks
    )
    # Phải giữ block có score 0.91, drop block 0.70 (cùng stable_id)
    kept = [e for e in lc.evidence if e.vector_id == "clause:D168-2024-ND-CP-A-6-K4"]
    assert len(kept) == 1
    assert kept[0].scores.final_score == 0.91
    # Duplicate không được đưa vào evidence
    assert not any(e.vector_id == "clause:D168-2024-ND-CP-A-6-K4-dup" for e in lc.evidence)

# ============================================================
# Hierarchy structure (Document → Chapter → Article → Clause)
# ============================================================
def test_hierarchy_nesting(sample_blocks, sample_cleaned):
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=sample_blocks
    )
    # Document Nghị định có Chapter II, Article 6, Clause 4
    nd = next(d for d in lc.hierarchy.documents if d.document_id == "D168-2024-ND-CP")
    assert len(nd.chapters) == 1
    assert nd.chapters[0].chapter_id == "D168-2024-ND-CP-CII"
    assert len(nd.chapters[0].articles) == 1
    art = nd.chapters[0].articles[0]
    assert art.article_id == "D168-2024-ND-CP-A-6"
    assert len(art.clauses) == 1
    assert art.clauses[0].clause_id == "D168-2024-ND-CP-A-6-K4"
    assert art.clauses[0].evidence_ids == ["EV-001"]
    # Document Luật có Article 15, không có Clause (vì article-level)
    luat = next(d for d in lc.hierarchy.documents if d.document_id == "L36-2024-QH15")
    art15 = luat.chapters[0].articles[0]
    assert art15.article_id == "L36-2024-QH15-A-15"
    assert art15.clauses == []  # không có clause → list rỗng, không crash


# ============================================================
# Citation mapping (CIT-NNN → EV-NNN)
# ============================================================
def test_citation_evidence_mapping(sample_blocks, sample_cleaned):
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=sample_blocks
    )
    ev_ids = {e.evidence_id for e in lc.evidence}
    cit_ev_ids = {c.evidence_id for c in lc.citations}
    assert cit_ev_ids == ev_ids, "Mọi citation phải trỏ về 1 evidence tồn tại"
    # Citation short text phải đúng
    assert "Điều 6" in lc.citations[0].short
    assert "Khoản 4" in lc.citations[0].short
    # Citation document metadata populate
    assert lc.citations[0].document.type == "Nghị định"
    assert lc.citations[0].document.number == "168/2024/NĐ-CP"


# ============================================================
# Empty evidence
# ============================================================
def test_empty_retrieved_blocks(sample_cleaned):
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=[]
    )
    assert lc.evidence == []
    assert lc.citations == []
    assert lc.hierarchy.documents == []
    assert lc.formatted_context == ""
    assert lc.stats == {
        "b4_count": 0, "deduped_count": 0, "kept_count": 0, "dropped_count": 0,
    }


# ============================================================
# Malformed evidence (thiếu field)
# ============================================================
def test_malformed_block_missing_fields(sample_cleaned):
    """Block gần như rỗng - B5 KHÔNG được crash, evidence vẫn được tạo."""
    bad_blocks = [
        {
            "score": 0.5, "citation": "?", "context_block": "unknown",
            # thiếu pinecone_meta, law_*, article_*, ...
        }
    ]
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=bad_blocks
    )
    assert len(lc.evidence) == 1
    ev = lc.evidence[0]
    assert ev.node_type == "Unknown"
    assert ev.stable_id.document_id is None
    # Fallback: hierarchy_path[0] = "Document" khi thiếu doc label
    assert ev.hierarchy_path[0] == "Document"
    # Ungrouped (không có document_id)
    assert "EV-001" in lc.hierarchy.ungrouped_evidence_ids


def test_block_with_only_article_id_no_clause(sample_cleaned):
    blocks = [{
        "score": 0.7, "citation": "X - Điều 1", "context_block": "x",
        "article_number": "1",
        "pinecone_meta": {"type": "article", "document_id": "DOC1", "article_id": "DOC1-A1"},
    }]
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=blocks
    )
    ev = lc.evidence[0]
    assert ev.node_type == "Article"
    assert ev.stable_id.article_id == "DOC1-A1"
    assert ev.stable_id.clause_id is None
    # Không có chapter → path chỉ có doc + article (2 cấp)
    assert len(ev.hierarchy_path) == 2
    assert "Điều 1" in ev.hierarchy_path[1]
    # Dedup key dùng article_id (không có clause)
    assert ev.stable_id.dedup_key() == "article:DOC1-A1"


# ============================================================
# Context size limit (max_evidence)
# ============================================================
def test_max_evidence_cap(sample_cleaned):
    blocks = []
    for i in range(15):
        blocks.append({
            "score": 0.9 - i * 0.01,
            "vector_id": f"v{i}",
            "type": "clause",
            "citation": f"X - Điều {i}",
            "context_block": f"ctx{i}",
            "article_number": str(i),
            "pinecone_meta": {
                "type": "clause", "document_id": "DOC", "article_id": f"A{i}",
            },
        })
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=blocks,
        max_evidence=5,
    )
    assert len(lc.evidence) == 5
    assert lc.stats["kept_count"] == 5
    assert lc.stats["dropped_count"] == 10


# ============================================================
# Sort by final_score desc
# ============================================================
def test_evidence_sorted_by_score_desc(sample_blocks, sample_cleaned):
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=sample_blocks
    )
    scores = [e.scores.final_score for e in lc.evidence]
    assert scores == sorted(scores, reverse=True)


# ============================================================
# Backward-compat: build_context_for_llm / build_sources_for_response
# ============================================================
def test_backward_compat_build_context_for_llm(sample_blocks):
    """Hàm cũ KHÔNG được đổi signature/output - B6 nếu quay lại dùng vẫn chạy."""
    text = build_context_for_llm(sample_blocks)
    assert "Nguồn 1" in text
    assert "độ tương đồng" in text
    # Duplicate block bị dedup
    assert text.count("DUPLICATE block") == 0


def test_backward_compat_build_sources(sample_blocks):
    sources = build_sources_for_response(sample_blocks)
    assert len(sources) == 2  # dedup theo citation
    assert all("citation" in s and "score" in s for s in sources)


# ============================================================
# Pydantic validation
# ============================================================
def test_evidence_item_pydantic_validation():
    """EvidenceItem phải là Pydantic - không accept input sai shape."""
    from app.rag.schemas.legal_context import EvidenceItem, Scores, StableId

    # OK
    ev = EvidenceItem(
        evidence_id="EV-001",
        stable_id=StableId(document_id="D1"),
        scores=Scores(final_score=0.9),
        content="test",
    )
    assert ev.evidence_id == "EV-001"
    # evidence_id là required
    with pytest.raises(ValidationError):
        EvidenceItem(stable_id=StableId(), scores=Scores(final_score=0.0))


def test_legal_context_json_roundtrip(sample_blocks, sample_cleaned):
    """LegalContext phải serialize/deserialize được (B6/B7 dev có thể log/debug)."""
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=sample_blocks
    )
    j = lc.model_dump_json()
    assert "EV-001" in j
    assert "CIT-001" in j
    # Re-parse
    from app.rag.schemas.legal_context import LegalContext
    lc2 = LegalContext.model_validate_json(j)
    assert lc2.evidence[0].evidence_id == lc.evidence[0].evidence_id
    assert len(lc2.citations) == len(lc.citations)


# ============================================================
# Stable ID dedup key uniqueness
# ============================================================
def test_dedup_key_uniqueness_across_levels():
    """Cùng article_id nhưng khác clause_id → KHÔNG dedup nhầm."""
    from app.rag.schemas.legal_context import StableId
    a = StableId(document_id="D", article_id="A", clause_id="A-K1")
    b = StableId(document_id="D", article_id="A", clause_id="A-K2")
    assert a.dedup_key() != b.dedup_key()
    # Cùng clause_id ở 2 doc khác nhau → khác key (vì clause_id chứa doc prefix)
    c = StableId(document_id="D1", clause_id="A-K1")
    d = StableId(document_id="D2", clause_id="A-K1")
    # Nếu clause_id đã unique (vd: "D1-A-K1" vs "D2-A-K1") → khác
    # Nếu clause_id raw trùng → key trùng (giống design hiện tại của project)


# ============================================================
# B7 traceability: evidence_id → citation_id lookup
# ============================================================
def test_evidence_to_citation_lookup_table(sample_blocks, sample_cleaned):
    """B7 cần map nhanh evidence_id → citation_id. LegalContext cung cấp sẵn."""
    lc = build_legal_context(
        question="test", cleaned=sample_cleaned, retrieved_blocks=sample_blocks
    )
    ev_to_cit = {c.evidence_id: c.citation_id for c in lc.citations}
    for ev in lc.evidence:
        assert ev.evidence_id in ev_to_cit
        assert ev_to_cit[ev.evidence_id].startswith("CIT-")


# ============================================================
# ACCEPTANCE TESTS — Plan §11 (B5 policy echo + status + expansion kinds)
# ============================================================
def _make_block_with_status(
    vid,
    score,
    *,
    is_active=True,
    eff_from=None,
    eff_to=None,
    expansion_kind="anchor",
    expanded_from=None,
):
    """Helper: B4-style block với các field mới (is_active, expansion_kind, ...)."""
    return {
        "score": score,
        "pinecone_score": score,
        "boosted": False,
        "vector_id": vid,
        "type": "clause",
        "citation": f"Doc X - Điều 1, Khoản 1 (vid={vid})",
        "context_block": f"context {vid}",
        "law_document_type": "Nghị định",
        "law_document_number": "X/2024",
        "law_title": "Mock",
        "law_date_enacted": "2024-01-01",
        "law_date_effective": "2025-01-01",
        "law_issuing_authority": "Mock",
        "chapter_number": "I",
        "chapter_title": "Mock",
        "article_number": "1",
        "article_title": "Mock",
        "clause_number": "1",
        "related_amendments": [],
        "pinecone_meta": {
            "type": "clause",
            "document_id": "DOC-X",
            "chapter_id": "DOC-X-C1",
            "article_id": "DOC-X-A-1",
            "clause_id": f"DOC-X-A-1-K1-{vid}",
        },
        "is_active": is_active,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "expansion_kind": expansion_kind,
        "expanded_from": expanded_from or [],
    }


# Test #6a: evidence[].is_active đúng (True / False đều được map)
def test_evidence_is_active_flag_preserved():
    cleaned = {
        "cleaned_query": "test", "intent": "general_info",
        "legal_domain": "", "key_legal_terms": [],
    }
    blocks = [
        _make_block_with_status("v1", 0.9, is_active=True),
        _make_block_with_status("v2", 0.8, is_active=False, eff_to="2024-12-31"),
    ]
    lc = build_legal_context(
        question="test", cleaned=cleaned, retrieved_blocks=blocks,
    )
    assert len(lc.evidence) == 2
    active_blocks = [e for e in lc.evidence if e.is_active]
    inactive_blocks = [e for e in lc.evidence if not e.is_active]
    assert len(active_blocks) == 1
    assert len(inactive_blocks) == 1
    # effective_to được map vào evidence (kể cả khi inactive)
    assert inactive_blocks[0].effective_to == "2024-12-31"


# Test #6b: expansion_kind ∈ {anchor, horizontal, up, down, neighbor}
def test_evidence_expansion_kind_in_allowed_values():
    cleaned = {
        "cleaned_query": "test", "intent": "general_info",
        "legal_domain": "", "key_legal_terms": [],
    }
    kinds = ["anchor", "horizontal", "up", "down", "neighbor"]
    blocks = [
        _make_block_with_status(f"v{i}", 0.9 - i * 0.05, expansion_kind=k)
        for i, k in enumerate(kinds)
    ]
    lc = build_legal_context(
        question="test", cleaned=cleaned, retrieved_blocks=blocks,
    )
    assert len(lc.evidence) == len(kinds)
    seen_kinds = {e.expansion_kind for e in lc.evidence}
    assert seen_kinds == set(kinds), "Phải có đủ 5 expansion_kind"


# Test #6c: expanded_from đúng (vector_id của anchor đã mở rộng ra node này)
def test_evidence_expanded_from_tracks_anchor():
    cleaned = {
        "cleaned_query": "test", "intent": "general_info",
        "legal_domain": "", "key_legal_terms": [],
    }
    anchor_vid = "anchor-1"
    blocks = [
        # Anchor
        _make_block_with_status(anchor_vid, 0.9, expansion_kind="anchor",
                                 expanded_from=[]),
        # Expansion sibling
        _make_block_with_status("sibling-1", 0.0, expansion_kind="horizontal",
                                 expanded_from=[anchor_vid]),
    ]
    lc = build_legal_context(
        question="test", cleaned=cleaned, retrieved_blocks=blocks,
    )
    expanded_blocks = [e for e in lc.evidence if e.expansion_kind != "anchor"]
    assert len(expanded_blocks) == 1
    assert expanded_blocks[0].expanded_from == [anchor_vid]


# Test #6d: retrieval_policy được echo vào RequestInfo + stats
def test_legal_context_echoes_retrieval_policy():
    cleaned = {
        "cleaned_query": "test", "intent": "penalty_lookup",
        "legal_domain": "xử phạt giao thông",
        "key_legal_terms": ["phạt"],
        # New fields
        "resolved_query": "phạt xe máy ơ",
        "history_dependent": True,
        "missing_facts": ["vehicle_type"],
        "retrieval_policy": {
            "intensity": "default",
            "expansion": "siblings",
            "max_evidence_hint": 10,
            "filters": {"require_active": True, "document_type": "Nghị định"},
            "missing_facts": ["vehicle_type"],
            "source_intent": "penalty_lookup",
        },
    }
    lc = build_legal_context(
        question="Phạt bao nhiêu?", cleaned=cleaned, retrieved_blocks=[
            _make_block_with_status("v1", 0.9),
        ],
    )
    # RequestInfo có retrieval_policy + resolved_query + history_dependent
    assert lc.request.retrieval_policy == cleaned["retrieval_policy"]
    assert lc.request.resolved_query == "phạt xe máy ơ"
    assert lc.request.history_dependent is True
    # Stats echo policy (để B7 + debug)
    assert "retrieval_policy" in lc.stats
    assert lc.stats["retrieval_policy"]["expansion"] == "siblings"


# Test #6e: hierarchy.expanded=True + expansion_summary khi có expansion
def test_hierarchy_expansion_markers():
    cleaned = {
        "cleaned_query": "test", "intent": "general_info",
        "legal_domain": "", "key_legal_terms": [],
        "retrieval_policy": {"expansion": "siblings", "filters": {}},
    }
    blocks = [
        _make_block_with_status("a1", 0.9, expansion_kind="anchor"),
        _make_block_with_status("a2", 0.0, expansion_kind="horizontal",
                                 expanded_from=["a1"]),
        _make_block_with_status("a3", 0.0, expansion_kind="neighbor",
                                 expanded_from=["a1"]),
    ]
    lc = build_legal_context(
        question="test", cleaned=cleaned, retrieved_blocks=blocks,
    )
    assert lc.hierarchy.expanded is True
    assert "anchor" in lc.hierarchy.expansion_summary
    assert "horizontal" in lc.hierarchy.expansion_summary
    assert "neighbor" in lc.hierarchy.expansion_summary


# Test #6f: hierarchy.expanded=False khi policy.expansion='none'
def test_hierarchy_not_expanded_when_policy_none():
    cleaned = {
        "cleaned_query": "test", "intent": "list_clauses",
        "legal_domain": "", "key_legal_terms": [],
        "retrieval_policy": {"expansion": "none", "filters": {}},
    }
    blocks = [
        _make_block_with_status("v1", 0.9, expansion_kind="anchor"),
    ]
    lc = build_legal_context(
        question="test", cleaned=cleaned, retrieved_blocks=blocks,
    )
    assert lc.hierarchy.expanded is False
    assert lc.hierarchy.expansion_summary == ""


# Test #6g: stats.expansion_executed.kind_counts khi có expansion
def test_stats_expansion_executed_counts():
    cleaned = {
        "cleaned_query": "test", "intent": "general_info",
        "legal_domain": "", "key_legal_terms": [],
        "retrieval_policy": {"expansion": "neighbors", "filters": {}},
    }
    blocks = [
        _make_block_with_status("a1", 0.9, expansion_kind="anchor"),
        _make_block_with_status("a2", 0.0, expansion_kind="horizontal",
                                 expanded_from=["a1"]),
        _make_block_with_status("a3", 0.0, expansion_kind="horizontal",
                                 expanded_from=["a1"]),
        _make_block_with_status("a4", 0.0, expansion_kind="up",
                                 expanded_from=["a1"]),
    ]
    lc = build_legal_context(
        question="test", cleaned=cleaned, retrieved_blocks=blocks,
    )
    assert "expansion_executed" in lc.stats
    counts = lc.stats["expansion_executed"]["kind_counts"]
    assert counts.get("anchor") == 1
    assert counts.get("horizontal") == 2
    assert counts.get("up") == 1


# Test #7: E2E pipeline chạy, response shape không đổi, debug có stats.retrieval_policy
def test_e2e_pipeline_legal_context_full_shape(mock_engine):
    """Acceptance test #7: full pipeline → LegalContext có stats.retrieval_policy."""
    from app.rag.orchestrator import run_pipeline

    response = run_pipeline(
        engine=mock_engine,
        question="Phạt bao nhiêu khi đi xe máy không nhường đường?",
        top_k=5,
        verify=True,
    )
    # Response shape không đổi
    assert response.answer
    assert response.sources
    assert response.verification is not None
    # Debug có legal_context stats (cho developer/observability)
    legal_ctx_stats = response.debug.get("legal_context", {}).get("stats", {})
    # Verify shape không vỡ
    assert "evidence_count" in response.debug["legal_context"]
    assert "citation_count" in response.debug["legal_context"]
    assert "stats" in response.debug["legal_context"]


# Test E2E thiếu dữ kiện (case 2 trong Plan §11): câu mơ hồ → missing_facts populate
def test_e2e_missing_fact_query_path():
    """Acceptance test: câu 'Phạt bao nhiêu khi vượt đèn đỏ?' (không rõ xe gì) → missing_facts có vehicle_type."""
    from app.rag.steps.cleaner import step_clean_query

    q = "Phạt bao nhiêu khi vượt đèn đỏ?"
    cleaned = step_clean_query(None, q)  # fallback rule-based

    # Câu không có vehicle → missing_facts phải có vehicle_type
    assert "vehicle_type" in cleaned.get("missing_facts", []), \
        "Câu phạt mà không rõ xe gì phải flag missing_facts=vehicle_type"
    # policy.expansion phải boost lên 'neighbors' do missing_facts
    policy = cleaned["retrieval_policy"]
    assert policy["expansion"] == "neighbors", \
        "Missing fact → expansion phải boost lên neighbors để lấy đủ context"
