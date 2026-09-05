"""
Các endpoint HTTP cho auth. Router này KHÔNG chứa logic nghiệp vụ (đã nằm ở
service.py / google_oauth.py) — chỉ nhận request, gọi service, trả response.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from config import FRONTEND_URL, log
from auth import google_oauth, service
from auth.dependencies import get_current_user
from auth.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    """Bước 1: đưa user sang trang chọn tài khoản Google."""
    state = google_oauth.generate_state()
    redirect = RedirectResponse(google_oauth.build_authorization_url(state))
    # Lưu state tạm ở cookie httpOnly để đối chiếu tại callback (chống CSRF).
    redirect.set_cookie(
        "oauth_state",
        state,
        max_age=300,
        httponly=True,
        samesite="lax",
    )
    return redirect


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Bước 2: Google redirect về đây sau khi user đồng ý đăng nhập."""
    if error:
        return RedirectResponse(f"{FRONTEND_URL}/?login_error={error}")

    saved_state = request.cookies.get("oauth_state")
    if not code or not state or state != saved_state:
        raise HTTPException(status_code=400, detail="State không khớp — yêu cầu có thể đã bị giả mạo.")

    try:
        _user, jwt_token = await service.authenticate_with_google(code)
    except Exception as exc:  # noqa: BLE001 - log rồi trả về frontend, không lộ chi tiết lỗi
        log.exception("Lỗi xác thực Google: %s", exc)
        return RedirectResponse(f"{FRONTEND_URL}/?login_error=server_error")

    # Trả JWT về frontend qua URL fragment (#...) để không bị log lại ở server truy cập.
    # Frontend đọc window.location.hash, lưu token, rồi xóa khỏi thanh địa chỉ.
    response = RedirectResponse(f"{FRONTEND_URL}/#token={jwt_token}")
    response.delete_cookie("oauth_state")
    return response


@router.get("/me", response_model=UserOut)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserOut:
    """Frontend gọi API này sau khi có JWT để lấy lại thông tin cá nhân + role."""
    user = service.get_user_by_id(current_user["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng.")
    return UserOut(
        id=str(user["_id"]),
        email=user["email"],
        name=user.get("name"),
        picture=user.get("picture"),
        role=user["role"],
    )
