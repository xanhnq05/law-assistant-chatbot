"""
FastAPI entry point for the RAG Chatbot - Luật Giao thông Đường bộ.

Run:
    cd backend
    uvicorn app:app --reload --port 8000

Module layout:
    app.py         - this file: FastAPI app, lifespan, routes
    config.py      - env vars + logging
    models.py      - Pydantic request/response schemas (RAG)
    routers/       - auth_router, chat_router
    rag/
        engine.py  - heavy resources (LLM, embedder, Pinecone, Neo4j)
        steps.py   - B1/B2/B3 pipeline functions
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from core.config import log
from core.models import ChatRequest, ChatResponse, SourceItem
from rag.engine import RagEngine
from rag.steps import step1_query_understanding, step2_retrieval, step3_answer
from routers import auth_router, chat_router


# ============================================================
# APP
# ============================================================

engine = RagEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        engine.init()
    except Exception as exc:
        log.exception("RAG engine init failed: %s", exc)
    yield
    engine.close()


app = FastAPI(title="RAG Chatbot - Luật GTĐB", lifespan=lifespan)

# SessionMiddleware bắt buộc cho Authlib OAuth (lưu state chống CSRF).
# Đổi secret_key thành giá trị random an toàn trong production.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("JWT_SECRET_KEY", "tlpl-dev-secret-change-me"),
    same_site="lax",
    https_only=False,  # dev: chưa cần HTTPS
)


# ============================================================
# CORS - whitelist frontend
# ============================================================
# Mặc định cho phép localhost dev + URL đã cấu hình trong FRONTEND_URL.
# Trong production nên set FRONTEND_URL=https://your-frontend.com.
_allowed_origins = [
    os.getenv("FRONTEND_URL", "http://localhost:5500").rstrip("/"),
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
# de-dup + loại bỏ None / rỗng
_allowed_origins = [o for o in {o for o in _allowed_origins if o}]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROUTES
# ============================================================

@app.get("/")
def health():
    return {"status": "ok", "service": "rag-chatbot"}


# ============================================================
# AUTH ROUTES
# ============================================================

app.include_router(auth_router)

# ============================================================
# CHAT HISTORY ROUTES
# ============================================================

app.include_router(chat_router)


# ============================================================
# RAG PUBLIC CHAT (không cần auth)
# ============================================================

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """B1 → B2 → B3 pipeline."""
    if not engine.get_llm():
        return JSONResponse(
            status_code=503,
            content={"detail": "Engine not initialized yet"},
        )
    try:
        # B1 - Query Understanding
        understood = step1_query_understanding(engine.get_llm(), req.question)
        # B2 - Retrieval
        blocks = step2_retrieval(engine, understood["reformulated_query"], req.top_k)
        # B3 - Answer
        answer = step3_answer(engine.get_llm(), req.question, blocks)
        return ChatResponse(
            answer=answer,
            sources=[SourceItem(
                citation=b["citation"],
                score=round(float(b["score"]), 4),
                context_block=b["context_block"],
                law_document_type=b.get("law_document_type", ""),
                law_document_number=b.get("law_document_number", ""),
                law_title=b.get("law_title", ""),
                law_date_enacted=b.get("law_date_enacted", ""),
            ) for b in blocks],
            debug={
                "reformulated_query": understood["reformulated_query"],
                "legal_domain": understood.get("legal_domain", ""),
                "key_legal_terms": understood.get("key_legal_terms", []),
            },
        )
    except Exception as e:
        log.exception("Chat failed")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)},
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)