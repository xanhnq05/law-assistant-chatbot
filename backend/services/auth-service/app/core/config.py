"""Configuration & logging for the auth-service.

Loads env vars from a local .env (next to this service folder) and
from the legacy root .env (backend/.env) for backwards compatibility.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================
# Order of preference (later wins):
#   1. service-local .env  -> services/auth-service/.env
#   2. repo-root .env      -> backend/.env
#   3. process env vars    -> already in os.environ
_SERVICE_DIR = Path(__file__).resolve().parents[2]
_BACKEND_DIR = _SERVICE_DIR.parent.parent

load_dotenv(_SERVICE_DIR / ".env")
load_dotenv(_BACKEND_DIR / ".env")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("auth-service")


# ============================================================
# MONGO
# ============================================================
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_USERNAME = os.getenv("MONGODB_USERNAME")
MONGODB_PASSWORD = os.getenv("MONGODB_PASSWORD")
DATABASE_NAME = os.getenv("DATABASE_NAME", "law_assistant")


# ============================================================
# GOOGLE OAUTH
# ============================================================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_CLIENT_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "http://localhost:8001/auth/google/callback",
)


# ============================================================
# JWT
# ============================================================
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# Refresh token: lưu HASH trong collection `sessions`, gửi cho browser qua
# cookie HttpOnly (JavaScript không đọc được -> khó bị đánh cắp qua XSS).
JWT_REFRESH_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "30"))
REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "tlpl_refresh")
# Chỉ gửi cookie tới /auth/* (refresh, logout), không gửi kèm /chats/*.
REFRESH_COOKIE_PATH = "/auth"
# Production (HTTPS): đặt REFRESH_COOKIE_SECURE=true.
# Nếu frontend và API khác *site*: REFRESH_COOKIE_SAMESITE=none (bắt buộc kèm Secure).
REFRESH_COOKIE_SECURE = os.getenv("REFRESH_COOKIE_SECURE", "false").strip().lower() in (
    "1", "true", "yes",
)
REFRESH_COOKIE_SAMESITE = os.getenv("REFRESH_COOKIE_SAMESITE", "lax").strip().lower()


# ============================================================
# SERVICE
# ============================================================
SERVICE_NAME = "auth-service"
SERVICE_PORT = int(os.getenv("AUTH_SERVICE_PORT", "8001"))
# Where to redirect the browser after OAuth success (frontend).
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")
