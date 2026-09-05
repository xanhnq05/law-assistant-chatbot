"""
Utility for updating a user's last login information.

Responsibilities:
- Update last_login
- Update updated_at
- Return the updated user document
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from bson import ObjectId
from bson.errors import InvalidId

from pymongo import ReturnDocument

from database.mongo_client import get_mongo_client


# ============================================================
# GET USERS COLLECTION
# ============================================================

users_collection = (
    get_mongo_client()
    .get_collection("users")
)


# ============================================================
# UPDATE LAST LOGIN
# ============================================================

def update_last_login(
    user_id: Union[str, ObjectId]
) -> Optional[Dict[str, Any]]:
    """
    Update last_login and updated_at for an existing user.

    Args:
        user_id:
            MongoDB User _id.

            Supported formats:
            - ObjectId
            - ObjectId string

    Returns:
        Updated user document.

        Returns None if:
        - user_id is invalid
        - user does not exist
        - user cannot be updated
    """

    # =========================================================
    # 1. VALIDATE USER ID
    # =========================================================

    if not user_id:
        return None


    # =========================================================
    # 2. CONVERT USER ID TO OBJECTID
    # =========================================================

    try:

        if isinstance(
            user_id,
            ObjectId
        ):

            user_object_id = user_id

        else:

            user_object_id = ObjectId(
                str(user_id)
            )

    except (
        InvalidId,
        TypeError
    ):

        return None


    # =========================================================
    # 3. CREATE CURRENT UTC TIME
    # =========================================================

    now = datetime.now(
        timezone.utc
    )


    # =========================================================
    # 4. UPDATE USER
    # =========================================================

    updated_user = (
        users_collection.find_one_and_update(

            # Find user
            {
                "_id": user_object_id
            },

            # Update fields
            {
                "$set": {

                    "last_login": now,

                    "updated_at": now
                }
            },

            # Return updated document
            return_document=ReturnDocument.AFTER
        )
    )


    # =========================================================
    # 5. RETURN RESULT
    # =========================================================

    return updated_user