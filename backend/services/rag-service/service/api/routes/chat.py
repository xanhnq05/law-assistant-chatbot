"""RAG public route.

POST /api/chat
    request : { "question": "...", "top_k": 5 }
    response: { "answer": "...", "sources": [...], "debug": {...} }

Tái sử dụng nguyên code ở backend/rag/* để không phải duplicate.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.config import log
from core.models import ChatRequest, ChatResponse, SourceItem
from rag.engine import RagEngine
from rag.steps import (
    step1_query_understanding,
    step2_retrieval,
    step3_answer,
)


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
    """B1 → B2 → B3 pipeline."""
    if not engine.get_llm():
        return JSONResponse(
            status_code=503,
            content={"detail": "RAG engine not initialized yet"},
        )
    try:
        understood = step1_query_understanding(engine.get_llm(), req.question)
        blocks = step2_retrieval(engine, understood["reformulated_query"], req.top_k)
        answer = step3_answer(engine.get_llm(), req.question, blocks)
        return ChatResponse(
            answer=answer,
            sources=[
                SourceItem(
                    citation=b["citation"],
                    score=round(float(b["score"]), 4),
                    context_block=b["context_block"],
                    law_document_type=b.get("law_document_type", ""),
                    law_document_number=b.get("law_document_number", ""),
                    law_title=b.get("law_title", ""),
                    law_date_enacted=b.get("law_date_enacted", ""),
                )
                for b in blocks
            ],
            debug={
                "reformulated_query": understood["reformulated_query"],
                "legal_domain": understood.get("legal_domain", ""),
                "key_legal_terms": understood.get("key_legal_terms", []),
            },
        )
    except Exception as exc:
        log.exception("Chat failed")
        return JSONResponse(
            status_code=500, content={"detail": str(exc)}
        )
