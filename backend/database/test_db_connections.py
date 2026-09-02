"""
Test all database connections.

Run: python -m database.test_db_connections
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from database import (
    get_mongo_client,
    get_neo4j_client,
)
from database.pinecone_client import get_pinecone_client
from core.config import log


def test_mongodb() -> bool:
    """Test MongoDB connection."""
    try:
        log.info("Testing MongoDB connection...")
        client = get_mongo_client()
        client.connect()
        # Ping to verify
        client.client.admin.command("ping")
        log.info("MongoDB: OK")
        return True
    except Exception as e:
        log.error("MongoDB: FAILED - %s", e)
        return False


def test_neo4j() -> bool:
    """Test Neo4j connection."""
    try:
        log.info("Testing Neo4j connection...")
        client = get_neo4j_client()
        client.connect()
        # Verify connectivity
        client.driver.verify_connectivity()
        log.info("Neo4j: OK")
        return True
    except Exception as e:
        log.error("Neo4j: FAILED - %s", e)
        return False


def test_pinecone() -> bool:
    """Test Pinecone connection."""
    try:
        log.info("Testing Pinecone connection...")
        client = get_pinecone_client()
        client.connect()
        indexes = client.list_indexes()
        log.info("Pinecone: OK (found %d indexes: %s)", len(indexes), indexes)
        return True
    except Exception as e:
        log.error("Pinecone: FAILED - %s", e)
        return False


def test_all() -> None:
    """Test all database connections."""
    print("\n" + "=" * 50)
    print("Database Connection Tests")
    print("=" * 50 + "\n")

    results = {
        "MongoDB": test_mongodb(),
        "Neo4j": test_neo4j(),
        "Pinecone": test_pinecone(),
    }

    print("\n" + "=" * 50)
    print("Results Summary")
    print("=" * 50)

    all_passed = True
    for name, success in results.items():
        status = "PASS" if success else "FAIL"
        print(f"  {name}: {status}")
        if not success:
            all_passed = False

    print("=" * 50)
    if all_passed:
        print("All database connections successful!")
    else:
        print("Some database connections failed.")
        sys.exit(1)


if __name__ == "__main__":
    test_all()
