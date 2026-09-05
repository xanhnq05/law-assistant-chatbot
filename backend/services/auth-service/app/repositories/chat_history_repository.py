"""Chat-history repository (auth-service side).

auth-service chỉ dùng để tạo document chat_history rỗng cho user mới
(sau khi đăng ký Google lần đầu). Mọi thao tác CRUD chat session
thực sự sẽ do chat-service đảm nhận.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.db import get_mongo_client


chat_history_collection = get_mongo_client().get_collection("chat_history")


def _to_oid(user_id: Any) -> Optional[ObjectId]:
    if not user_id:
        return None
    if isinstance(user_id, ObjectId):
        return user_id
    try:
        return ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None


def create_initial_chat_history(user_id: Any) -> Optional[Dict[str, Any]]:
    """Tạo document chat_history rỗng cho user mới."""
    oid = _to_oid(user_id)
    if oid is None:
        raise ValueError("user_id is required and must be a valid ObjectId")

    now = datetime.now(timezone.utc)
    document = {
        "user_id": oid,
        "chats": [],
        "created_at": now,
        "updated_at": now,
    }
    result = chat_history_collection.insert_one(document)
    document["_id"] = result.inserted_id
    return document
