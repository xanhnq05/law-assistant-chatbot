"""Chat repository.

Consolidated từ backend_new/utils/chat/*.py (7 file) — vì chúng chỉ làm
việc với 1 collection duy nhất (`chat_history`). Trong microservice này
việc tách file nhỏ làm tăng số module không cần thiết.

Schema MongoDB:
    collection: chat_history
    mỗi user có 1 document:
        {
            "_id": ObjectId,
            "user_id": ObjectId,
            "chats": [
                {
                    "session_id": str (uuid4),
                    "title": str,
                    "messages": [{message_id, role, content, sources, created_at}],
                    "created_at": datetime,
                    "updated_at": datetime,
                    "metadata": {"message_count": int},
                }
            ],
            "created_at": datetime,
            "updated_at": datetime,
        }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from bson import ObjectId
from bson.errors import InvalidId

from app.db import get_mongo_client


chat_history_collection = get_mongo_client().get_collection("chat_history")


# ============================================================
# Helpers
# ============================================================
def _to_oid(user_id: Any) -> Optional[ObjectId]:
    if not user_id:
        return None
    if isinstance(user_id, ObjectId):
        return user_id
    try:
        return ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None


# ============================================================
# OWNERSHIP
# ============================================================
def check_chat_owner(user_id: Any, session_id: str) -> bool:
    if not user_id or not session_id:
        return False
    oid = _to_oid(user_id)
    if oid is None:
        return False
    document = chat_history_collection.find_one(
        {"user_id": oid, "chats.session_id": session_id},
        {"_id": 1},
    )
    return document is not None


# ============================================================
# ENSURE CHAT HISTORY DOCUMENT
# ============================================================
def ensure_chat_history(user_id: Any) -> Optional[Dict[str, Any]]:
    """Đảm bảo user có 1 document chat_history, trả về document đó."""
    oid = _to_oid(user_id)
    if oid is None:
        return None
    now = datetime.now(timezone.utc)
    chat_history_collection.update_one(
        {"user_id": oid},
        {
            "$setOnInsert": {
                "user_id": oid,
                "chats": [],
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return chat_history_collection.find_one({"user_id": oid})


# ============================================================
# CREATE
# ============================================================
def create_chat(user_id: Any, title: str = "Cuộc trò chuyện mới") -> Dict[str, Any]:
    """Tạo chat session mới (kèm upsert chat_history document)."""
    oid = _to_oid(user_id)
    if oid is None:
        raise ValueError("Invalid user_id")

    now = datetime.now(timezone.utc)
    # Đảm bảo document tồn tại
    chat_history_collection.update_one(
        {"user_id": oid},
        {
            "$setOnInsert": {
                "user_id": oid,
                "chats": [],
                "created_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )
    new_session = {
        "session_id": str(uuid4()),
        "title": title,
        "messages": [],
        "created_at": now,
        "updated_at": now,
        "metadata": {"message_count": 0},
    }
    chat_history_collection.update_one(
        {"user_id": oid},
        {"$push": {"chats": new_session}, "$set": {"updated_at": now}},
    )
    return new_session


# ============================================================
# READ
# ============================================================
def get_chat(user_id: Any, session_id: str) -> Optional[Dict[str, Any]]:
    oid = _to_oid(user_id)
    if oid is None or not session_id:
        return None
    document = chat_history_collection.find_one(
        {"user_id": oid, "chats.session_id": session_id},
        {"chats.$": 1},
    )
    if not document:
        return None
    chats = document.get("chats", [])
    return chats[0] if chats else None


def list_user_chats(user_id: Any) -> List[Dict[str, Any]]:
    """Trả về danh sách session của user (rỗng nếu chưa có history)."""
    oid = _to_oid(user_id)
    if oid is None:
        return []
    document = chat_history_collection.find_one({"user_id": oid})
    if not document:
        return []
    return document.get("chats", [])


# ============================================================
# UPDATE
# ============================================================
def update_chat(user_id: Any, session_id: str, title: str) -> Optional[Dict[str, Any]]:
    oid = _to_oid(user_id)
    if oid is None or not session_id or not title:
        return None
    now = datetime.now(timezone.utc)
    result = chat_history_collection.find_one_and_update(
        {"user_id": oid, "chats.session_id": session_id},
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


# ============================================================
# DELETE
# ============================================================
def delete_chat(user_id: Any, session_id: str) -> bool:
    oid = _to_oid(user_id)
    if oid is None or not session_id:
        return False
    now = datetime.now(timezone.utc)
    result = chat_history_collection.update_one(
        {"user_id": oid},
        {"$pull": {"chats": {"session_id": session_id}}, "$set": {"updated_at": now}},
    )
    return result.modified_count > 0


# ============================================================
# ADD MESSAGE
# ============================================================
def add_message(
    user_id: Any,
    session_id: str,
    role: str,
    content: str,
    sources: Optional[List[dict]] = None,
) -> Optional[Dict[str, Any]]:
    """Push message vào session và trả về message vừa tạo."""
    if not session_id or not content:
        return None
    if role not in ("user", "assistant", "system"):
        return None
    oid = _to_oid(user_id)
    if oid is None:
        return None

    message = {
        "message_id": str(uuid4()),
        "role": role,
        "content": content,
        "sources": sources or [],
        "created_at": datetime.now(timezone.utc),
    }
    now = datetime.now(timezone.utc)
    result = chat_history_collection.find_one_and_update(
        {"user_id": oid, "chats.session_id": session_id},
        {
            "$push": {"chats.$.messages": message},
            "$inc": {"chats.$.metadata.message_count": 1},
            "$set": {"chats.$.updated_at": now, "updated_at": now},
        },
        return_document=True,
        projection={"chats.$": 1},
    )
    if not result:
        return None
    chats = result.get("chats", [])
    if not chats:
        return None
    messages = chats[0].get("messages", [])
    return messages[-1] if messages else message
