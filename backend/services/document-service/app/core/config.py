"""Configuration & logging setup cho document-service.

document-service là microservice self-contained (clone pattern từ rag-service):
  - Tất cả biến môi trường load từ `backend/.env` (single source of truth).
  - KHÔNG share config với service khác qua import.
  - Tất cả resource (Mongo, Neo4j, Pinecone, Supabase, Groq parser) đều do
    service này tự khởi tạo.

Load order:
    1. `backend/services/document-service/.env` (nếu có - override)
    2. `backend/.env` (single source of truth)

Phase 1 chỉ cần Mongo + JWT + Supabase + Groq parser key.
Phase 2+ sẽ thêm Neo4j, Pinecone, embedding model.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# ============================================================
# .env loading
# ============================================================
# Path layout: backend/services/document-service/app/core/config.py
#   parents[0] = app/core/
#   parents[1] = app/
#   parents[2] = document-service/
#   parents[3] = services/
#   parents[4] = backend/         ← đây là root
_BACKEND_DIR = Path(__file__).resolve().parents[4]  # = backend/
_SERVICE_DIR = Path(__file__).resolve().parents[3]  # = backend/services/document-service/

for candidate in [
    _SERVICE_DIR / ".env",       # ưu tiên service-local
    _BACKEND_DIR / ".env",       # fallback root
]:
    if candidate.exists():
        load_dotenv(candidate, override=False)


# ============================================================
# Logging
# ============================================================
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("document-service")


# ============================================================
# SERVICE METADATA
# ============================================================
SERVICE_NAME = "document-service"
SERVICE_PORT = int(os.getenv("DOCUMENT_SERVICE_PORT", "8004"))


# ============================================================
# MONGO (shared cluster với auth-service / chat-service)
# ============================================================
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME", "law_assistant")


# ============================================================
# JWT (verify-only - cùng secret với auth-service)
# ============================================================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


# ============================================================
# SUPABASE (storage cho PDF/DOCX + JSON intermediate)
# ============================================================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_BUCKET_DOCUMENTS = os.getenv("SUPABASE_BUCKET_DOCUMENTS", "documents")
SUPABASE_BUCKET_JSON = os.getenv("SUPABASE_BUCKET_JSON", "json")


# ============================================================
# GROQ (LLM fallback cho parser)
# ============================================================
GROQ_API_KEY_DOCUMENT_PARSER = os.getenv("GROQ_API_KEY_document_parser")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")
PARSER_FALLBACK_ENABLED = os.getenv("PARSER_FALLBACK_ENABLED", "true").lower() == "true"


# ============================================================
# NEO4J (graph database)
# ============================================================
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
NEO4J_IMPORT_ENABLED = os.getenv("NEO4J_IMPORT_ENABLED", "true").lower() == "true"


# ============================================================
# PINECONE (vector database for RAG)
# ============================================================
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "law-rag-v1")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "")
PINECONE_IMPORT_ENABLED = os.getenv("PINECONE_IMPORT_ENABLED", "true").lower() == "true"


# ============================================================
# ADMIN (optional allowlist)
# ============================================================
# Optional comma-separated email list. Nếu rỗng → chỉ check role trong Mongo.
ADMIN_EMAILS_ALLOWLIST = [
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS_ALLOWLIST", "").split(",")
    if e.strip()
]


# ============================================================
# CORS (admin SPA chạy port 5174 riêng)
# ============================================================
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
ADMIN_FRONTEND_URL = os.getenv("ADMIN_FRONTEND_URL", "http://localhost:5174")

# NOTE: KHÔNG còn dùng local output/ — pipeline đã chuyển sang cloud-only
# (Supabase Storage). Cleanup dead code.
