"""Session repository (refresh token).

Responsibilities:
- Sinh refresh token ngẫu nhiên + hash SHA-256 để lưu DB
- Tạo session khi đăng nhập
- Xoay vòng (rotate) refresh token mỗi lần refresh
- Thu hồi (revoke) session khi đăng xuất
- Tạo index cho collection `sessions`

Refresh token gốc chỉ tồn tại ở phía client. DB chỉ giữ hash, nên dù lộ DB
kẻ xấu cũng không dùng được token. Token là chuỗi ngẫu nhiên 384-bit nên
SHA-256 là đủ (không cần bcrypt như mật khẩu).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from pymongo import ASCENDING, ReturnDocument

from app.core.config import JWT_REFRESH_EXPIRE_DAYS
from app.db import get_mongo_client


# Singleton collection accessor — connection mở lazily.
sessions_collection = get_mongo_client().get_collection("sessions")

# Giới hạn độ dài User-Agent lưu DB (header có thể rất dài / bị giả mạo).
_MAX_USER_AGENT_LEN = 512


# ============================================================
# TOKEN HELPERS
# ============================================================
def generate_refresh_token() -> str:
    """Sinh refresh token ngẫu nhiên an toàn (48 bytes -> ~64 ký tự URL-safe)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex của refresh token — đây là giá trị lưu trong DB."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expiry_from(now: datetime) -> datetime:
    return now + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)


# ============================================================
# INDEXES
# ============================================================
def ensure_indexes() -> None:
    """Tạo index cho collection `sessions` (idempotent, gọi lúc startup)."""
    # Tra cứu nhanh khi refresh + đảm bảo không trùng hash.
    sessions_collection.create_index(
        [("refresh_token_hash", ASCENDING)],
        unique=True,
        name="uq_refresh_token_hash",
    )
    # Liệt kê / thu hồi session theo user.
    sessions_collection.create_index([("user_id", ASCENDING)], name="ix_user_id")
    # TTL: MongoDB tự xoá session khi tới expires_at.
    sessions_collection.create_index(
        [("expires_at", ASCENDING)],
        expireAfterSeconds=0,
        name="ttl_expires_at",
    )


# ============================================================
# CREATE
# ============================================================
def create_session(
    user_id: Any,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Tạo session mới khi user đăng nhập.

    Returns:
        (refresh_token_goc, session_document). Token gốc chỉ trả về ở đây,
        không thể lấy lại từ DB — hãy gửi ngay cho client.
    """
    if not user_id:
        raise ValueError("user_id is required")
    user_id = str(user_id).strip()
    if not user_id:
        raise ValueError("user_id cannot be empty")

    refresh_token = generate_refresh_token()
    now = datetime.now(timezone.utc)
    document = {
        "user_id": user_id,
        "refresh_token_hash": hash_refresh_token(refresh_token),
        "user_agent": user_agent[:_MAX_USER_AGENT_LEN] if user_agent else None,
        "ip_address": ip_address or None,
        "is_revoked": False,
        "revoked_at": None,
        "created_at": now,
        "last_used_at": now,
        "expires_at": _expiry_from(now),
    }
    result = sessions_collection.insert_one(document)
    document["_id"] = result.inserted_id
    return refresh_token, document


# ============================================================
# ROTATE
# ============================================================
def rotate_session(refresh_token: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Kiểm tra refresh token và đổi sang refresh token mới (rotation).

    Dùng một thao tác `find_one_and_update` duy nhất nên atomic: nếu 2 request
    cùng gửi 1 token, chỉ 1 request thành công, request còn lại nhận None.
    Token cũ mất hiệu lực ngay sau khi xoay. Hạn dùng được gia hạn thêm
    JWT_REFRESH_EXPIRE_DAYS ngày kể từ lần refresh này (sliding expiration).

    Returns:
        (refresh_token_moi, session_document_sau_cap_nhat), hoặc None nếu token
        không tồn tại / đã bị thu hồi / đã hết hạn.
    """
    if not refresh_token:
        return None

    now = datetime.now(timezone.utc)
    new_token = generate_refresh_token()
    document = sessions_collection.find_one_and_update(
        {
            "refresh_token_hash": hash_refresh_token(refresh_token),
            "is_revoked": False,
            "expires_at": {"$gt": now},
        },
        {
            "$set": {
                "refresh_token_hash": hash_refresh_token(new_token),
                "last_used_at": now,
                "expires_at": _expiry_from(now),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        return None
    return new_token, document


# ============================================================
# REVOKE
# ============================================================
def revoke_session(refresh_token: str) -> bool:
    """Thu hồi session ứng với refresh token (đăng xuất). True nếu có thay đổi."""
    if not refresh_token:
        return False
    result = sessions_collection.update_one(
        {
            "refresh_token_hash": hash_refresh_token(refresh_token),
            "is_revoked": False,
        },
        {"$set": {"is_revoked": True, "revoked_at": datetime.now(timezone.utc)}},
    )
    return result.modified_count > 0
