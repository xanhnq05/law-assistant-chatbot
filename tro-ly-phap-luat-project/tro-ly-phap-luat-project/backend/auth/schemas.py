"""
Các schema (Pydantic) dùng trong luồng auth.
Tách riêng để router/service import mà không phải nhìn logic xử lý.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GoogleUserInfo(BaseModel):
    """Dữ liệu thô lấy từ Google userinfo endpoint sau khi đổi code lấy access_token."""

    sub: str  # định danh tài khoản Google, không đổi -> dùng làm user id nội bộ
    email: str
    email_verified: Optional[bool] = None
    name: Optional[str] = None
    picture: Optional[str] = None


class TokenPayload(BaseModel):
    """Payload giải mã được từ JWT nội bộ (không phải token của Google)."""

    sub: str  # user id (= Google sub)
    role: str
    email: Optional[str] = None
    exp: Optional[int] = None


class UserOut(BaseModel):
    """Hình dạng user trả về cho frontend, không lộ field nội bộ."""

    id: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    role: str
