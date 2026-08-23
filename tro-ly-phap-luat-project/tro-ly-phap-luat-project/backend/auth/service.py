"""
Điều phối toàn bộ luồng đăng nhập:
  google_oauth (nói chuyện với Google) + Mongo (users collection) + jwt_handler (phát token)

Đây là nơi xử lý đúng 2 trường hợp bạn mô tả:
  - TH1: user chưa từng đăng nhập -> tạo document mới trong `users`, role mặc định "user"
  - TH2: user đã tồn tại (tìm theo _id = Google sub) -> chỉ cập nhật thông tin mới nhất, không tạo trùng
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import log
from mongo_client import get_database
from auth import google_oauth
from auth.jwt_handler import create_access_token

USERS_COLLECTION = "users"


def _users():
    return get_database()[USERS_COLLECTION]


def get_or_create_user(profile: dict) -> dict[str, Any]:
    """profile: dict thô từ Google userinfo (sub, email, name, picture, ...)."""
    users = _users()
    google_id = profile["sub"]
    now = datetime.now(timezone.utc)

    existing = users.find_one({"_id": google_id})

    if existing:
        # TH2: đã có tài khoản -> chỉ đồng bộ lại thông tin hiển thị mới nhất từ Google
        update_fields = {
            "email": profile.get("email"),
            "name": profile.get("name"),
            "picture": profile.get("picture"),
            "updated_at": now,
        }
        users.update_one({"_id": google_id}, {"$set": update_fields})
        existing.update(update_fields)
        log.info("Đăng nhập (tài khoản đã tồn tại): %s", profile.get("email"))
        return existing

    # TH1: chưa có -> tạo mới, role mặc định "user"
    new_user = {
        "_id": google_id,
        "email": profile.get("email"),
        "name": profile.get("name"),
        "picture": profile.get("picture"),
        "role": "user",
        "created_at": now,
        "updated_at": now,
    }
    users.insert_one(new_user)
    log.info("Tạo tài khoản mới cho: %s", profile.get("email"))
    return new_user


async def authenticate_with_google(code: str) -> tuple[dict, str]:
    """Đổi authorization code lấy user + JWT nội bộ.
    Trả về (user_document, jwt_token)."""
    tokens = await google_oauth.exchange_code_for_tokens(code)
    access_token = tokens.get("access_token")
    if not access_token:
        raise ValueError("Google không trả về access_token — code có thể đã bị dùng hoặc hết hạn.")

    profile = await google_oauth.fetch_google_userinfo(access_token)
    user = get_or_create_user(profile)

    jwt_token = create_access_token(
        user_id=str(user["_id"]),
        role=user["role"],
        email=user.get("email"),
    )
    return user, jwt_token


def get_user_by_id(user_id: str) -> dict | None:
    return _users().find_one({"_id": user_id})
