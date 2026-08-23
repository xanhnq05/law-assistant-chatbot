"""
Lưu trữ lịch sử chat trong Mongo, tách 2 collection:
  - chats:    mỗi document là 1 "hồ sơ" hội thoại (id, user_id, code, title, thời gian)
  - messages: mỗi document là 1 tin nhắn, tham chiếu tới chat_id

Tách riêng thay vì nhúng messages vào trong chats để tránh document chat
phình to không giới hạn khi hội thoại dài (Mongo giới hạn 16MB / document).
"""
from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId

from mongo_client import get_database

CHATS_COLLECTION = "chats"
MESSAGES_COLLECTION = "messages"


def _chats():
    return get_database()[CHATS_COLLECTION]


def _messages():
    return get_database()[MESSAGES_COLLECTION]


def list_chats(user_id: str) -> list[dict]:
    cursor = _chats().find({"user_id": user_id}).sort("updated_at", -1)
    return [_serialize_chat(c) for c in cursor]


def create_chat(user_id: str, title: str = "Cuộc trò chuyện mới") -> dict:
    count = _chats().count_documents({"user_id": user_id})
    code = f"HS-{count + 1:03d}"
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": user_id,
        "code": code,
        "title": (title or "Cuộc trò chuyện mới")[:120],
        "created_at": now,
        "updated_at": now,
    }
    result = _chats().insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_chat(doc, with_messages=True, messages=[])


def get_chat(user_id: str, chat_id: str) -> dict | None:
    doc = _chats().find_one({"_id": _oid(chat_id), "user_id": user_id})
    if not doc:
        return None
    messages = list_messages(chat_id)
    return _serialize_chat(doc, with_messages=True, messages=messages)


def chat_belongs_to_user(user_id: str, chat_id: str) -> bool:
    return _chats().find_one({"_id": _oid(chat_id), "user_id": user_id}) is not None


def rename_chat_if_default(user_id: str, chat_id: str, new_title: str) -> None:
    chat = _chats().find_one({"_id": _oid(chat_id), "user_id": user_id})
    if chat and chat.get("title") == "Cuộc trò chuyện mới":
        _chats().update_one({"_id": _oid(chat_id)}, {"$set": {"title": new_title[:60]}})


def delete_chat(user_id: str, chat_id: str) -> None:
    _messages().delete_many({"chat_id": _oid(chat_id)})
    _chats().delete_one({"_id": _oid(chat_id), "user_id": user_id})


def add_message(chat_id: str, role: str, content: str) -> None:
    now = datetime.now(timezone.utc)
    _messages().insert_one({"chat_id": _oid(chat_id), "role": role, "content": content, "created_at": now})
    _chats().update_one({"_id": _oid(chat_id)}, {"$set": {"updated_at": now}})


def list_messages(chat_id: str) -> list[dict]:
    cursor = _messages().find({"chat_id": _oid(chat_id)}).sort("created_at", 1)
    return [{"role": m["role"], "content": m["content"]} for m in cursor]


# ---------- helpers ----------
def _oid(value: str) -> ObjectId:
    return ObjectId(value)


def _serialize_chat(doc: dict, with_messages: bool = False, messages: list | None = None) -> dict:
    out = {
        "id": str(doc["_id"]),
        "code": doc["code"],
        "title": doc["title"],
        "updated_at": doc["updated_at"].isoformat() if hasattr(doc["updated_at"], "isoformat") else doc["updated_at"],
    }
    if with_messages:
        out["messages"] = messages or []
    return out
