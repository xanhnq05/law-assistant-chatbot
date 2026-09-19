"""Pydantic schemas cho Session (auth-service).

Mỗi lần đăng nhập thành công sẽ tạo 1 document trong collection `sessions`.
Document này lưu **hash** của refresh token (KHÔNG lưu token gốc) để lần sau
client có thể dùng refresh token đổi lấy access token mới mà không phải
đăng nhập Google lại.

Luồng dự kiến:
    1. Đăng nhập OK  -> sinh refresh token ngẫu nhiên -> lưu SHA-256(token)
                        vào `sessions` -> gửi token gốc cho client.
    2. Access token hết hạn -> client gửi refresh token
                        -> server hash lại, tìm session theo `refresh_token_hash`
                        -> kiểm tra chưa revoke / chưa hết hạn
                        -> cấp access token mới (và xoay vòng refresh token).
    3. Đăng xuất     -> đặt `is_revoked = True`.

Index MongoDB nên tạo (collection `sessions`):
    - {"refresh_token_hash": 1}  unique   -> tra cứu nhanh khi refresh
    - {"user_id": 1}                      -> liệt kê / thu hồi session của user
    - {"expires_at": 1}  expireAfterSeconds=0  (TTL) -> Mongo tự xoá session hết hạn
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Session(BaseModel):
    """Session document trong MongoDB (1 document = 1 lần đăng nhập / 1 thiết bị)."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Optional[str] = Field(default=None, alias="_id")
    user_id: str                                # = JWT "sub" = str(users._id)
    refresh_token_hash: str                     # SHA-256 hex của refresh token
    user_agent: Optional[str] = None            # trình duyệt / thiết bị
    ip_address: Optional[str] = None
    is_revoked: bool = False                    # True khi đăng xuất / bị thu hồi
    revoked_at: Optional[datetime] = None
    created_at: datetime
    last_used_at: datetime                      # lần gần nhất dùng để refresh
    expires_at: datetime                        # hạn của refresh token (TTL index)

    @property
    def is_expired(self) -> bool:
        """Session đã quá hạn chưa (chấp nhận datetime naive do pymongo trả về)."""
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires_at

    @property
    def is_active(self) -> bool:
        """Session còn dùng được: chưa bị revoke và chưa hết hạn."""
        return not self.is_revoked and not self.is_expired


class SessionPublic(BaseModel):
    """Thông tin session an toàn để trả về client (vd: danh sách thiết bị đăng nhập).

    Không chứa `refresh_token_hash`.
    """

    id: str
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    is_current: bool = False


class RefreshTokenRequest(BaseModel):
    """Body của POST /auth/refresh."""

    refresh_token: str = Field(..., min_length=1)


class RefreshTokenResponse(BaseModel):
    """Response của POST /auth/refresh.

    - Client trình duyệt: refresh token mới được set qua cookie HttpOnly,
      nên `refresh_token` = None (không lộ ra body).
    - Client không dùng cookie (Postman, mobile...): gửi refresh token trong
      body thì nhận refresh token mới trong body.
    """

    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
