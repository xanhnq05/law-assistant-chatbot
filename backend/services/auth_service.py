# Login, token refresh, logout
"""
Authentication Service.

This service acts as an orchestrator.

Responsibilities:
- Handle Google login flow
- Get Google user information
- Check whether the user exists
- Create a new user if necessary
- Update last login for existing users
- Generate JWT access token
- Return login response

This service does NOT:
- Directly communicate with Google OAuth endpoints
- Directly query MongoDB
- Directly create MongoDB documents
- Directly encode/decode JWT logic

Those responsibilities are delegated to:
- utils.auth.auth_gg
- utils.auth.check_exist
- utils.auth.create_user
- utils.auth.update_last_login
- utils.auth.jwt
"""

from typing import Any, Dict

from fastapi import HTTPException, Request, status

from utils.auth.auth_gg import get_google_user_info

from utils.auth.check_exist import (
    find_user_by_google_id,
)

from utils.auth.create_history_chat import (
    create_initial_chat_history,
)
from utils.auth.create_user import (
    create_user,
)

from utils.auth.update_last_login import (
    update_last_login,
)

from utils.auth.jwt import (
    create_access_token,
    decode_access_token,
)


# ============================================================
# HANDLE GOOGLE LOGIN CALLBACK
# ============================================================

async def handle_google_login(
    request: Request
) -> Dict[str, Any]:
    """
    Xử lý toàn bộ luồng đăng nhập Google.

    Flow:

        Google Callback
            ↓
        Get Google User Info
            ↓
        Find User in MongoDB
            ↓
        User exists?
          ↙         ↘
        NO           YES
        ↓             ↓
    Create User   Update Last Login
        ↓             ↓
        └──────┬──────┘
               ↓
          Create JWT
               ↓
        Return Login Response


    Args:
        request:
            FastAPI Request được gửi từ Google OAuth callback.

    Returns:
        Dict[str, Any]:

        {
            "user": {
                "id": "...",
                "google_id": "...",
                "email": "...",
                "name": "...",
                "picture": "...",
                "role": "user"
            },
            "access_token": "...",
            "token_type": "bearer",
            "is_new_user": True
        }

    Raises:
        HTTPException:
            Nếu Google authentication hoặc database
            processing thất bại.
    """

    try:

        # ====================================================
        # 1. GET USER INFORMATION FROM GOOGLE
        # ====================================================

        google_user = await get_google_user_info(
            request
        )

        if not google_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to retrieve Google user information"
            )

        # ====================================================
        # 2. GET GOOGLE ID
        # ====================================================

        google_id = google_user.get(
            "sub"
        )

        if not google_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Google user ID is missing"
            )

        # ====================================================
        # 3. CHECK IF USER EXISTS
        # ====================================================

        user = find_user_by_google_id(
            google_id
        )

        is_new_user = False

        # ====================================================
        # 4. USER DOES NOT EXIST -> CREATE USER
        # ====================================================

        if user is None:

            user = create_user(
                google_user
            )

            # Khởi tạo document chat_history rỗng cho user mới.
            create_initial_chat_history(
                user["_id"]
            )

            is_new_user = True

        # ====================================================
        # 5. USER EXISTS -> UPDATE LAST LOGIN
        # ====================================================

        else:

            updated_user = update_last_login(
                user["_id"]
            )

            # Nếu update thất bại thì vẫn giữ
            # user document đã tìm được trước đó.
            if updated_user is not None:
                user = updated_user

        # ====================================================
        # 6. VALIDATE USER
        # ====================================================

        if not user:

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to process user information"
            )

        user_id = user.get(
            "_id"
        )

        role = user.get(
            "role",
            "user"
        )

        if not user_id:

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User ID is missing"
            )

        # ====================================================
        # 7. CREATE JWT ACCESS TOKEN
        # ====================================================

        access_token = create_access_token(
            user_id=str(user_id),
            role=role
        )

        # ====================================================
        # 8. PREPARE SAFE USER RESPONSE
        # ====================================================

        user_response = {
            "id": str(
                user_id
            ),

            "google_id": user.get(
                "google_id"
            ),

            "email": user.get(
                "email"
            ),

            "name": user.get(
                "name"
            ),

            "picture": user.get(
                "picture"
            ),

            "email_verified": user.get(
                "email_verified",
                False
            ),

            "role": role
        }

        # ====================================================
        # 9. RETURN LOGIN RESPONSE
        # ====================================================

        return {
            "user": user_response,

            "access_token": access_token,

            "token_type": "bearer",

            "is_new_user": is_new_user
        }

    # ========================================================
    # HTTP EXCEPTION
    # ========================================================

    except HTTPException:
        raise

    # ========================================================
    # UNEXPECTED ERROR
    # ========================================================

    except Exception as error:

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Google login failed. "
                f"Error: {str(error)}"
            )
        )


# ============================================================
# GET CURRENT USER FROM REQUEST
# ============================================================

async def get_current_user(
    request: Request
) -> str:
    """
    Trích xuất user_id từ JWT trong header Authorization.

    Args:
        request: FastAPI Request.

    Returns:
        str: MongoDB user_id (subject) của user hiện tại.

    Raises:
        HTTPException:
            - 401 nếu thiếu header / token không hợp lệ.
            - 401 nếu token không có subject.
            - 404 nếu user không còn tồn tại trong DB.
    """
    from utils.user import load_user

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

    token = parts[1]

    payload = decode_access_token(token)
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

    user = load_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user_id