"""Auth-service FastAPI entry point.

Run:
    cd backend/services/auth-service
    set PYTHONPATH=. (hoặc $env:PYTHONPATH="."  trên PowerShell)
    uvicorn app.main:app --reload --port 8001

Endpoints:
- GET  /                            : health check
- GET  /auth/google/login           : bắt đầu Google OAuth flow
- GET  /auth/google/callback        : Google OAuth callback
- GET  /auth/me                     : thông tin user hiện tại (cần Bearer JWT)
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes.auth import router as auth_router
from app.core.config import (
    JWT_SECRET_KEY,
    SERVICE_NAME,
    SERVICE_PORT,
    log,
)
from app.db import get_mongo_client
from app.repositories.google_oauth import register_google_oauth


app = FastAPI(title=SERVICE_NAME, version="1.0.0")


# ------------------------------------------------------------
# Middleware
# ------------------------------------------------------------
# SessionMiddleware BẮT BUỘC cho Authlib OAuth (lưu state chống CSRF).
# Trong production phải đổi secret_key thành random đủ mạnh.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("JWT_SECRET_KEY", JWT_SECRET_KEY or "tlpl-dev-secret-change-me"),
    same_site="lax",
    https_only=False,
)


_allowed_origins = [
    os.getenv("FRONTEND_URL", "http://localhost:5500").rstrip("/"),
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_allowed_origins = [o for o in {o for o in _allowed_origins if o}]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# Startup / shutdown
# ------------------------------------------------------------
@app.on_event("startup")
async def _startup() -> None:
    # Register Google OAuth (validate env + register provider).
    try:
        register_google_oauth()
    except RuntimeError as exc:
        log.error("Google OAuth chưa sẵn sàng: %s", exc)
    # Warm-up Mongo connection (sẽ không throw nếu thiếu env).
    try:
        get_mongo_client().connect()
    except Exception as exc:
        log.error("MongoDB warm-up thất bại: %s", exc)


@app.on_event("shutdown")
async def _shutdown() -> None:
    try:
        get_mongo_client().close()
    except Exception:
        pass


# ------------------------------------------------------------
# Routes
# ------------------------------------------------------------
@app.get("/")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "port": SERVICE_PORT}


app.include_router(auth_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=SERVICE_PORT,
        reload=False,
    )
