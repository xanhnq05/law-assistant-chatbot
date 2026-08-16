"""
Configuration & logging setup for the backend.

All environment values are loaded from .env (or ../source/.env for
backwards compatibility). No business logic lives here.
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv


def _load_env() -> None:
    """Load .env files in order of preference."""
    load_dotenv()
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "source", ".env"))


_load_env()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backend")


# ============================================================
# CONFIG
# ============================================================

NEO4J_URI      = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

PINECONE_API_KEY    = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "law-rag-v1"

GROQ_MODEL      = "llama-3.3-70b-versatile"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"