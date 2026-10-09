"""User repository cho document-service (read-only).

Dùng để verify JWT payload.sub → load role từ Mongo `users` collection.
Không tạo user mới (auth-service làm việc đó).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union

from bson import ObjectId
from bson.errors import InvalidId

from app.db import get_mongo_client


users_collection = get_mongo_client().get_collection("users")


def find_user_by_id(user_id: Union[str, ObjectId]) -> Optional[Dict[str, Any]]:
    """Lookup user theo Mongo `_id`. Trả None nếu invalid / not found."""
    if not user_id:
        return None
    try:
        oid = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    return users_collection.find_one({"_id": oid})


def load_user_role(user_id: Union[str, ObjectId]) -> Optional[str]:
    """Lấy role của user (lowercase). Trả None nếu user không tồn tại."""
    user = find_user_by_id(user_id)
    if not user:
        return None
    return str(user.get("role", "user")).strip().lower()


def load_user_public(user_id: Union[str, ObjectId]) -> Optional[Dict[str, Any]]:
    """Thông tin user an toàn để trả về client."""
    user = find_user_by_id(user_id)
    if not user:
        return None
    return {
        "id": str(user["_id"]),
        "email": user.get("email"),
        "name": user.get("name"),
        "picture": user.get("picture"),
        "role": user.get("role", "user"),
    }
