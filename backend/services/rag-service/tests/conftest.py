"""Shared pytest fixtures cho rag-service tests."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_llm():
    """Mock ChatGroq LLM (trả về JSON string cho B2/B7)."""
    llm = MagicMock()

    def _invoke(messages):
        # Detect system prompt để trả về JSON hợp lý
        sys_msg = ""
        for m in messages:
            content = getattr(m, "content", None)
            if content is None and isinstance(m, dict):
                content = m.get("content", "")
            if isinstance(content, str):
                sys_msg = content
                break
        # Default: trả JSON giả lập
        resp = MagicMock()
        if "LÀM SẠCH" in sys_msg or "QUERY_CLEANER" in sys_msg or "cleaner" in sys_msg.lower():
            resp.content = (
                '{"cleaned_query":"phạt xe máy không nhường đường",'
                '"legal_domain":"xử phạt giao thông",'
                '"key_legal_terms":["phạt","xe máy","không nhường đường"],'
                '"intent":"penalty_lookup"}'
            )
        elif "verifier" in sys_msg.lower() or "GRAND" in sys_msg:
            resp.content = (
                '{"is_grounded":true,"has_citation":true,'
                '"citation_correct":true,"addresses_question":true,'
                '"confidence":0.85,"issues":[],"reason":"OK"}'
            )
        else:
            resp.content = (
                "Theo Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4, "
                "phạt tiền từ 4-6 triệu đồng."
            )
        return resp

    llm.invoke.side_effect = _invoke
    return llm


@pytest.fixture
def sample_context_blocks():
    """Mock output của B4 (Hybrid Retrieval).

    Shape khớp với output thực tế của step_retrieve_hybrid v2.
    """
    return [
        {
            "score": 0.91,
            "pinecone_score": 0.83,  # boosted từ 0.83 → 0.91 do soft intent boost
            "boosted": True,
            "vector_id": "clause:D168-2024-ND-CP-A-6-K4",
            "type": "clause",
            "citation": "Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4",
            "context_block": (
                "Nghị định 168/2024/NĐ-CP - Xử phạt hành vi không nhường đường\n"
                "  Cơ quan ban hành: Chính phủ | Ngày ban hành: 2024-12-26\n"
                "  Chương II: VI PHẠM QUY TẮC GIAO THÔNG\n"
                "  Điều 6: Xử phạt hành vi không nhường đường\n"
                "    Khoản 4: Phạt tiền từ 4.000.000đ đến 6.000.000đ"
            ),
            "law_document_type": "Nghị định",
            "law_document_number": "168/2024/NĐ-CP",
            "law_title": "Xử phạt vi phạm hành chính",
            "law_date_enacted": "2024-12-26",
            "law_date_effective": "2025-01-01",
            "law_issuing_authority": "Chính phủ",
            "chapter_number": "II",
            "chapter_title": "VI PHẠM QUY TẮC GIAO THÔNG",
            "article_number": "6",
            "article_title": "Xử phạt hành vi không nhường đường",
            "clause_number": "4",
            "related_amendments": [],
            "pinecone_meta": {"type": "clause"},
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
                "  Cơ quan ban hành: Quốc hội | Ngày ban hành: 2024-06-27\n"
                "  Điều 15: Quy tắc nhường đường"
            ),
            "law_document_type": "Luật",
            "law_document_number": "36/2024/QH15",
            "law_title": "Trật tự an toàn giao thông đường bộ",
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
            "pinecone_meta": {"type": "article"},
        },
    ]


@pytest.fixture
def mock_engine(mock_llm, sample_context_blocks):
    """Mock RagEngine với tất cả dependencies."""
    from sentence_transformers import SentenceTransformer  # noqa: F401

    engine = MagicMock()
    engine.get_llm.return_value = mock_llm
    engine.get_verifier_llm.return_value = mock_llm

    # Mock embedder
    embedder = MagicMock()
    embedder.encode.return_value = [[0.1] * 384]
    engine.get_embedder.return_value = embedder

    # Mock Pinecone
    index = MagicMock()
    index.query.return_value.matches = [
        MagicMock(
            id="clause:D168-2024-ND-CP-A-6-K4",
            score=0.91,
            metadata={
                "type": "clause",
                "document_id": "D168-2024-ND-CP",
                "chapter_id": "D168-2024-ND-CP-CII",
                "article_id": "D168-2024-ND-CP-A-6",
                "clause_id": "D168-2024-ND-CP-A-6-K4",
            },
        ),
        MagicMock(
            id="article:L36-2024-QH15-A-15",
            score=0.85,
            metadata={
                "type": "article",
                "document_id": "L36-2024-QH15",
                "chapter_id": "L36-2024-QH15-CIII",
                "article_id": "L36-2024-QH15-A-15",
                "clause_id": "",
            },
        ),
    ]
    engine.get_pinecone_index.return_value = index

    # Mock Neo4j session — batch mode (v2: 1 query cho N match, không .single())
    session = MagicMock()

    def _build_ctx_row(mid: str, doc_id: str, art_id: str, doc_type: str, doc_number: str, art_num: str, art_title: str):
        return {
            "vector_id": mid,
            "pinecone_score": 0.0,  # filled by caller if needed
            "document_id": doc_id,
            "document_number": doc_number,
            "document_title": "Mock",
            "document_type": doc_type,
            "document_issuing_authority": "Mock",
            "document_date_enacted": "2024-12-26",
            "document_date_effective": "2025-01-01",
            "chapter_id": f"{doc_id}-CII",
            "chapter_number": "II",
            "chapter_title": "Mock Chapter",
            "article_id": art_id,
            "article_number": art_num,
            "article_title": art_title,
            "article_text": "",
            "clause_id": "",
            "clause_number": "",
            "clause_text": "",
            "forward_amendments": [],
            "backward_amendments": [],
        }

    rows = [
        _build_ctx_row(
            "clause:D168-2024-ND-CP-A-6-K4",
            "D168-2024-ND-CP",
            "D168-2024-ND-CP-A-6",
            "Nghị định",
            "168/2024/NĐ-CP",
            "6",
            "Xử phạt hành vi không nhường đường",
        ),
        _build_ctx_row(
            "article:L36-2024-QH15-A-15",
            "L36-2024-QH15",
            "L36-2024-QH15-A-15",
            "Luật",
            "36/2024/QH15",
            "15",
            "Quy tắc nhường đường",
        ),
    ]
    # session.run(...) phải trả về object có thể iterate thành rows
    cursor = MagicMock()
    cursor.__iter__ = lambda self: iter(rows)
    session.run.return_value = cursor

    # context manager support
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = None
    engine.neo_session.return_value = cm

    return engine
