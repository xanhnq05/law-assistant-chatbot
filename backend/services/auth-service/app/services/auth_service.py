"""Authentication orchestrator.

Quy trình xử lý Google login (tách bạch với HTTP & DB):
    handle_google_login(request)
        1. Lấy Google user info từ request (Google OAuth repo)
        2. Tìm user trong MongoDB theo google_id
        3. Nếu chưa có: tạo user + tạo chat_history rỗng
        4. Nếu có rồi: cập nhật last_login
        5. Tạo JWT
        6. Trả về LoginResponse

Không truy cập trực tiếp MongoDB / Google OAuth / JWT — tất cả qua
repositories layer.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException, Request, status

from app.core.config import log
from app.repositories.google_oauth import get_google_user_info
from app.repositories.jwt_helper import create_access_token
from app.repositories.user_repository import (
    create_user,
    find_user_by_google_id,
    load_user,
    update_last_login,
)
from app.repositories.chat_history_repository import create_initial_chat_history


async def handle_google_login(request: Request) -> Dict[str, Any]:
    """Xử lý toàn bộ luồng Google login → trả dict {user, access_token, ...}."""
    try:
        # 1. Google user info
        google_user = await get_google_user_info(request)
        if not google_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to retrieve Google user information",
            )

        google_id = google_user.get("sub")
        if not google_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google user ID is missing",
            )

        # 2. Find existing user
        user = find_user_by_google_id(google_id)
        is_new_user = False

        # 3. Create if missing
        if user is None:
            user = create_user(google_user)
            # Khởi tạo document chat_history rỗng cho user mới.
            try:
                create_initial_chat_history(user["_id"])
            except Exception as exc:
                log.warning("Không tạo được chat_history ban đầu: %s", exc)
            is_new_user = True
        else:
            updated = update_last_login(user["_id"])
            if updated is not None:
                user = updated

        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to process user information",
            )

        user_id = user.get("_id")
        role = user.get("role", "user")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User ID is missing",
            )

        # 4. JWT
        access_token = create_access_token(user_id=str(user_id), role=role)

        # 5. Safe response
        return {
            "user": {
                "id": str(user_id),
                "google_id": user.get("google_id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "picture": user.get("picture"),
                "email_verified": user.get("email_verified", False),
                "role": role,
            },
            "access_token": access_token,
            "token_type": "bearer",
            "is_new_user": is_new_user,
        }

    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Google login failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Google login failed. Error: {exc}",
        ) from exc


async def get_current_user(request: Request) -> str:
    """Trích xuất user_id từ JWT trong Authorization header.

    Raises 401 nếu thiếu / sai token, 404 nếu user không tồn tại.
    """
    from app.repositories.jwt_helper import decode_access_token

    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(parts[1])
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing subject",
        )

    if load_user(user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user_id
