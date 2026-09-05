"""
Utility for creating initial chat history for a new user.

Responsibilities:
- Create an initial empty chat history document
- Associate the chat history with a user

This file does NOT:
- Add user messages
- Add assistant messages
- Call AI or RAG services
- Generate JWT
- Handle Google OAuth
"""

from datetime import datetime, timezone
from typing import Any, Dict

from database.mongo_client import get_mongo_client


# ============================================================
# GET CHAT HISTORY COLLECTION
# ============================================================

chat_history_collection = (
    get_mongo_client()
    .get_collection("chat_history")
)


# ============================================================
# CREATE INITIAL CHAT HISTORY
# ============================================================

def create_initial_chat_history(
    user_id: Any
) -> Dict[str, Any]:
    """
    Tạo document lịch sử chat ban đầu cho User mới.

    Document được tạo với danh sách chats rỗng.

    Args:
        user_id:
            MongoDB ObjectId của User.

    Returns:
        Dict[str, Any]:
            Document chat history vừa được tạo.

    Example document:

    {
        "_id": ObjectId(...),

        "user_id": ObjectId(...),

        "chats": [],

        "created_at": datetime(...),

        "updated_at": datetime(...)
    }
    """

    # =========================================================
    # 1. VALIDATE USER ID
    # =========================================================

    if not user_id:
        raise ValueError(
            "user_id is required"
        )


    # =========================================================
    # 2. CREATE CURRENT UTC TIME
    # =========================================================

    now = datetime.now(
        timezone.utc
    )


    # =========================================================
    # 3. CREATE CHAT HISTORY DOCUMENT
    # =========================================================

    chat_history_document = {

        # User owner
        "user_id": user_id,

        # List of chat sessions
        "chats": [],

        # Timestamps
        "created_at": now,

        "updated_at": now
    }


    # =========================================================
    # 4. INSERT INTO MONGODB
    # =========================================================

    result = chat_history_collection.insert_one(
        chat_history_document
    )


    # =========================================================
    # 5. ADD GENERATED MONGODB ID
    # =========================================================

    chat_history_document["_id"] = (
        result.inserted_id
    )


    # =========================================================
    # 6. RETURN CREATED DOCUMENT
    # =========================================================

    return chat_history_document