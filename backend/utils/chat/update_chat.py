"""
Utility cập nhật title cho một chat session.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


def update_chat(
    user_id: Any,
    session_id: str,
    title: str
) -> Optional[dict]:
    """
    Cập nhật title cho một chat session.

    Args:
        user_id: MongoDB ObjectId hoặc string.
        session_id: UUID của session.
        title: Title mới.

    Returns:
        Dict session sau khi cập nhật, None nếu không tìm thấy.
    """
    if not user_id or not session_id or not title:
        return None

    try:
        user_object_id = (
            user_id
            if isinstance(user_id, ObjectId)
            else ObjectId(str(user_id))
        )
    except (InvalidId, TypeError):
        return None

    now = datetime.now(timezone.utc)
    result = chat_history_collection.find_one_and_update(
        {
            "user_id": user_object_id,
            "chats.session_id": session_id,
        },
        {
            "$set": {
                "chats.$.title": title,
                "chats.$.updated_at": now,
                "updated_at": now,
            }
        },
        return_document=True,
        projection={"chats.$": 1},
    )

    if not result:
        return None

    chats = result.get("chats", [])
    return chats[0] if chats else None