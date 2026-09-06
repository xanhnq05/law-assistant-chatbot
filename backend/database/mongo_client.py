"""MongoDB connection singleton using PyMongo.

Used by the RAG gateway (backend/app.py) for the connection-test
script and any code that needs MongoDB access at gateway level.

NOTE: Microservices (auth-service, chat-service) have their own
copy at services/<svc>/app/db/mongo_client.py — keep them in sync
if you change anything here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pymongo import MongoClient
from pymongo.database import Database

if TYPE_CHECKING:
    from pymongo.collection import Collection

from core.config import (
    MONGODB_PASSWORD,
    MONGODB_URI,
    MONGODB_USERNAME,
    log,
)


class MongoDBClient:
    """Thread-safe MongoDB client wrapper with lazy initialization."""

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
