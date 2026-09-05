"""
Pydantic schemas package.

Exports:
- User, UserPublic, LoginResponse, GoogleUserInfo
- ChatMessage, AddMessageRequest
- ChatSession, CreateChatRequest, UpdateChatRequest, ChatSessionResponse
- ChatHistoryEntry, ChatHistory, ChatHistoryResponse
"""
from __future__ import annotations

from schemas.chat_message import AddMessageRequest, ChatMessage
from schemas.chat_session import (
    ChatSession,
    ChatSessionResponse,
    CreateChatRequest,
    UpdateChatRequest,
)
from schemas.history_chat import (
    ChatHistory,
    ChatHistoryEntry,
    ChatHistoryResponse,
)
from schemas.user import (
    GoogleUserInfo,
    LoginResponse,
    User,
    UserPublic,
)

__all__ = [
    "User",
    "UserPublic",
    "LoginResponse",
    "GoogleUserInfo",
    "ChatMessage",
    "AddMessageRequest",
    "ChatSession",
    "ChatSessionResponse",
    "CreateChatRequest",
    "UpdateChatRequest",
    "ChatHistory",
    "ChatHistoryEntry",
    "ChatHistoryResponse",
]