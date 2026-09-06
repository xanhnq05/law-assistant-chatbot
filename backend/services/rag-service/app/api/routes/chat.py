"""RAG public route - thin wrapper around the 7-step orchestrator.

POST /api/chat
    request : { "question": "...", "top_k": 5, "verify": true }
    response: { "answer": "...", "sources": [...], "verification": {...}, "debug": {...} }
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import log
from app.core.models import ChatRequest, ChatResponse
from app.rag.engine import RagEngine
from app.rag.orchestrator import run_pipeline


router = APIRouter()

engine = RagEngine()


@router.on_event("startup")
async def _startup() -> None:
    try:
        engine.init()
    except Exception as exc:
        log.exception("RAG engine init failed: %s", exc)


@router.on_event("shutdown")
async def _shutdown() -> None:
    engine.close()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Chạy 7-step pipeline: B1 Orchestrator → B2 → ... → B7 Verification."""
    if not engine.get_llm():
        return JSONResponse(
            status_code=503,
            content={"detail": "RAG engine not initialized yet"},
        )
    try:
        response = run_pipeline(
            engine=engine,
            question=req.question,
            top_k=req.top_k,
            verify=req.verify,
        )
        return response
    except Exception as exc:
        log.exception("Chat pipeline failed")
        return JSONResponse(
            status_code=500, content={"detail": str(exc)}
        )
