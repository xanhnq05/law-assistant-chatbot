"""document-service FastAPI entry point.

Run (terminal mode, không Docker):
    cd backend/services/document-service
    $env:PYTHONPATH="."        # PowerShell
    python -m uvicorn app.main:app --reload --port 8004

Run (Docker):
    docker compose up document-service

Endpoints:
- GET  /                          : health
- GET  /admin/health              : admin health
- GET  /admin/me                  : current admin user info (JWT)
- POST /admin/documents/upload    : upload PDF/DOCX + metadata (JWT+admin)
- GET  /admin/documents           : list documents (JWT+admin)

Phase 1 chỉ cần Mongo + Supabase Storage.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.admin import router as admin_router
from app.core.config import (
    ADMIN_FRONTEND_URL,
    FRONTEND_URL,
    SERVICE_NAME,
    SERVICE_PORT,
    log,
)
from app.db import get_mongo_client

app = FastAPI(
    title=SERVICE_NAME,
    version="1.0.0",
    description=(
        "Admin Document Management service. "
        "Chỉ cho phép user có role=admin truy cập."
    ),
)


# ------------------------------------------------------------
# CORS
# ------------------------------------------------------------
_allowed_origins = [
    FRONTEND_URL.rstrip("/"),
    ADMIN_FRONTEND_URL.rstrip("/"),
    "http://localhost:5174",      # admin SPA (Vite dev)
    "http://127.0.0.1:5174",
    "http://localhost:5173",      # user SPA (optional debug)
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
    """Warm up Mongo connection."""
    try:
        get_mongo_client().connect()
    except Exception as exc:
        log.error("MongoDB warm-up thất bại: %s", exc)

    # Supabase chỉ init khi cần (lazy qua get_supabase_client())


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


app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=SERVICE_PORT,
        reload=False,
    )
