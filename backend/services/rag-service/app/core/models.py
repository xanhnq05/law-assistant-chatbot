"""Pydantic request/response schemas for rag-service.

Định nghĩa toàn bộ shape của input/output, bao gồm cả metadata
verification từ B7.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# REQUEST
# ============================================================
class ChatRequest(BaseModel):
    """POST /api/chat body."""

    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    # Cho phép user bật/tắt verification (mặc định bật để đảm bảo chất lượng).
    verify: bool = Field(default=True)


# ============================================================
# RESPONSE
# ============================================================
class SourceItem(BaseModel):
    """Một citation block được retrieve."""

    citation: str
    score: float
    context_block: str
    law_document_type: str = ""
    law_document_number: str = ""
    law_title: str = ""
    law_date_enacted: str = ""
    # Bổ sung từ hybrid retrieval
    law_date_effective: str = ""
    law_issuing_authority: str = ""
    chapter_number: str = ""
    chapter_title: str = ""
    article_number: str = ""
    article_title: str = ""
    clause_number: str = ""
    # Quan hệ AMEND/REPLACE/REPEAL được phát hiện (nếu có).
    related_amendments: list[dict[str, str]] = Field(default_factory=list)


class VerificationStatus(str, Enum):
    """Trạng thái verification từ B7."""

    PASS = "pass"               # Câu trả lời đạt yêu cầu, có trích dẫn đầy đủ
    WARN = "warn"               # Đạt nhưng có cảnh báo (vd: thiếu metadata)
    FAIL = "fail"               # Không đạt (không có citation, không đúng context)


class VerificationResult(BaseModel):
    """Kết quả symbolic verification (B7)."""

    status: VerificationStatus
    confidence: float = Field(..., ge=0.0, le=1.0)
    has_citation: bool = False
    citation_count: int = 0
    cites_valid_doc: bool = False
    context_grounded: bool = False
    issues: list[str] = Field(default_factory=list)
    llm_judge_used: bool = False
    llm_judge_reason: str | None = None


class ChatResponse(BaseModel):
    """POST /api/chat response."""

    answer: str
    sources: list[SourceItem]
    verification: VerificationResult
    debug: dict[str, Any]
