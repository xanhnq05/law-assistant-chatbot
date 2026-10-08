"""JWT utilities cho document-service (verify-only).

document-service chỉ verify token do auth-service cấp.
KHÔNG tạo token. Cùng JWT_SECRET_KEY với auth-service / chat-service.

Decoded payload:
    {
        "sub": "mongodb_user_id",
        "role": "user" | "admin",
        "iat": issued_at,
        "exp": expiration_time,
    }
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY, log


def _validate_config() -> None:
    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is missing in environment variables")


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode JWT. Trả None nếu invalid / expired."""
    _validate_config()
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except ExpiredSignatureError:
        log.info("JWT expired")
        return None
    except InvalidTokenError:
        log.info("JWT invalid")
        return None


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode + kiểm tra payload có sub & role."""
    payload = decode_access_token(token)
    if not payload:
        return None
    if not payload.get("sub") or not payload.get("role"):
        return None
    return payload
