"""MongoDB connection for chat-service.

Mirror of backend/database/mongo_client.py — share cùng MongoDB cluster
với auth-service (chỉ khác service name trong log).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo import MongoClient
from pymongo.database import Database

if TYPE_CHECKING:
    from pymongo.collection import Collection

from app.core.config import (
    DATABASE_NAME,
    MONGODB_PASSWORD,
    MONGODB_URI,
    MONGODB_USERNAME,
    log,
)


class MongoDBClient:
    _instance: MongoDBClient | None = None
    _client: MongoClient | None = None

    def __new__(cls) -> MongoDBClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> MongoClient:
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
        if self._client is not None:
            self._client.close()
            self._client = None
            log.info("MongoDB connection closed.")

    def get_database(self, name: str | None = None) -> Database:
        return self.connect()[name or DATABASE_NAME]

    def get_collection(self, collection: str, database: str | None = None) -> Collection:
        return self.get_database(database)[collection]

    @property
    def client(self) -> MongoClient:
        return self.connect()


def get_mongo_client() -> MongoDBClient:
    return MongoDBClient()


def get_database(name: str | None = None) -> Database:
    return get_mongo_client().get_database(name)
