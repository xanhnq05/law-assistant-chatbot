"""
Utility load thông tin user từ MongoDB (an toàn để trả về client).

Loại bỏ các field nội bộ nếu cần.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


users_collection = (
    get_mongo_client()
    .get_collection("users")
)


def load_user(
    user_id: Any
) -> Optional[Dict[str, Any]]:
    """
    Lấy document user theo MongoDB _id.

    Args:
        user_id: MongoDB ObjectId hoặc string.

    Returns:
        Dict user hoặc None nếu không tìm thấy / input không hợp lệ.
    """
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

    return users_collection.find_one({"_id": user_object_id})


def load_user_public(
    user_id: Any
) -> Optional[Dict[str, Any]]:
    """
    Lấy thông tin user ở dạng an toàn để trả về client.

    Trả về dict gồm các key an toàn (id, google_id, email, name,
    picture, email_verified, role).
    """
    user = load_user(user_id)
    if not user:
        return None

    return {
        "id": str(user["_id"]),
        "google_id": user.get("google_id"),
        "email": user.get("email"),
        "name": user.get("name"),
        "picture": user.get("picture"),
        "email_verified": user.get("email_verified", False),
        "role": user.get("role", "user"),
    }