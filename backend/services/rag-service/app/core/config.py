"""Configuration & logging setup cho rag-service.

rag-service là **self-contained microservice**:
  - Tất cả biến môi trường load từ `backend/.env` (single source of truth).
  - KHÔNG share config với service khác qua import.
  - Tất cả resource (Neo4j, Pinecone, Groq, embedder) đều do service này
    tự khởi tạo.

Load order:
  1. `backend/services/rag-service/.env` (nếu có - override)
  2. `backend/.env` (single source of truth)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# .env loading
# ============================================================
# File .env ở thư mục gốc `backend/` chứa toàn bộ secrets.
# Service-local .env (nếu có) sẽ override.
_BACKEND_DIR = Path(__file__).resolve().parents[3]  # = backend/
_SERVICE_DIR = Path(__file__).resolve().parents[2]  # = backend/services/rag-service/

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
log = logging.getLogger("rag-service")


# ============================================================
# SERVICE METADATA
# ============================================================
SERVICE_NAME = "rag-service"
SERVICE_PORT = int(os.getenv("RAG_SERVICE_PORT", "8003"))


# ============================================================
# GROQ (LLM)
# ============================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# Model nhỏ hơn cho B7 verifier (nhanh + rẻ).
GROQ_MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")
GROQ_TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0"))


# ============================================================
# EMBEDDING (B3)
# ============================================================
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))


# ============================================================
# PINECONE (B4 - vector)
# ============================================================
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "law-rag-v1")
# Lấy dư từ Pinecone để B4 filter/rerank lại.
PINECONE_TOP_K = int(os.getenv("PINECONE_TOP_K", "8"))


# ============================================================
# NEO4J (B4 - graph)
# ============================================================
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


# ============================================================
# VERIFICATION (B7)
# ============================================================
# Ngưỡng chấp nhận câu trả lời từ symbolic verifier (0.0 - 1.0).
VERIFICATION_PASS_THRESHOLD = float(os.getenv("VERIFICATION_PASS_THRESHOLD", "0.6"))
# Bật/tắt LLM-as-Judge (vẫn chạy rule-based nếu False).
VERIFIER_LLM_ENABLED = os.getenv("VERIFIER_LLM_ENABLED", "true").lower() == "true"


# ============================================================
# RERANKER (B4 - optional hook)
# ============================================================
# Bật để dùng cross-encoder reranking (chậm hơn nhưng precision cao hơn).
# Mặc định tắt để giữ latency thấp + không tốn RAM.
# Cần ~2GB RAM cho bge-reranker-v2-m3.
RERANKER_ENABLED = os.getenv("RERANKER_ENABLED", "false").lower() == "true"
# Số candidate tối đa đưa vào reranker (sau soft boost + trước rerank).
RERANKER_TOP_N = int(os.getenv("RERANKER_TOP_N", "20"))


# ============================================================
# LANGSMITH (observability)
# ============================================================
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "law assistant chatbot")


# ============================================================
# CORS
# ============================================================
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")
