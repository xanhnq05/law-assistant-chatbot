"""
Pydantic schemas cho ChatMessage.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Một message trong cuộc hội thoại."""

    message_id: Optional[str] = None
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str
    sources: List[dict] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class AddMessageRequest(BaseModel):
    """Request body khi thêm một message vào session."""

    session_id: str
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str
    sources: List[dict] = Field(default_factory=list)