"""RAG public route - thin wrapper around the orchestrator (B1-B8).

POST /api/chat
    request : {
        "question": "...",
        "top_k": 5,
        "verify": true,
        "history": [...],            # optional, overridden by session_id if provided
        "session_id": "...",         # optional, for Memory Manager
        "generate_followups": true   # optional, B8 toggle
    }
    response: {
        "answer": "...",
        "sources": [...],
        "verification": {...},
        "followups": [...],           # B8 output
        "debug": {...}
    }
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import log
from app.core.models import ChatRequest, ChatResponse
from app.rag.engine import RagEngine
from app.rag.memory import shutdown_memory
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
    # Cleanup background summarizer thread của Memory Manager
    shutdown_memory()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Chạy pipeline: B1 Orchestrator → B2 → ... → B8 Follow-up.

    Mới (B2/B4 đợt sửa):
      - req.session_id: nếu có → load/save memory in-process.
      - req.history: legacy — dùng khi KHÔNG có session_id.
      - req.generate_followups: bật/tắt B8 (default True).
    """
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
            history=req.history or None,
            session_id=req.session_id or None,
            generate_followups=req.generate_followups,
        )
        return response
    except Exception as exc:
        log.exception("Chat pipeline failed")
        return JSONResponse(
            status_code=500, content={"detail": str(exc)}
        )
