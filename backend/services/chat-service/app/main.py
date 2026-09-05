"""Chat-service FastAPI entry point.

Run:
    cd backend/services/chat-service
    $env:PYTHONPATH="."        # PowerShell
    uvicorn app.main:app --reload --port 8002

Phụ thuộc runtime:
- MongoDB (cùng cluster với auth-service)
- rag-service đang chạy ở RAG_SERVICE_URL (mặc định http://localhost:8003)
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chats import router as chats_router
from app.core.config import SERVICE_NAME, SERVICE_PORT, log
from app.db import get_mongo_client


app = FastAPI(title=SERVICE_NAME, version="1.0.0")


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


app.include_router(chats_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=SERVICE_PORT,
        reload=False,
    )
