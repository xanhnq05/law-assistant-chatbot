"""User repository.

Consolidated from backend_new/utils/auth/{check_exist,create_user,
update_last_login}.py + backend_new/utils/user/load_user.py.

Responsibilities:
- Find user by google_id / email / _id
- Create a new user document
- Update last_login / updated_at
- Load user / user-public dict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from app.db import get_mongo_client


# Singleton collection accessor — connection mở lazily.
users_collection = get_mongo_client().get_collection("users")


# ============================================================
# FIND
# ============================================================
def find_user_by_google_id(google_id: str) -> Optional[Dict[str, Any]]:
    if not google_id:
        return None
    return users_collection.find_one({"google_id": google_id})


def find_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    normalized = email.strip().lower()
    if not normalized:
        return None
    return users_collection.find_one({"email": normalized})


def find_user_by_id(user_id: Union[str, ObjectId]) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    try:
        oid = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    return users_collection.find_one({"_id": oid})


def check_user_exists(google_id: str) -> bool:
    return find_user_by_google_id(google_id) is not None


# ============================================================
# CREATE
# ============================================================
def create_user(google_user: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new user from authenticated Google user info.

    Required keys in google_user: sub, email.
    Optional: name, picture, email_verified.
    """
    if not google_user:
        raise ValueError("Google user information is required")

    google_id = google_user.get("sub")
    email = google_user.get("email")
    name = google_user.get("name")

    if not google_id:
        raise ValueError("Google user ID (sub) is required")
    if not email:
        raise ValueError("Google user email is required")

    google_id = str(google_id).strip()
    email = str(email).strip().lower()
    if not google_id:
        raise ValueError("Google user ID cannot be empty")
    if not email:
        raise ValueError("Google user email cannot be empty")
    if name:
        name = str(name).strip()
    else:
        # Fallback khi Google không trả name.
        name = email

    now = datetime.now(timezone.utc)
    document = {
        "google_id": google_id,
        "email": email,
        "name": name,
        "email_verified": bool(google_user.get("email_verified", False)),
        "role": "user",
        "created_at": now,
        "updated_at": now,
        "last_login": now,
    }
    result = users_collection.insert_one(document)
    document["_id"] = result.inserted_id
    return document


# ============================================================
# UPDATE
# ============================================================
def update_last_login(user_id: Union[str, ObjectId]) -> Optional[Dict[str, Any]]:
    if not user_id:
        return None
    try:
        oid = user_id if isinstance(user_id, ObjectId) else ObjectId(str(user_id))
    except (InvalidId, TypeError):
        return None
    now = datetime.now(timezone.utc)
    return users_collection.find_one_and_update(
        {"_id": oid},
        {"$set": {"last_login": now, "updated_at": now}},
        return_document=ReturnDocument.AFTER,
    )


# ============================================================
# LOAD (read-side helpers, dùng cho router /me)
# ============================================================
def load_user(user_id: Any) -> Optional[Dict[str, Any]]:
    """Lấy user document theo _id. Trả về None nếu invalid / not found."""
    return find_user_by_id(user_id)


def load_user_public(user_id: Any) -> Optional[Dict[str, Any]]:
    """Lấy thông tin user ở dạng an toàn để trả về client."""
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
