"""db package — exposes MongoDB accessors for the auth-service."""
from __future__ import annotations

from app.db.mongo_client import (
    MongoDBClient,
    get_database,
    get_mongo_client,
)

__all__ = ["MongoDBClient", "get_mongo_client", "get_database"]
