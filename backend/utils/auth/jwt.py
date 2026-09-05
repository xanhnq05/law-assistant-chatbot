"""
JWT Authentication Utility.

Responsibilities:
- Create JWT access token
- Decode JWT access token
- Verify JWT access token

JWT payload structure:

{
    "sub": "mongodb_user_id",
    "role": "user",
    "iat": issued_at,
    "exp": expiration_time
}

This file does NOT:
- Access MongoDB
- Handle Google OAuth
- Create users
- Update users
- Handle passwords
"""

import os

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt

from dotenv import load_dotenv

from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidTokenError
)


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY"
)

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256"
)

JWT_EXPIRE_MINUTES = int(
    os.getenv(
        "JWT_EXPIRE_MINUTES",
        "60"
    )
)


# ============================================================
# VALIDATE JWT CONFIGURATION
# ============================================================

def validate_jwt_config() -> None:
    """
    Kiểm tra JWT configuration.

    Raises:
        RuntimeError:
            Nếu JWT_SECRET_KEY chưa được cấu hình.
    """

    if not JWT_SECRET_KEY:

        raise RuntimeError(
            "JWT_SECRET_KEY is missing in environment variables"
        )


# ============================================================
# CREATE ACCESS TOKEN
# ============================================================

def create_access_token(
    user_id: str,
    role: str
) -> str:
    """
    Tạo JWT Access Token.

    Args:
        user_id:
            MongoDB User _id.

        role:
            Role của User.
            Ví dụ:
            - user
            - admin

    Returns:
        JWT access token dạng string.

    JWT Payload:

    {
        "sub": "user_id",
        "role": "user",
        "iat": ...,
        "exp": ...
    }
    """

    validate_jwt_config()


    # =========================================================
    # VALIDATE INPUT
    # =========================================================

    if not user_id:

        raise ValueError(
            "user_id is required"
        )

    if not role:

        raise ValueError(
            "role is required"
        )


    # =========================================================
    # NORMALIZE DATA
    # =========================================================

    user_id = str(
        user_id
    ).strip()

    role = str(
        role
    ).strip().lower()


    if not user_id:

        raise ValueError(
            "user_id cannot be empty"
        )

    if not role:

        raise ValueError(
            "role cannot be empty"
        )


    # =========================================================
    # CREATE TIMESTAMPS
    # =========================================================

    now = datetime.now(
        timezone.utc
    )

    expire = now + timedelta(
        minutes=JWT_EXPIRE_MINUTES
    )


    # =========================================================
    # CREATE PAYLOAD
    # =========================================================

    payload = {

        # Subject = MongoDB User ID
        "sub": user_id,

        # User authorization role
        "role": role,

        # Token issued time
        "iat": now,

        # Token expiration time
        "exp": expire
    }


    # =========================================================
    # ENCODE JWT
    # =========================================================

    access_token = jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )


    return access_token


# ============================================================
# DECODE ACCESS TOKEN
# ============================================================

def decode_access_token(
    token: str
) -> Optional[Dict[str, Any]]:
    """
    Decode JWT Access Token.

    Khi decode, PyJWT sẽ kiểm tra:

    - Signature
    - Algorithm
    - Expiration

    Args:
        token:
            JWT token dạng string.

    Returns:
        JWT payload nếu token hợp lệ.

        None nếu:
        - Token rỗng
        - Token hết hạn
        - Token sai chữ ký
        - Token không hợp lệ
    """

    validate_jwt_config()


    # =========================================================
    # VALIDATE TOKEN
    # =========================================================

    if not token:

        return None


    # =========================================================
    # DECODE TOKEN
    # =========================================================

    try:

        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[
                JWT_ALGORITHM
            ]
        )

        return payload


    # =========================================================
    # TOKEN EXPIRED
    # =========================================================

    except ExpiredSignatureError:

        return None


    # =========================================================
    # INVALID TOKEN
    # =========================================================

    except InvalidTokenError:

        return None


# ============================================================
# VERIFY ACCESS TOKEN
# ============================================================

def verify_access_token(
    token: str
) -> Optional[Dict[str, Any]]:
    """
    Verify JWT Access Token.

    Kiểm tra:

    - Token tồn tại
    - Token hợp lệ
    - Signature hợp lệ
    - Token chưa hết hạn
    - Có user_id (sub)
    - Có role

    Args:
        token:
            JWT Access Token.

    Returns:
        JWT payload nếu hợp lệ.

        None nếu token không hợp lệ.
    """

    # =========================================================
    # DECODE TOKEN
    # =========================================================

    payload = decode_access_token(
        token
    )


    if not payload:

        return None


    # =========================================================
    # GET REQUIRED DATA
    # =========================================================

    user_id = payload.get(
        "sub"
    )

    role = payload.get(
        "role"
    )


    # =========================================================
    # VALIDATE USER ID
    # =========================================================

    if not user_id:

        return None


    # =========================================================
    # VALIDATE ROLE
    # =========================================================

    if not role:

        return None


    # =========================================================
    # TOKEN IS VALID
    # =========================================================

    return payload