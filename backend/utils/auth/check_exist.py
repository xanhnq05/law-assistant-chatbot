"""
Utility functions for finding and checking users in MongoDB.

Responsibilities:
- Find user by Google ID
- Find user by email
- Find user by MongoDB ID
- Check whether a user exists

This file does NOT:
- Create users
- Update users
- Handle Google OAuth
- Generate JWT
"""

from typing import Any, Dict, Optional, Union

from bson import ObjectId
from bson.errors import InvalidId

from database.mongo_client import get_mongo_client


# ============================================================
# GET USERS COLLECTION
# ============================================================

users_collection = (
    get_mongo_client()
    .get_collection("users")
)


# ============================================================
# FIND USER BY GOOGLE ID
# ============================================================

def find_user_by_google_id(
    google_id: str
) -> Optional[Dict[str, Any]]:
    """
    Tìm User bằng Google ID.

    Google ID được lấy từ:
        google_user["sub"]

    MongoDB field:
        google_id

    Args:
        google_id:
            Google unique user ID.

    Returns:
        User document nếu tìm thấy.

        None nếu không tìm thấy hoặc google_id không hợp lệ.
    """

    if not google_id:
        return None

    user = users_collection.find_one(
        {
            "google_id": google_id
        }
    )

    return user


# ============================================================
# FIND USER BY EMAIL
# ============================================================

def find_user_by_email(
    email: str
) -> Optional[Dict[str, Any]]:
    """
    Tìm User bằng email.

    Args:
        email:
            Email của User.

    Returns:
        User document nếu tìm thấy.

        None nếu không tìm thấy hoặc email không hợp lệ.
    """

    if not email:
        return None

    # Chuẩn hóa email để tránh khác biệt
    # giữa chữ hoa và chữ thường.
    normalized_email = email.strip().lower()

    if not normalized_email:
        return None

    user = users_collection.find_one(
        {
            "email": normalized_email
        }
    )

    return user


# ============================================================
# FIND USER BY MONGODB ID
# ============================================================

def find_user_by_id(
    user_id: Union[str, ObjectId]
) -> Optional[Dict[str, Any]]:
    """
    Tìm User bằng MongoDB _id.

    Args:
        user_id:
            MongoDB ObjectId hoặc ObjectId dạng string.

    Returns:
        User document nếu tìm thấy.

        None nếu:
        - user_id rỗng
        - user_id không hợp lệ
        - không tìm thấy User
    """

    if not user_id:
        return None

    try:

        # Nếu đã là ObjectId
        if isinstance(user_id, ObjectId):

            user_object_id = user_id

        # Nếu là string
        else:

            user_object_id = ObjectId(
                str(user_id)
            )

        user = users_collection.find_one(
            {
                "_id": user_object_id
            }
        )

        return user

    except (InvalidId, TypeError):

        return None


# ============================================================
# CHECK USER EXISTS
# ============================================================

def check_user_exists(
    google_id: str
) -> bool:
    """
    Kiểm tra User có tồn tại trong MongoDB hay không
    bằng Google ID.

    Args:
        google_id:
            Google unique user ID.

    Returns:
        True:
            User tồn tại.

        False:
            User không tồn tại.
    """

    user = find_user_by_google_id(
        google_id
    )

    return user is not None