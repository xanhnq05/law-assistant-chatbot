"""
Pydantic schemas cho ChatSession.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.chat_message import ChatMessage


class ChatSession(BaseModel):
    """Một cuộc hội thoại giữa user và hệ thống."""

    session_id: Optional[str] = None
    user_id: str
    title: str = "Cuộc trò chuyện mới"
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: dict = Field(default_factory=lambda: {"message_count": 0})


class CreateChatRequest(BaseModel):
    """Request body khi tạo chat session mới."""

    title: str = "Cuộc trò chuyện mới"


class UpdateChatRequest(BaseModel):
    """Request body khi cập nhật title của chat session."""

    title: str = Field(..., min_length=1, max_length=200)


class ChatSessionResponse(BaseModel):
    """Response trả về cho client."""

    session_id: str
    user_id: str
    title: str
    messages: List[ChatMessage]
    created_at: datetime
    updated_at: datetime
    metadata: dict = Field(default_factory=lambda: {"message_count": 0})