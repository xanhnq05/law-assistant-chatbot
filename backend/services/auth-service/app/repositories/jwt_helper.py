"""JWT utilities (auth-service).

Decoded payload structure:
    {
        "sub": "mongodb_user_id",
        "role": "user",
        "iat": issued_at,
        "exp": expiration_time,
    }
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.core.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET_KEY, log


def _validate_config() -> None:
    if not JWT_SECRET_KEY:
        raise RuntimeError("JWT_SECRET_KEY is missing in environment variables")


def create_access_token(user_id: str, role: str) -> str:
    """Tạo JWT access token."""
    _validate_config()
    if not user_id:
        raise ValueError("user_id is required")
    if not role:
        raise ValueError("role is required")

    user_id = str(user_id).strip()
    role = str(role).strip().lower()
    if not user_id:
        raise ValueError("user_id cannot be empty")
    if not role:
        raise ValueError("role cannot be empty")

    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "iat": now, "exp": expire}
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


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
