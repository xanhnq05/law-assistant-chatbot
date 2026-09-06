"""
Test all database connections.

Self-contained: tự load `.env` từ `backend/.env` mà KHÔNG cần import
`core/config.py`. Chạy được từ bất kỳ thư mục nào.

Run:
    cd backend
    python -m database.test_db_connections

    # Hoặc trực tiếp:
    cd backend/database
    python test_db_connections.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# ============================================================
# 1. LOAD .env ĐỘC LẬP (không qua core/config.py)
# ============================================================
# Tìm file .env ở thư mục backend/ (cha của database/)
_THIS_DIR = Path(__file__).resolve().parent              # = backend/database/
_BACKEND_DIR = _THIS_DIR.parent                          # = backend/
_ENV_PATH = _BACKEND_DIR / ".env"

try:
    from dotenv import load_dotenv
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=False)
        print(f"[INFO] Loaded .env from: {_ENV_PATH}")
    else:
        print(f"[WARN] .env not found at {_ENV_PATH}")
except ImportError:
    print("[WARN] python-dotenv not installed, falling back to os.environ")

# ============================================================
# 2. TỰ TẠO LOGGER (không dùng log từ core/config)
# ============================================================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("db-conn-test")

# ============================================================
# 3. ĐỌC BIẾN MÔI TRƯỜNG TRỰC TIẾP
# ============================================================
def _get_env(key: str, default: str | None = None) -> str | None:
    """Đọc env, trả về None nếu thiếu (không fallback giá trị mặc định ảo)."""
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


# MongoDB
MONGODB_URI = _get_env("MONGODB_URI")
MONGODB_USERNAME = _get_env("MONGODB_USERNAME")
MONGODB_PASSWORD = _get_env("MONGODB_PASSWORD")
DATABASE_NAME = _get_env("DATABASE_NAME", "law_assistant")

# Neo4j
NEO4J_URI = _get_env("NEO4J_URI")
NEO4J_USERNAME = _get_env("NEO4J_USERNAME")
NEO4J_PASSWORD = _get_env("NEO4J_PASSWORD")
NEO4J_DATABASE = _get_env("NEO4J_DATABASE", "neo4j")

# Pinecone
PINECONE_API_KEY = _get_env("PINECONE_API_KEY")
PINECONE_INDEX_NAME = _get_env("PINECONE_INDEX_NAME", "law-rag-v1")


# ============================================================
# 4. CÁC HÀM TEST
# ============================================================
def _check_required(name: str, value: str | None) -> bool:
    """Kiểm tra biến môi trường có giá trị không."""
    if not value:
        log.error("%s: MISSING env variable", name)
        return False
    return True


def test_mongodb() -> bool:
    """Test MongoDB connection."""
    if not all([_check_required("MONGODB_URI", MONGODB_URI),
                _check_required("MONGODB_USERNAME", MONGODB_USERNAME),
                _check_required("MONGODB_PASSWORD", MONGODB_PASSWORD)]):
        return False

    try:
        from pymongo import MongoClient
        log.info("Testing MongoDB connection...")
        client = MongoClient(
            MONGODB_URI,
            username=MONGODB_USERNAME,
            password=MONGODB_PASSWORD,
            serverSelectionTimeoutMS=5000,
        )
        client.admin.command("ping")
        # Test truy cập database
        db = client[DATABASE_NAME]
        _ = db.list_collection_names()  # force query
        log.info("MongoDB: OK (database='%s')", DATABASE_NAME)
        client.close()
        return True
    except Exception as e:
        log.error("MongoDB: FAILED - %s", e)
        return False


def test_neo4j() -> bool:
    """Test Neo4j connection."""
    if not all([_check_required("NEO4J_URI", NEO4J_URI),
                _check_required("NEO4J_USERNAME", NEO4J_USERNAME),
                _check_required("NEO4J_PASSWORD", NEO4J_PASSWORD)]):
        return False

    try:
        from neo4j import GraphDatabase
        log.info("Testing Neo4j connection...")
        driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        )
        driver.verify_connectivity()
        # Test query thực tế
        with driver.session(database=NEO4J_DATABASE) as s:
            result = s.run("RETURN 1 AS ok").single()
            assert result["ok"] == 1
        log.info("Neo4j: OK (database='%s')", NEO4J_DATABASE)
        driver.close()
        return True
    except Exception as e:
        log.error("Neo4j: FAILED - %s", e)
        return False


def test_pinecone() -> bool:
    """Test Pinecone connection."""
    if not _check_required("PINECONE_API_KEY", PINECONE_API_KEY):
        return False

    try:
        from pinecone import Pinecone
        log.info("Testing Pinecone connection...")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        indexes = pc.list_indexes()
        index_names = [ix.name for ix in indexes]

        # Kiểm tra index có tồn tại không
        if PINECONE_INDEX_NAME not in index_names:
            log.warning(
                "Pinecone: connected, but index '%s' NOT in %s",
                PINECONE_INDEX_NAME, index_names,
            )
            return False

        # Test query index stats
        idx = pc.Index(PINECONE_INDEX_NAME)
        stats = idx.describe_index_stats()
        log.info(
            "Pinecone: OK (index='%s', vectors=%d, dim=%d)",
            PINECONE_INDEX_NAME,
            stats.total_vector_count,
            stats.dimension,
        )
        return True
    except Exception as e:
        log.error("Pinecone: FAILED - %s", e)
        return False


# ============================================================
# 5. MAIN
# ============================================================
def test_all() -> None:
    """Test tất cả database connections."""
    print("\n" + "=" * 60)
    print("Database Connection Tests (self-contained, no core.config)")
    print("=" * 60 + "\n")

    # In ra env đã load
    # print("Config loaded:")
    # print(f"  MONGODB_URI       = {MONGODB_URI}")
    # print(f"  MONGODB_USERNAME  = {MONGODB_USERNAME}")
    # print(f"  NEO4J_URI         = {NEO4J_URI}")
    # print(f"  NEO4J_DATABASE    = {NEO4J_DATABASE}")
    # print(f"  PINECONE_INDEX    = {PINECONE_INDEX_NAME}")
    # print(f"  (passwords hidden)\n")

    results = {
        "MongoDB": test_mongodb(),
        "Neo4j":   test_neo4j(),
        "Pinecone": test_pinecone(),
    }

    print("\n" + "=" * 60)
    print("Results Summary")
    print("=" * 60)

    all_passed = True
    for name, success in results.items():
        status = "PASS" if success else "FAIL"
        marker = "[OK]" if success else "[FAIL]"
        print(f"  {marker} {name}: {status}")
        if not success:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("All database connections successful!")
    else:
        print("Some database connections failed.")
        sys.exit(1)


if __name__ == "__main__":
    test_all()
