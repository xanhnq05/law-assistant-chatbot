"""
Router xử lý Google OAuth + trả về thông tin user hiện tại.

Endpoints:
- GET  /auth/google/login           : bắt đầu Google OAuth flow
- GET  /auth/google/callback        : Google redirect user về đây
                                       -> backend xử lý xong thì redirect
                                          về FRONTEND_URL kèm #token=...
- GET  /auth/me                     : lấy thông tin user hiện tại (cần JWT)
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from schemas import UserPublic
from services.auth_service import handle_google_login
from utils.auth.auth_gg import login_with_google
from utils.auth.jwt import decode_access_token
from utils.user import load_user_public
from core.config import log


router = APIRouter(prefix="/auth", tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


def _frontend_base_url() -> str:
    """Lấy URL gốc của frontend từ env, có fallback an toàn."""
    base = os.getenv("FRONTEND_URL", "http://localhost:5500")
    return base.rstrip("/")


# ============================================================
# GOOGLE LOGIN - REDIRECT
# ============================================================

@router.get("/google/login")
async def google_login(request: Request):
    """
    Bắt đầu Google OAuth flow bằng cách redirect user sang Google.
    """
    return await login_with_google(request)


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@router.get("/google/callback")
async def google_callback(request: Request):
    """
    Google redirect user về đây sau khi xác thực thành công.

    Luồng xử lý:
        Google -> /auth/google/callback (backend)
                  -> tạo JWT
                  -> Redirect về FRONTEND_URL/#token=<jwt>

    Nếu thất bại, redirect về FRONTEND_URL kèm ?login_error=...
    """
    frontend_base = _frontend_base_url()

    try:
        result = await handle_google_login(request)

        # Trả về dict gồm user, access_token, ...
        access_token = result.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate access token",
            )

        # Redirect về frontend kèm token trong hash.
        # Dùng hash (#) thay vì query (?) để browser không gửi token
        # lên server qua log / referer.
        target = f"{frontend_base}/#token={access_token}"
        log.info("OAuth success, redirecting to frontend")
        return RedirectResponse(url=target, status_code=302)

    except HTTPException as exc:
        log.warning("OAuth callback failed: %s", exc.detail)
        params = urlencode({"login_error": str(exc.detail)})
        return RedirectResponse(
            url=f"{frontend_base}/?{params}",
            status_code=302,
        )
    except Exception as exc:
        log.exception("Unexpected OAuth error")
        params = urlencode({"login_error": f"unexpected: {exc}"})
        return RedirectResponse(
            url=f"{frontend_base}/?{params}",
            status_code=302,
        )


# ============================================================
# CURRENT USER
# ============================================================

@router.get("/me", response_model=UserPublic)
async def get_me(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    """
    Lấy thông tin user hiện tại dựa trên JWT trong header Authorization.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing",
        )

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing subject",
        )

    user_public = load_user_public(user_id)
    if user_public is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user_public