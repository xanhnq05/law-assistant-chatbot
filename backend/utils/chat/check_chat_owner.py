"""
Utility kiểm tra một chat session có thuộc về user hay không.

Dùng để bảo vệ quyền sở hữu khi user thao tác với session.
"""
from __future__ import annotations

from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


def check_chat_owner(
    user_id: Any,
    session_id: str
) -> bool:
    """
    Kiểm tra session có thuộc user hay không.

    Args:
        user_id: MongoDB ObjectId hoặc string.
        session_id: UUID của session.

    Returns:
        True nếu session tồn tại và thuộc về user.
        False trong mọi trường hợp khác (kể cả input không hợp lệ).
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

    document = chat_history_collection.find_one(
        {
            "user_id": user_object_id,
            "chats.session_id": session_id,
        },
        {"_id": 1},
    )

    return document is not None