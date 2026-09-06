"""rag-service entry point.

Run local:
    cd backend
    $env:PYTHONPATH="backend;backend/services/rag-service"
    uvicorn services.rag-service.app.main:app --reload --port 8003

Run Docker:
    docker compose up rag-service
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.core.config import FRONTEND_URL, SERVICE_NAME, SERVICE_PORT, log


app = FastAPI(
    title=SERVICE_NAME,
    version="2.0.0",
    description=(
        "RAG service cho chatbot pháp luật giao thông Việt Nam.\n\n"
        "Pipeline 7 bước:\n"
        "  B1. LangChain Orchestrator\n"
        "  B2. Query Cleaner\n"
        "  B3. Embedding\n"
        "  B4. Hybrid Retrieval (Pinecone + Neo4j)\n"
        "  B5. Context Builder\n"
        "  B6. LLM Generation (Groq)\n"
        "  B7. Symbolic Verification (rule + LLM-as-Judge)"
    ),
)


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
    return {"status": "ok", "service": SERVICE_NAME, "port": SERVICE_PORT, "version": "2.0.0"}


app.include_router(chat_router)


@app.on_event("startup")
async def _startup_global() -> None:
    log.info("rag-service started on port %s (pipeline v2.0)", SERVICE_PORT)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=SERVICE_PORT,
        reload=False,
    )
