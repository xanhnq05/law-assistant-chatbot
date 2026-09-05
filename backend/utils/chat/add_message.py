"""
Utility thêm một message vào chat session.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


def add_message(
    user_id: Any,
    session_id: str,
    role: str,
    content: str,
    sources: Optional[List[dict]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Thêm một message mới vào session và trả về message vừa tạo.

    Args:
        user_id: MongoDB ObjectId hoặc string.
        session_id: UUID của session.
        role: Vai trò của message ('user' | 'assistant' | 'system').
        content: Nội dung message.
        sources: Danh sách trích dẫn nguồn (cho assistant).

    Returns:
        Dict message vừa được thêm vào, None nếu input không hợp lệ
        hoặc không tìm thấy session.
    """
    if not user_id or not session_id:
        return None
    if role not in ("user", "assistant", "system"):
        return None
    if not content:
        return None

    try:
        user_object_id = (
            user_id
            if isinstance(user_id, ObjectId)
            else ObjectId(str(user_id))
        )
    except (InvalidId, TypeError):
        return None

    message: Dict[str, Any] = {
        "message_id": str(uuid4()),
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": datetime.now(timezone.utc),
    }

    now = datetime.now(timezone.utc)
    result = chat_history_collection.find_one_and_update(
        {
            "user_id": user_object_id,
            "chats.session_id": session_id,
        },
        {
            "$push": {"chats.$.messages": message},
            "$inc": {"chats.$.metadata.message_count": 1},
            "$set": {
                "chats.$.updated_at": now,
                "updated_at": now,
            },
        },
        return_document=True,
        projection={"chats.$": 1},
    )

    if not result:
        return None

    chats = result.get("chats", [])
    if not chats:
        return None

    session = chats[0]
    messages = session.get("messages", [])
    return messages[-1] if messages else message