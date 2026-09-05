"""Router xử lý chat history cho user đã đăng nhập.

Tất cả endpoint yêu cầu JWT hợp lệ (Authorization: Bearer <token>).
Token được cấp bởi auth-service; chat-service chỉ verify chữ ký với
cùng JWT_SECRET_KEY.

Endpoints:
- POST   /chats/                       : tạo chat session mới
- GET    /chats/                       : lấy toàn bộ chat history của user
- GET    /chats/{session_id}           : lấy 1 chat session
- PATCH  /chats/{session_id}           : cập nhật title chat session
- DELETE /chats/{session_id}           : xoá chat session
- POST   /chats/{session_id}/messages  : thêm message (auto generate answer)
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.repositories.jwt_helper import decode_access_token
from app.schemas import (
    AddMessageRequest,
    ChatSessionResponse,
    CreateChatRequest,
    UpdateChatRequest,
)
from app.services.chat_service import (
    add_chat_message,
    create_new_chat,
    delete_user_chat,
    get_user_chat,
    get_user_history,
    update_user_chat,
)


router = APIRouter(prefix="/chats", tags=["chats"])

bearer_scheme = HTTPBearer(auto_error=False)


def _extract_user_id(request: Request) -> str:
    """Đọc JWT từ header Authorization, trả user_id (sub)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(parts[1])
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing subject",
        )
    return user_id


# ============================================================
# CREATE
# ============================================================
@router.post("/", response_model=ChatSessionResponse, status_code=201)
async def create_chat(body: CreateChatRequest, request: Request):
    """Tạo chat session mới cho user hiện tại."""
    user_id = _extract_user_id(request)
    return create_new_chat(user_id=user_id, title=body.title)


# ============================================================
# LIST
# ============================================================
@router.get("/", response_model=List[ChatSessionResponse])
async def list_chats(request: Request):
    """Lấy toàn bộ chat history của user hiện tại."""
    user_id = _extract_user_id(request)
    return get_user_history(user_id=user_id)


# ============================================================
# GET ONE
# ============================================================
@router.get("/{session_id}", response_model=ChatSessionResponse)
async def get_chat(session_id: str, request: Request):
    """Lấy 1 chat session theo session_id."""
    user_id = _extract_user_id(request)
    return get_user_chat(user_id=user_id, session_id=session_id)


# ============================================================
# UPDATE TITLE
# ============================================================
@router.patch("/{session_id}", response_model=ChatSessionResponse)
async def update_chat(session_id: str, body: UpdateChatRequest, request: Request):
    """Cập nhật title cho chat session."""
    user_id = _extract_user_id(request)
    return update_user_chat(
        user_id=user_id, session_id=session_id, title=body.title
    )


# ============================================================
# DELETE
# ============================================================
@router.delete("/{session_id}", status_code=200)
async def delete_chat(session_id: str, request: Request):
    """Xoá chat session."""
    user_id = _extract_user_id(request)
    return delete_user_chat(user_id=user_id, session_id=session_id)


# ============================================================
# ADD MESSAGE
# ============================================================
@router.post(
    "/{session_id}/messages",
    response_model=ChatSessionResponse,
    status_code=201,
)
async def add_message(session_id: str, body: AddMessageRequest, request: Request):
    """Thêm message vào session và tự động generate answer bằng RAG."""
    user_id = _extract_user_id(request)
    return add_chat_message(
        user_id=user_id,
        session_id=session_id,
        role=body.role,
        content=body.content,
        sources=body.sources,
    )
