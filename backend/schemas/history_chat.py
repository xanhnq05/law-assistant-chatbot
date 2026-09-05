"""
Pydantic schemas cho chat history document trong MongoDB.

Một user có một chat_history document, bên trong chứa danh sách các
chat session (mỗi session là một cuộc hội thoại gồm nhiều message).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from schemas.chat_message import ChatMessage
from schemas.chat_session import ChatSession


class ChatHistoryEntry(BaseModel):
    """Một entry chat session nằm trong mảng `chats` của chat_history."""

    session_id: str
    title: str = "Cuộc trò chuyện mới"
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessage] = Field(default_factory=list)
    metadata: dict = Field(default_factory=lambda: {"message_count": 0})


class ChatHistory(BaseModel):
    """Document chat_history của một user trong MongoDB."""

    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str
    chats: List[ChatHistoryEntry] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_object = True


class ChatHistoryResponse(BaseModel):
    """Response trả về cho client."""

    user_id: str
    chats: List[ChatHistoryEntry]