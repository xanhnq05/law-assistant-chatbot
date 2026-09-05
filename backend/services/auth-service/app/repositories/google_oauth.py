"""Google OAuth repository.

Encapsulates Authlib OAuth registration + helpers for /login and
/callback endpoints. Logic ported từ backend_new/utils/auth/auth_gg.py.
"""
from __future__ import annotations

from typing import Any, Dict

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request, status

from app.core.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_REDIRECT_URI,
    GOOGLE_CLIENT_SECRET,
    log,
)


oauth = OAuth()


def _validate_config() -> None:
    missing = []
    if not GOOGLE_CLIENT_ID:
        missing.append("GOOGLE_CLIENT_ID")
    if not GOOGLE_CLIENT_SECRET:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not GOOGLE_CLIENT_REDIRECT_URI:
        missing.append("GOOGLE_REDIRECT_URI")
    if missing:
        raise RuntimeError(
            "Missing Google OAuth environment variables: " + ", ".join(missing)
        )


def register_google_oauth() -> None:
    """Register Google as an OAuth provider (idempotent)."""
    _validate_config()
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/openid-configuration"
        ),
        client_kwargs={"scope": "openid email profile"},
    )


async def login_with_google(request: Request):
    """Redirect user sang trang đăng nhập Google."""
    try:
        return await oauth.google.authorize_redirect(
            request, GOOGLE_CLIENT_REDIRECT_URI
        )
    except Exception as exc:
        log.exception("Failed to start Google OAuth")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to start Google authentication. Error: {exc}",
        ) from exc


async def get_google_user_info(request: Request) -> Dict[str, Any]:
    """Trao đổi code lấy user info, normalize về dict {sub,email,name,email_verified}."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        log.exception("Google token exchange failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google authentication failed. Error: {exc}",
        ) from exc

    user_info = token.get("userinfo")
    if not user_info:
        try:
            resp = await oauth.google.get("userinfo", token=token)
            user_info = resp.json()
        except Exception as exc:
            log.exception("Fetching userinfo from Google failed")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unable to retrieve Google user information. Error: {exc}",
            ) from exc

    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to retrieve Google user information",
        )

    google_id = user_info.get("sub")
    email = user_info.get("email")
    if not google_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google user ID is missing",
        )
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google user email is missing",
        )

    return {
        "sub": google_id,
        "email": email,
        "name": user_info.get("name"),
        "email_verified": user_info.get("email_verified", False),
    }
