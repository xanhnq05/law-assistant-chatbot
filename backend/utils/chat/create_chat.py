"""
Utility tạo chat session mới cho một user.

Cấu trúc dữ liệu trong MongoDB:
- Collection: chat_history
- Mỗi user có 1 document, bên trong là mảng `chats`.
- Mỗi phần tử trong `chats` là một session gồm session_id, title,
  messages, created_at, updated_at, metadata.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


# ============================================================
# GET CHAT HISTORY COLLECTION
# ============================================================

chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


# ============================================================
# CREATE NEW CHAT SESSION
# ============================================================

def create_chat(
    user_id: Any,
    title: str = "Cuộc trò chuyện mới"
) -> Dict[str, Any]:
    """
    Tạo một chat session mới cho user và push vào mảng `chats`.

    Nếu user chưa có document chat_history thì tạo document rỗng trước,
    sau đó push session mới vào.

    Args:
        user_id: MongoDB ObjectId (hoặc string) của User.
        title: Tiêu đề session.

    Returns:
        Dict[str, Any]: document chat session vừa tạo.

    Raises:
        ValueError: Nếu user_id không hợp lệ.
    """
    # =================================================
    # 1. VALIDATE & CONVERT USER ID
    # =================================================
    if not user_id:
        raise ValueError("user_id is required")

    try:
        if isinstance(user_id, ObjectId):
            user_object_id = user_id
        else:
            user_object_id = ObjectId(str(user_id))
    except (InvalidId, TypeError) as exc:
        raise ValueError("Invalid user_id") from exc

    # =================================================
    # 2. ENSURE CHAT HISTORY DOCUMENT EXISTS
    # =================================================
    now = datetime.now(timezone.utc)

    chat_history_collection.update_one(
        {"user_id": user_object_id},
        {
            "$setOnInsert": {
                "user_id": user_object_id,
                "chats": [],
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )

    # =================================================
    # 3. BUILD NEW CHAT SESSION
    # =================================================
    session_id = str(uuid4())
    new_session: Dict[str, Any] = {
        "session_id": session_id,
        "title": title,
        "messages": [],
        "created_at": now,
        "updated_at": now,
        "metadata": {"message_count": 0},
    }

    # =================================================
    # 4. PUSH SESSION INTO CHAT HISTORY
    # =================================================
    chat_history_collection.update_one(
        {"user_id": user_object_id},
        {
            "$push": {"chats": new_session},
            "$set": {"updated_at": now},
        },
    )

    return new_session


# ============================================================
# ENSURE CHAT HISTORY EXISTS (helper)
# ============================================================

def ensure_chat_history(user_id: Any) -> Optional[Dict[str, Any]]:
    """Đảm bảo user có 1 document chat_history, trả về document đó."""
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

    now = datetime.now(timezone.utc)
    chat_history_collection.update_one(
        {"user_id": user_object_id},
        {
            "$setOnInsert": {
                "user_id": user_object_id,
                "chats": [],
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )

    return chat_history_collection.find_one({"user_id": user_object_id})