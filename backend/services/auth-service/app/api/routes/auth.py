"""Router xử lý Google OAuth + trả về thông tin user hiện tại.

Endpoints:
- GET  /auth/google/login           : bắt đầu Google OAuth flow
- GET  /auth/google/callback        : Google redirect user về đây
- GET  /auth/me                     : lấy thông tin user hiện tại (cần JWT)
- POST /auth/refresh                : đổi refresh token lấy access token mới
- POST /auth/logout                 : thu hồi refresh token + xoá cookie
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import (
    FRONTEND_URL,
    JWT_REFRESH_EXPIRE_DAYS,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    REFRESH_COOKIE_SAMESITE,
    REFRESH_COOKIE_SECURE,
    log,
)
from app.repositories.google_oauth import login_with_google
from app.repositories.jwt_helper import decode_access_token
from app.repositories.user_repository import load_user_public
from app.schemas.session import RefreshTokenRequest, RefreshTokenResponse
from app.schemas.user import UserPublic


router = APIRouter(prefix="/auth", tags=["auth"])

bearer_scheme = HTTPBearer(auto_error=False)


def _frontend_base_url() -> str:
    """URL gốc của frontend (để redirect sau OAuth). Có fallback an toàn."""
    base = FRONTEND_URL or "http://localhost:5500"
    return base.rstrip("/")


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Gắn refresh token vào cookie HttpOnly (JS không đọc được)."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=JWT_REFRESH_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite=REFRESH_COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=REFRESH_COOKIE_SAMESITE,
    )


@router.get("/google/login")
async def google_login(request: Request):
    """Bắt đầu Google OAuth flow bằng cách redirect user sang Google."""
    return await login_with_google(request)


@router.get("/google/callback")
async def google_callback(request: Request):
    """Google redirect user về đây sau khi xác thực thành công.

    Flow:
        Google -> /auth/google/callback (auth-service)
                  -> tạo JWT (access token) + session (refresh token)
                  -> set cookie HttpOnly chứa refresh token
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
        redirect = RedirectResponse(url=target, status_code=302)
        refresh_token = result.get("refresh_token")
        if refresh_token:
            _set_refresh_cookie(redirect, refresh_token)
        return redirect

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
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


def _token_from_request(
    request: Request, payload: Optional[RefreshTokenRequest]
) -> tuple[Optional[str], bool]:
    """Lấy refresh token: ưu tiên body (Postman/mobile), không có thì lấy cookie.

    Returns (token, from_body).
    """
    if payload and payload.refresh_token:
        return payload.refresh_token, True
    return request.cookies.get(REFRESH_COOKIE_NAME), False


@router.post(
    "/refresh",
    response_model=RefreshTokenResponse,
    response_model_exclude_none=True,
)
def refresh(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
):
    """Đổi refresh token lấy access token mới (frontend gọi khi mở lại trang
    hoặc khi access token hết hạn).

    Refresh token được xoay vòng: token cũ mất hiệu lực, token mới được set lại
    vào cookie. Client dùng body thì nhận token mới trong body thay vì cookie.
    """
    from app.services.auth_service import refresh_access_token

    refresh_token, from_body = _token_from_request(request, payload)
    response.headers["Cache-Control"] = "no-store"
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is missing",
        )

    try:
        result = refresh_access_token(refresh_token)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_401_UNAUTHORIZED:
            raise
        # Token chết: xoá cookie để trình duyệt không gửi lại mãi.
        failed = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": exc.detail},
            headers={"Cache-Control": "no-store"},
        )
        if not from_body:
            _clear_refresh_cookie(failed)
        return failed

    if from_body:
        return RefreshTokenResponse(**result)
    _set_refresh_cookie(response, result["refresh_token"])
    return RefreshTokenResponse(
        access_token=result["access_token"], token_type=result["token_type"]
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
):
    """Đăng xuất: thu hồi session trong DB và xoá cookie refresh token.

    Idempotent: gọi khi chưa đăng nhập / token đã thu hồi vẫn trả 200.
    """
    from app.services.auth_service import logout_session

    refresh_token, _ = _token_from_request(request, payload)
    if refresh_token:
        logout_session(refresh_token)
    _clear_refresh_cookie(response)
    return {"detail": "Logged out"}
