"""Router xử lý Google OAuth + trả về thông tin user hiện tại.

Endpoints:
- GET  /auth/google/login           : bắt đầu Google OAuth flow
- GET  /auth/google/callback        : Google redirect user về đây
- GET  /auth/me                     : lấy thông tin user hiện tại (cần JWT)
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import FRONTEND_URL, log
from app.repositories.google_oauth import login_with_google
from app.repositories.jwt_helper import decode_access_token
from app.repositories.user_repository import load_user_public
from app.schemas import UserPublic


router = APIRouter(prefix="/auth", tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


def _frontend_base_url() -> str:
    """URL gốc của frontend (để redirect sau OAuth). Có fallback an toàn."""
    base = FRONTEND_URL or "http://localhost:5500"
    return base.rstrip("/")


@router.get("/google/login")
async def google_login(request: Request):
    """Bắt đầu Google OAuth flow bằng cách redirect user sang Google."""
    return await login_with_google(request)


@router.get("/google/callback")
async def google_callback(request: Request):
    """Google redirect user về đây sau khi xác thực thành công.

    Flow:
        Google -> /auth/google/callback (auth-service)
                  -> tạo JWT
                  -> Redirect về FRONTEND_URL/#token=<jwt>
    """
    from app.services.auth_service import handle_google_login

    frontend_base = _frontend_base_url()
    try:
        result = await handle_google_login(request)
        access_token = result.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate access token",
            )
        target = f"{frontend_base}/#token={access_token}"
        log.info("OAuth success, redirecting to frontend")
        return RedirectResponse(url=target, status_code=302)

    except HTTPException as exc:
        log.warning("OAuth callback failed: %s", exc.detail)
        params = urlencode({"login_error": str(exc.detail)})
        return RedirectResponse(
            url=f"{frontend_base}/?{params}", status_code=302
        )
    except Exception as exc:
        log.exception("Unexpected OAuth error")
        params = urlencode({"login_error": f"unexpected: {exc}"})
        return RedirectResponse(
            url=f"{frontend_base}/?{params}", status_code=302
        )


@router.get("/me", response_model=UserPublic)
async def get_me(
    credentials: HTTPAuthorizationCredentials | None = None,
):
    """Lấy thông tin user hiện tại dựa trên JWT trong header Authorization."""
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
