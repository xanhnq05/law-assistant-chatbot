"""
Utility for creating a new user in MongoDB.

Responsibilities:
- Receive authenticated Google user information
- Validate required user information
- Normalize user data
- Create a new user document
- Set default role to "user"
- Set timestamps

This file does NOT:
- Handle Google OAuth
- Check whether the user already exists
- Update existing users
- Generate JWT
"""

from datetime import datetime, timezone
from typing import Any, Dict

from database.mongo_client import get_mongo_client


# ============================================================
# GET USERS COLLECTION
# ============================================================

users_collection = (
    get_mongo_client()
    .get_collection("users")
)


# ============================================================
# CREATE USER
# ============================================================

def create_user(
    google_user: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Create a new user from authenticated Google user information.

    Expected google_user structure:

    {
        "sub": "...",
        "email": "...",
        "name": "...",
        "email_verified": True
    }

    MongoDB user document:

    {
        "_id": ObjectId(...),
        "google_id": "...",
        "email": "...",
        "name": "...",
        "email_verified": True,
        "role": "user",
        "created_at": datetime(...),
        "updated_at": datetime(...),
        "last_login": datetime(...)
    }

    Args:
        google_user:
            User information returned from Google OAuth.

    Returns:
        Dict[str, Any]:
            Newly created user document.

    Raises:
        ValueError:
            If required user information is missing.
    """

    # =========================================================
    # 1. VALIDATE GOOGLE USER DATA
    # =========================================================

    if not google_user:

        raise ValueError(
            "Google user information is required"
        )

    google_id = google_user.get(
        "sub"
    )

    email = google_user.get(
        "email"
    )

    name = google_user.get(
        "name"
    )


    # =========================================================
    # 2. VALIDATE REQUIRED FIELDS
    # =========================================================

    if not google_id:

        raise ValueError(
            "Google user ID (sub) is required"
        )

    if not email:

        raise ValueError(
            "Google user email is required"
        )


    # =========================================================
    # 3. NORMALIZE DATA
    # =========================================================

    google_id = str(
        google_id
    ).strip()

    email = str(
        email
    ).strip().lower()

    # Name có thể không tồn tại trong một số trường hợp.
    # Nếu không có thì dùng email làm tên mặc định.
    if name:

        name = str(
            name
        ).strip()

    else:

        name = email


    # =========================================================
    # 4. VALIDATE NORMALIZED DATA
    # =========================================================

    if not google_id:

        raise ValueError(
            "Google user ID cannot be empty"
        )

    if not email:

        raise ValueError(
            "Google user email cannot be empty"
        )


    # =========================================================
    # 5. CREATE UTC TIMESTAMP
    # =========================================================

    now = datetime.now(
        timezone.utc
    )


    # =========================================================
    # 6. CREATE USER DOCUMENT
    # =========================================================

    user_document = {

        # Google unique user ID
        "google_id": google_id,

        # User email
        "email": email,

        # User display name
        "name": name,

        # Google email verification status
        "email_verified": bool(
            google_user.get(
                "email_verified",
                False
            )
        ),

        # Default role for newly created users
        "role": "user",

        # Account creation time
        "created_at": now,

        # Last user information update time
        "updated_at": now,

        # Last successful login time
        "last_login": now
    }


    # =========================================================
    # 7. INSERT USER INTO MONGODB
    # =========================================================

    result = users_collection.insert_one(
        user_document
    )


    # =========================================================
    # 8. ADD GENERATED MONGODB ID
    # =========================================================

    user_document["_id"] = (
        result.inserted_id
    )


    # =========================================================
    # 9. RETURN CREATED USER
    # =========================================================

    return user_document