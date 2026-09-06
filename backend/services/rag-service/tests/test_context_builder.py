"""Tests cho B5 - Context Builder."""
from __future__ import annotations

from rag.steps.context_builder import (
    build_context_for_llm,
    build_sources_for_response,
)


def test_build_context_for_llm_empty():
    assert build_context_for_llm([]) == ""


def test_build_context_for_llm_with_blocks(sample_context_blocks):
    ctx = build_context_for_llm(sample_context_blocks)
    assert "Nguồn 1" in ctx
    assert "Nguồn 2" in ctx
    assert "độ tương đồng" in ctx
    # Verify citation xuất hiện
    assert "Nghị định 168/2024/NĐ-CP" in ctx
    assert "Luật 36/2024/QH15" in ctx


def test_build_context_dedup_by_citation():
    """Nếu 2 blocks có cùng citation → chỉ giữ 1 (score cao hơn)."""
    b1 = {
        "score": 0.9, "citation": "X - Điều 1",
        "context_block": "block 1",
    }
    b2 = {
        "score": 0.7, "citation": "X - Điều 1",
        "context_block": "block 2 (duplicate, lower score)",
    }
    b3 = {
        "score": 0.5, "citation": "Y - Điều 2",
        "context_block": "block 3",
    }
    ctx = build_context_for_llm([b1, b2, b3])
    # Chỉ có 2 nguồn (b1 dedup b2, còn b3)
    assert "Nguồn 1" in ctx
    assert "Nguồn 2" in ctx
    assert "Nguồn 3" not in ctx
    assert "block 1" in ctx
    assert "block 2 (duplicate" not in ctx


def test_build_context_sorts_by_score_desc():
    blocks = [
        {"score": 0.5, "citation": "A", "context_block": "low"},
        {"score": 0.9, "citation": "B", "context_block": "high"},
    ]
    ctx = build_context_for_llm(blocks)
    # B (score 0.9) phải xuất hiện trước A (score 0.5)
    assert ctx.index("high") < ctx.index("low")


def test_build_context_includes_amendments():
    blocks = [
        {
            "score": 0.9,
            "citation": "X - Điều 1",
            "context_block": "ctx",
            "related_amendments": [
                {"type": "REPLACED_BY", "target_label": "Article", "target_number": "5"}
            ],
        },
    ]
    ctx = build_context_for_llm(blocks)
    assert "Quan hệ" in ctx
    assert "REPLACED_BY" in ctx


def test_build_sources_for_response(sample_context_blocks):
    sources = build_sources_for_response(sample_context_blocks)
    assert len(sources) == 2
    # Sorted by score desc
    assert sources[0]["score"] >= sources[1]["score"]
    # All required fields present
    for s in sources:
        assert "citation" in s
        assert "score" in s
        assert "context_block" in s


def test_build_sources_dedup(sample_context_blocks):
    """Trùng citation → 1 source."""
    dup = dict(sample_context_blocks[0])
    dup["score"] = 0.5  # lower
    sources = build_sources_for_response([sample_context_blocks[0], dup])
    assert len(sources) == 2  # vẫn 2 (sample_context_blocks[0] và sample_context_blocks[1])
    # Trong cùng 1 citation group: chỉ giữ score cao
    dup2 = dict(sample_context_blocks[0])
    dup2["citation"] = sample_context_blocks[0]["citation"]  # cùng citation
    dup2["score"] = 0.3
    sources2 = build_sources_for_response([sample_context_blocks[0], dup2])
    assert len(sources2) == 2  # 1 từ sample_context_blocks[0], 1 từ sample_context_blocks[1]
