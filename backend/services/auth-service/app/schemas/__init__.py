"""auth-service schemas package."""
from __future__ import annotations

from .user import (
    GoogleUserInfo,
    LoginResponse,
    User,
    UserPublic,
)

__all__ = [
    "User",
    "UserPublic",
    "LoginResponse",
    "GoogleUserInfo",
]
