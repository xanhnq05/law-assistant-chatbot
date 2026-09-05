"""rag-service entry point.

Run:
    cd backend
    $env:PYTHONPATH="backend;backend/services/rag-service"
    uvicorn services.rag-service.app.main:app --reload --port 8003

Lưu ý: service này TÁI SỬ DỤNG `backend.core.*` và `backend.rag.*`
nên cần PYTHONPATH trỏ về `backend/`. Khi đã có Dockerfile / docker-compose
sẽ set trong image, còn lúc chạy local thì dùng biến môi trường như trên.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from service.api.routes.chat import router as chat_router
from service.core.config import FRONTEND_URL, SERVICE_NAME, SERVICE_PORT, log


app = FastAPI(title=SERVICE_NAME, version="1.0.0")


_allowed_origins = [
    os.getenv("FRONTEND_URL", FRONTEND_URL).rstrip("/"),
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


@app.get("/")
def health():
    return {"status": "ok", "service": SERVICE_NAME, "port": SERVICE_PORT}


app.include_router(chat_router)


# Khởi tạo RAG engine một lần khi import module — vì trên event lifespan
# đã làm ở router nhưng import-level dễ debug.
@app.on_event("startup")
async def _startup_global() -> None:
    log.info("rag-service started on port %s", SERVICE_PORT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=SERVICE_PORT,
        reload=False,
    )
