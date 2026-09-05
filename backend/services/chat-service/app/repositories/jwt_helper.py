"""JWT helper cho chat-service.

Chat-service KHÔNG tự tạo token, chỉ verify token do auth-service cấp.
Quan trọng: cả auth-service & chat-service PHẢI dùng chung
JWT_SECRET_KEY (lấy từ backend/.env) để verify chéo được.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.core.config import JWT_ALGORITHM, JWT_SECRET_KEY, log


def _validate_config() -> None:
    if not JWT_SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is missing — phải dùng chung secret với auth-service."
        )


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
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
