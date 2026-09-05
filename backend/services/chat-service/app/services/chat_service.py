"""Chat-service business layer.

Responsibilities:
- CRUD chat session (create / list / get / update title / delete)
- Thêm message (user) + gọi rag-service để sinh câu trả lời (assistant)
- Kiểm tra ownership mọi thao tác

KHÔNG trực tiếp truy vấn MongoDB — qua chat_repository.
KHÔNG tự chạy RAG — qua rag_client (HTTP sang rag-service).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.core.config import log
from app.repositories.chat_repository import (
    add_message as repo_add_message,
    check_chat_owner,
    create_chat,
    delete_chat,
    get_chat,
    list_user_chats,
    update_chat,
)
from app.services.rag_client import RagClient, get_rag_client


_rag_client: Optional[RagClient] = None


def _rag() -> RagClient:
    global _rag_client
    if _rag_client is None:
        _rag_client = get_rag_client()
    return _rag_client


# ============================================================
# CRUD
# ============================================================
def create_new_chat(user_id: Any, title: str = "Cuộc trò chuyện mới") -> Dict[str, Any]:
    try:
        return create_chat(user_id=user_id, title=title)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


def get_user_chat(user_id: Any, session_id: str) -> Dict[str, Any]:
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required"
        )
    if not check_chat_owner(user_id=user_id, session_id=session_id):
        # Phân biệt 404 (không tồn tại) và 403 (không thuộc user) — đã có
        # owner-check fail, ta không lộ thông tin đó là 404 hay 403.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )
    session = get_chat(user_id=user_id, session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        )
    return session


def update_user_chat(user_id: Any, session_id: str, title: str) -> Dict[str, Any]:
    if not session_id or not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id and title are required",
        )
    if not check_chat_owner(user_id=user_id, session_id=session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )
    session = update_chat(user_id=user_id, session_id=session_id, title=title)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        )
    return session


def delete_user_chat(user_id: Any, session_id: str) -> Dict[str, bool]:
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="session_id is required"
        )
    if not check_chat_owner(user_id=user_id, session_id=session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )
    return {"deleted": delete_chat(user_id=user_id, session_id=session_id)}


def get_user_history(user_id: Any) -> List[Dict[str, Any]]:
    return list_user_chats(user_id=user_id)


# ============================================================
# ADD MESSAGE + AUTO ANSWER
# ============================================================
def add_chat_message(
    user_id: Any,
    session_id: str,
    role: str,
    content: str,
    sources: Optional[List[dict]] = None,
    generate_answer: bool = True,
    top_k: int = 5,
) -> Dict[str, Any]:
    """Push message mới + (nếu role=user) gọi RAG để push câu trả lời assistant."""
    if not session_id or not role or not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id, role and content are required",
        )
    if not check_chat_owner(user_id=user_id, session_id=session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )

    msg = repo_add_message(
        user_id=user_id,
        session_id=session_id,
        role=role,
        content=content,
        sources=sources,
    )
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid message payload"
        )

    if role == "user" and generate_answer:
        # Gọi rag-service bằng HTTP. Nếu fail, rag_client đã trả fallback.
        rag_result = _rag().ask_sync_safe(content, top_k=top_k)
        assistant = repo_add_message(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=rag_result.get("answer", ""),
            sources=rag_result.get("sources", []),
        )
        if assistant is None:
            log.warning("Không thêm được assistant message")

    full_session = get_chat(user_id=user_id, session_id=session_id)
    if full_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không lấy lại được session sau khi thêm message",
        )
    return full_session
