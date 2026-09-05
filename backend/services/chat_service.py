"""
Chat service - điều phối nghiệp vụ liên quan đến chat history.

Service này KHÔNG trực tiếp truy vấn MongoDB, mà ủy quyền cho các
utility trong utils.chat và utils.user. Khi thêm message user, service
sẽ gọi RAG engine để sinh câu trả lời assistant và lưu lại.

Responsibilities:
- Tạo chat session mới
- Lấy 1 chat session
- Cập nhật title chat session
- Xoá chat session
- Lấy toàn bộ chat history của user
- Thêm message vào session (đồng thời generate answer bằng RAG)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request, status

from core.config import log
from rag.engine import RagEngine
from rag.steps import (
    step1_query_understanding,
    step2_retrieval,
    step3_answer,
)
from utils.chat import (
    add_message,
    check_chat_owner,
    create_chat,
    delete_chat,
    get_chat,
    get_chat_history,
    update_chat,
)
from utils.user import load_history


# ============================================================
# RAG ENGINE SINGLETON (lazy)
# ============================================================
# Chia sẻ với app.lifespan: nếu app đã init thì engine.get_llm() != None.
# Nếu app chưa init (ví dụ test đơn lẻ), sẽ fail gracefully với 503.

_engine = RagEngine()


def get_engine() -> RagEngine:
    return _engine


# ============================================================
# CREATE NEW CHAT
# ============================================================

def create_new_chat(
    user_id: Any,
    title: str = "Cuộc trò chuyện mới"
) -> Dict[str, Any]:
    """
    Tạo chat session mới cho user.

    Args:
        user_id: MongoDB ObjectId hoặc string.
        title: Tiêu đề session.

    Returns:
        Dict session vừa tạo.

    Raises:
        HTTPException: 400 nếu user_id không hợp lệ.
    """
    try:
        return create_chat(user_id=user_id, title=title)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ============================================================
# GET ONE CHAT
# ============================================================

def get_user_chat(
    user_id: Any,
    session_id: str
) -> Dict[str, Any]:
    """Lấy 1 chat session, đồng thời kiểm tra quyền sở hữu."""
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id is required",
        )

    if not check_chat_owner(user_id=user_id, session_id=session_id):
        session = get_chat(user_id=user_id, session_id=session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this chat session",
        )

    session = get_chat(user_id=user_id, session_id=session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )
    return session


# ============================================================
# UPDATE CHAT TITLE
# ============================================================

def update_user_chat(
    user_id: Any,
    session_id: str,
    title: str
) -> Dict[str, Any]:
    """Cập nhật title cho session, kèm kiểm tra quyền sở hữu."""
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
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )
    return session


# ============================================================
# DELETE CHAT
# ============================================================

def delete_user_chat(
    user_id: Any,
    session_id: str
) -> Dict[str, bool]:
    """Xoá session, kèm kiểm tra quyền sở hữu."""
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id is required",
        )

    if not check_chat_owner(user_id=user_id, session_id=session_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found or access denied",
        )

    deleted = delete_chat(user_id=user_id, session_id=session_id)
    return {"deleted": deleted}


# ============================================================
# GET FULL CHAT HISTORY OF USER
# ============================================================

def get_user_history(
    user_id: Any
) -> List[Dict[str, Any]]:
    """Lấy toàn bộ chat history của user."""
    return load_history(user_id=user_id)


# ============================================================
# GENERATE ANSWER VIA RAG
# ============================================================

def _run_rag(question: str, top_k: int = 5) -> Dict[str, Any]:
    """
    Gọi RAG pipeline. Trả về dict {answer, sources, debug}.

    Nếu engine chưa sẵn sàng -> trả answer mặc định.
    """
    engine = get_engine()
    llm = engine.get_llm()
    if not llm:
        log.warning("RAG engine chưa init - trả fallback cho user.")
        return {
            "answer": (
                "Xin lỗi, hệ thống RAG (LLM/Embedder) hiện chưa sẵn sàng. "
                "Vui lòng kiểm tra GROQ_API_KEY, Pinecone và Neo4j, "
                "sau đó khởi động lại backend."
            ),
            "sources": [],
            "debug": {},
        }

    try:
        understood = step1_query_understanding(llm, question)
        blocks = step2_retrieval(
            engine,
            understood.get("reformulated_query", question),
            top_k,
        )
        answer = step3_answer(llm, question, blocks)
        return {
            "answer": answer,
            "sources": blocks,  # list of dict từ B2
            "debug": {
                "reformulated_query": understood.get("reformulated_query", ""),
                "legal_domain": understood.get("legal_domain", ""),
                "key_legal_terms": understood.get("key_legal_terms", []),
            },
        }
    except Exception as exc:
        log.exception("RAG pipeline lỗi")
        return {
            "answer": f"Xin lỗi, đã có lỗi khi xử lý câu hỏi: {exc}",
            "sources": [],
            "debug": {},
        }


# ============================================================
# ADD MESSAGE TO CHAT (+ auto-generate assistant answer)
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
    """
    Thêm message user vào session, sau đó tự động gọi RAG tạo câu trả lời
    assistant (nếu role == 'user' và generate_answer=True).

    Trả về toàn bộ session sau khi đã thêm cả 2 message.
    """
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

    msg = add_message(
        user_id=user_id,
        session_id=session_id,
        role=role,
        content=content,
        sources=sources,
    )
    if msg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid message payload",
        )

    # Chỉ generate answer khi user vừa gửi message.
    if role == "user" and generate_answer:
        rag_result = _run_rag(content, top_k=top_k)
        assistant_msg = add_message(
            user_id=user_id,
            session_id=session_id,
            role="assistant",
            content=rag_result["answer"],
            sources=rag_result.get("sources") or [],
        )
        if assistant_msg is None:
            log.warning("Không thêm được assistant message")

    # Trả về session đầy đủ cho client.
    full_session = get_chat(user_id=user_id, session_id=session_id)
    if full_session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không lấy lại được session sau khi thêm message",
        )
    return full_session