"""
Utility load lịch sử chat của user.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


def load_history(
    user_id: Any
) -> List[Dict[str, Any]]:
    """
    Lấy danh sách các chat session của user.

    Args:
        user_id: MongoDB ObjectId hoặc string.

    Returns:
        List[Dict]: danh sách session (rỗng nếu user chưa có history).
    """
    if not user_id:
        return []

    try:
        user_object_id = (
            user_id
            if isinstance(user_id, ObjectId)
            else ObjectId(str(user_id))
        )
    except (InvalidId, TypeError):
        return []

    document: Optional[Dict[str, Any]] = chat_history_collection.find_one(
        {"user_id": user_object_id}
    )

    if not document:
        return []

    return document.get("chats", [])


def load_history_document(
    user_id: Any
) -> Optional[Dict[str, Any]]:
    """Trả về toàn bộ document chat_history của user (hoặc None)."""
    if not user_id:
        return None

    try:
        user_object_id = (
            user_id
            if isinstance(user_id, ObjectId)
            else ObjectId(str(user_id))
        )
    except (InvalidId, TypeError):
        return None

    return chat_history_collection.find_one({"user_id": user_object_id})