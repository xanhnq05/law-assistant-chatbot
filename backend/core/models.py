"""
Pydantic request/response schemas exposed by the API.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class SourceItem(BaseModel):
    citation: str
    score: float
    context_block: str
    law_document_type: str = ""
    law_document_number: str = ""
    law_title: str = ""
    law_date_enacted: str = ""


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    debug: dict[str, Any]