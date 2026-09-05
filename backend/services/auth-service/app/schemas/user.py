"""Pydantic schemas cho User (auth-service)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
    """User document trong MongoDB."""

    id: Optional[str] = Field(default=None, alias="_id")
    google_id: str
    email: EmailStr
    name: str
    picture: Optional[str] = None
    email_verified: bool = False
    role: str = "user"
    created_at: datetime
    updated_at: datetime
    last_login: datetime

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class UserPublic(BaseModel):
    """Thông tin user an toàn để trả về client (không lộ _id nội bộ)."""

    id: str
    google_id: str
    email: EmailStr
    name: str
    picture: Optional[str] = None
    email_verified: bool = False
    role: str = "user"


class LoginResponse(BaseModel):
    """Response trả về khi đăng nhập thành công."""

    user: UserPublic
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool = False


class GoogleUserInfo(BaseModel):
    """Thông tin user lấy từ Google OAuth."""

    sub: str
    email: EmailStr
    name: Optional[str] = None
    picture: Optional[str] = None
    email_verified: bool = False
