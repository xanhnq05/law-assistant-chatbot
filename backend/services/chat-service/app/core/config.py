"""Configuration & logging for the chat-service."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv


_SERVICE_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _SERVICE_DIR.parent.parent

load_dotenv(_SERVICE_DIR / ".env")
load_dotenv(_BACKEND_DIR / ".env")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chat-service")


# Mongo
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME", "law_assistant")


# JWT (phải dùng chung với auth-service để verify token chéo)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))


# RAG-service (microservice khác). chat-service sẽ gọi HTTP sang đó.
RAG_SERVICE_URL = os.getenv("RAG_SERVICE_URL", "http://localhost:8003")
RAG_TIMEOUT_SECONDS = float(os.getenv("RAG_TIMEOUT_SECONDS", "60"))


# Service
SERVICE_NAME = "chat-service"
SERVICE_PORT = int(os.getenv("CHAT_SERVICE_PORT", "8002"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")
