"""
Neo4j connection singleton - self-contained trong rag-service.

rag-service tự khởi tạo + đóng driver Neo4j; không phụ thuộc
service khác.

Usage:
    from db.neo4j_client import get_neo4j_client

    client = get_neo4j_client()
    with client.session() as session:
        result = session.run("MATCH (n) RETURN count(n)")
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from neo4j import GraphDatabase

if TYPE_CHECKING:
    from neo4j import Driver, Session

from app.core.config import (
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    log,
)


class Neo4jClient:
    """Thread-safe Neo4j driver wrapper với lazy initialization."""

    _instance: Neo4jClient | None = None
    _driver: Driver | None = None

    def __new__(cls) -> Neo4jClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Driver:
        """Khởi tạo driver. Idempotent."""
        if self._driver is None:
            log.info("Connecting Neo4j at %s ...", NEO4J_URI)
            self._driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            )
            self._driver.verify_connectivity()
            log.info("Neo4j connected.")
        return self._driver

    def close(self) -> None:
        """Đóng driver nếu đang mở."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            log.info("Neo4j connection closed.")

    def session(self, database: str | None = None) -> Session:
        """Mở session mới với database được config."""
        db = database or NEO4J_DATABASE
        return self.connect().session(database=db)

    @property
    def driver(self) -> Driver:
        return self.connect()


def get_neo4j_client() -> Neo4jClient:
    """Singleton accessor."""
    return Neo4jClient()
