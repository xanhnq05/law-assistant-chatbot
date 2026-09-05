"""
Utility xoá một chat session.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


def delete_chat(
    user_id: Any,
    session_id: str
) -> bool:
    """
    Xoá một chat session khỏi chat_history của user.

    Args:
        user_id: MongoDB ObjectId hoặc string.
        session_id: UUID của session.

    Returns:
        True nếu xoá thành công, False nếu user_id không hợp lệ
        hoặc không tìm thấy session.
    """
    if not user_id or not session_id:
        return False

    try:
        user_object_id = (
            user_id
            if isinstance(user_id, ObjectId)
            else ObjectId(str(user_id))
        )
    except (InvalidId, TypeError):
        return False

    now = datetime.now(timezone.utc)
    result = chat_history_collection.update_one(
        {"user_id": user_object_id},
        {
            "$pull": {"chats": {"session_id": session_id}},
            "$set": {"updated_at": now},
        },
    )

    return result.modified_count > 0