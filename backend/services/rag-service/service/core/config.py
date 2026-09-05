"""Configuration & logging setup for the backend gateway.

This `app.py` runs ONLY the RAG public endpoint (POST /api/chat)
and a health page. Authentication & chat-history endpoints now live
in `services/auth-service` and `services/chat-service` (microservices).

All environment values are loaded from `.env` files (local then
backend-root). No business logic lives here.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv


# Load .env files in order of preference.
_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backend")


# ============================================================
# NEO4J
# ============================================================
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


# ============================================================
# PINECONE
# ============================================================
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "law-rag-v1"


# ============================================================
# MODELS
# ============================================================
GROQ_MODEL = "llama-3.3-70b-versatile"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


# ============================================================
# MONGODB (chỉ để test_db_connections chạy từ backend root)
# ============================================================
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME", "law_assistant")


# ============================================================
# SERVICE URLS (cho các microservice liên kết)
# ============================================================
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8001")
CHAT_SERVICE_URL = os.getenv("CHAT_SERVICE_URL", "http://localhost:8002")
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8003")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")
