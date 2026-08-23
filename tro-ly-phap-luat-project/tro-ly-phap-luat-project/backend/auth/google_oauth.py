"""
Giao tiếp trực tiếp với Google OAuth 2.0 (Authorization Code Flow).

Flow:
  1. build_authorization_url()  -> URL để redirect user sang trang chọn tài khoản Google
  2. Google redirect user về GOOGLE_REDIRECT_URI kèm ?code=...&state=...
  3. exchange_code_for_tokens(code) -> đổi code lấy access_token (dùng client_secret,
     nên bước này PHẢI chạy ở server, không phải ở trình duyệt)
  4. fetch_google_userinfo(access_token) -> lấy sub/email/name/picture thật từ Google

Không cần tự verify chữ ký id_token ở đây vì bước 4 đã hỏi thẳng Google
(userinfo endpoint) bằng access_token vừa đổi được — dữ liệu trả về đáng tin
cậy tương đương việc verify id_token.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


def generate_state() -> str:
    """Chuỗi ngẫu nhiên chống CSRF, đối chiếu lại ở bước callback."""
    return secrets.token_urlsafe(24)


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": GOOGLE_CLIENT_ID,          # public, được nhúng thẳng vào URL
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Đổi authorization code lấy access_token. Đây là bước BẮT BUỘC gửi
    kèm client_secret nên chỉ được thực hiện từ backend."""
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,  # private, tuyệt đối không gửi ra frontend
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    resp.raise_for_status()
    return resp.json()  # {"access_token": ..., "id_token": ..., "expires_in": ...}


async def fetch_google_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    resp.raise_for_status()
    return resp.json()  # {"sub": ..., "email": ..., "name": ..., "picture": ...}
