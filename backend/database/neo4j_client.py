"""
Neo4j connection singleton.

Usage:
    client = get_neo4j_client()
    with client.session() as session:
        result = session.run("MATCH (n) RETURN count(n)")
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from neo4j import GraphDatabase

if TYPE_CHECKING:
    from neo4j import Driver, Session

from config import log, NEO4J_DATABASE, NEO4J_PASSWORD, NEO4J_URI, NEO4J_USERNAME


class Neo4jClient:
    """Thread-safe Neo4j driver wrapper with lazy initialization."""

    _instance: Neo4jClient | None = None
    _driver: Driver | None = None

    def __new__(cls) -> Neo4jClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Driver:
        """Establish connection to Neo4j. Idempotent."""
        if self._driver is None:
            log.info("Connecting Neo4j at %s ...", NEO4J_URI)
            self._driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            )
            self._driver.verify_connectivity()
            log.info("Neo4j connected successfully.")
        return self._driver

    def close(self) -> None:
        """Close the driver if open."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            log.info("Neo4j connection closed.")

    def session(self, database: str | None = None) -> Session:
        """Open a new session against the configured database."""
        db = database or NEO4J_DATABASE
        return self.connect().session(database=db)

    @property
    def driver(self) -> Driver:
        """Get the active driver, connecting if necessary."""
        return self.connect()


def get_neo4j_client() -> Neo4jClient:
    """Get or create the global Neo4j client instance."""
    return Neo4jClient()
