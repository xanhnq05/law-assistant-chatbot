"""
Các FastAPI dependency dùng để bảo vệ route: đọc header Authorization,
giải mã JWT, gắn user vào request. Import file này ở bất kỳ router nào
cần yêu cầu đăng nhập.

Ví dụ dùng trong router khác:

    from auth.dependencies import get_current_user, require_role

    @router.get("/chats")
    def list_chats(current_user: dict = Depends(get_current_user)):
        ...

    @router.delete("/admin/xxx")
    def admin_only(current_user: dict = Depends(require_role("admin"))):
        ...
"""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from auth.jwt_handler import decode_access_token, TokenError


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Đọc header `Authorization: Bearer <jwt>`, trả về payload {sub, role, email}."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu token xác thực.",
        )

    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return payload


def require_role(*allowed_roles: str):
    """Trả về một dependency chỉ cho qua nếu user.role nằm trong allowed_roles."""

    def _checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bạn không có quyền truy cập chức năng này.",
            )
        return current_user

    return _checker
