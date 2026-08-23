"""
Tạo / giải mã JWT nội bộ của hệ thống.

LƯU Ý: đây là JWT do CHÍNH SERVER của bạn ký (bằng JWT_SECRET_KEY), khác hoàn
toàn với id_token mà Google trả về. Sau khi xác thực Google thành công một
lần ở bước OAuth, mọi request tiếp theo từ frontend sẽ dùng JWT này để chứng
minh danh tính + role, không cần hỏi lại Google nữa.

File này CHỦ Ý không import FastAPI để giữ logic JWT thuần, dễ test / tái sử
dụng. Các dependency dùng cho FastAPI (Depends, Header...) nằm ở dependencies.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from config import JWT_SECRET_KEY, JWT_ALGORITHM, JWT_EXPIRE_MINUTES


class TokenError(Exception):
    """Raise khi token thiếu, sai chữ ký, hoặc hết hạn."""


def create_access_token(user_id: str, role: str, email: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token đã hết hạn, vui lòng đăng nhập lại.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token không hợp lệ.") from exc
