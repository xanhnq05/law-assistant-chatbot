"""
Utility lấy một chat session theo session_id và user_id.

Kiểm tra owner để tránh user khác đọc trộm session.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


def get_chat(
    user_id: Any,
    session_id: str
) -> Optional[Dict[str, Any]]:
    """
    Tìm chat session theo user_id và session_id.

    Args:
        user_id: MongoDB ObjectId hoặc string của User.
        session_id: UUID của chat session.

    Returns:
        Dict session nếu tìm thấy, None nếu không.
    """
    if not user_id or not session_id:
        return None

    try:
        user_object_id = (
            user_id
            if isinstance(user_id, ObjectId)
            else ObjectId(str(user_id))
        )
    except (InvalidId, TypeError):
        return None

    document = chat_history_collection.find_one(
        {"user_id": user_object_id, "chats.session_id": session_id},
        {"chats.$": 1},
    )

    if not document:
        return None

    chats = document.get("chats", [])
    return chats[0] if chats else None