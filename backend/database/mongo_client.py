"""
MongoDB connection singleton using PyMongo.

Usage:
    db = get_database()
    collection = db["my_collection"]

    # Or use the client directly
    client = get_mongo_client()
    db = client[DATABASE_NAME]
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo import MongoClient
from pymongo.database import Database

if TYPE_CHECKING:
    from pymongo.collection import Collection

from core.config import log, MONGODB_PASSWORD, MONGODB_URI, MONGODB_USERNAME, DATABASE_NAME


class MongoDBClient:
    """Thread-safe MongoDB client wrapper with lazy initialization."""

    _instance: MongoDBClient | None = None
    _client: MongoClient | None = None

    def __new__(cls) -> MongoDBClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> MongoClient:
        """Establish connection to MongoDB. Idempotent."""
        if self._client is None:
            log.info("Connecting MongoDB at %s ...", MONGODB_URI)
            self._client = MongoClient(
                MONGODB_URI,
                username=MONGODB_USERNAME,
                password=MONGODB_PASSWORD,
                serverSelectionTimeoutMS=5000,
            )
            self._client.admin.command("ping")
            log.info("MongoDB connected successfully to database '%s'.", DATABASE_NAME)
        return self._client

    def close(self) -> None:
        """Close the client if open."""
        if self._client is not None:
            self._client.close()
            self._client = None
            log.info("MongoDB connection closed.")

    def get_database(self, name: str | None = None) -> Database:
        """Get a database by name, defaulting to DATABASE_NAME."""
        db_name = name or DATABASE_NAME
        return self.connect()[db_name]

    def get_collection(self, collection: str, database: str | None = None) -> Collection:
        """Get a collection from the specified database."""
        return self.get_database(database)[collection]

    @property
    def client(self) -> MongoClient:
        """Get the active client, connecting if necessary."""
        return self.connect()


def get_mongo_client() -> MongoDBClient:
    """Get or create the global MongoDB client instance."""
    return MongoDBClient()


def get_database(name: str | None = None) -> Database:
    """Convenience function to get a database directly."""
    return get_mongo_client().get_database(name)
