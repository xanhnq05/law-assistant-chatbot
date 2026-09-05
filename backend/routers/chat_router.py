"""
Router xử lý chat history cho user đã đăng nhập.

Tất cả endpoint yêu cầu JWT hợp lệ (Authorization: Bearer <token>).

Endpoints:
- POST   /chats/                      : tạo chat session mới
- GET    /chats/                      : lấy toàn bộ chat history của user
- GET    /chats/{session_id}          : lấy 1 chat session
- PATCH  /chats/{session_id}          : cập nhật title chat session
- DELETE /chats/{session_id}          : xoá chat session
- POST   /chats/{session_id}/messages : thêm message vào session
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schemas import (
    AddMessageRequest,
    ChatMessage,
    ChatSessionResponse,
    CreateChatRequest,
    UpdateChatRequest,
)
from services.auth_service import get_current_user
from services.chat_service import (
    add_chat_message,
    create_new_chat,
    delete_user_chat,
    get_user_chat,
    get_user_history,
    update_user_chat,
)


router = APIRouter(prefix="/chats", tags=["chats"])
bearer_scheme = HTTPBearer(auto_error=False)


# ============================================================
# CREATE NEW CHAT
# ============================================================

@router.post("/", response_model=ChatSessionResponse, status_code=201)
async def create_chat(
    body: CreateChatRequest,
    request: Request,
):
    """Tạo một chat session mới cho user hiện tại."""
    user_id = await get_current_user(request)
    return create_new_chat(user_id=user_id, title=body.title)


# ============================================================
# LIST ALL CHATS OF USER
# ============================================================

@router.get("/", response_model=List[ChatSessionResponse])
async def list_chats(request: Request):
    """Lấy toàn bộ chat history của user hiện tại."""
    user_id = await get_current_user(request)
    return get_user_history(user_id=user_id)


# ============================================================
# GET ONE CHAT
# ============================================================

@router.get("/{session_id}", response_model=ChatSessionResponse)
async def get_chat(session_id: str, request: Request):
    """Lấy 1 chat session theo session_id."""
    user_id = await get_current_user(request)
    return get_user_chat(user_id=user_id, session_id=session_id)


# ============================================================
# UPDATE CHAT TITLE
# ============================================================

@router.patch("/{session_id}", response_model=ChatSessionResponse)
async def update_chat(
    session_id: str,
    body: UpdateChatRequest,
    request: Request,
):
    """Cập nhật title cho chat session."""
    user_id = await get_current_user(request)
    return update_user_chat(
        user_id=user_id,
        session_id=session_id,
        title=body.title,
    )


# ============================================================
# DELETE CHAT
# ============================================================

@router.delete("/{session_id}", status_code=200)
async def delete_chat(session_id: str, request: Request):
    """Xoá chat session."""
    user_id = await get_current_user(request)
    return delete_user_chat(user_id=user_id, session_id=session_id)


# ============================================================
# ADD MESSAGE TO CHAT
# ============================================================

@router.post(
    "/{session_id}/messages",
    response_model=ChatSessionResponse,
    status_code=201,
)
async def add_message(
    session_id: str,
    body: AddMessageRequest,
    request: Request,
):
    """Thêm message vào session và tự động generate answer bằng RAG."""
    user_id = await get_current_user(request)
    return add_chat_message(
        user_id=user_id,
        session_id=session_id,
        role=body.role,
        content=body.content,
        sources=body.sources,
    )