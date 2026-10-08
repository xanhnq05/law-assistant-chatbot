"""Neo4j connection singleton cho document-service.

Phase 2+: lift toàn bộ logic import từ `data_import/import_data_neo4j.py`
vào đây. Phase 1 chỉ cần stub để service khởi động được.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from neo4j import GraphDatabase

if TYPE_CHECKING:
    from neo4j import Driver, Session

from app.core.config import log

# Phase 2+ sẽ import từ config khi nào cần dùng.
NEO4J_URI = None  # set in core/config.py khi activate
NEO4J_USERNAME = None
NEO4J_PASSWORD = None
NEO4J_DATABASE = None


class Neo4jClient:
    """Thread-safe Neo4j driver wrapper với lazy initialization."""

    _instance: Neo4jClient | None = None
    _driver: Driver | None = None

    def __new__(cls) -> Neo4jClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Driver:
        if self._driver is None:
            if not NEO4J_URI:
                raise RuntimeError("Neo4j chưa được kích hoạt cho document-service (Phase 2+).")
            log.info("Connecting Neo4j at %s ...", NEO4J_URI)
            self._driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            )
            self._driver.verify_connectivity()
            log.info("Neo4j connected.")
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            log.info("Neo4j connection closed.")


def get_neo4j_client() -> Neo4jClient:
    return Neo4jClient()
