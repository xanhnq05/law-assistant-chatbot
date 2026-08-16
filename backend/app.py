"""
FastAPI entry point for the RAG Chatbot - Luật Giao thông Đường bộ.

Run:
    cd backend
    uvicorn app:app --reload --port 8000

Module layout:
    app.py         - this file: FastAPI app, lifespan, routes
    config.py      - env vars + logging
    prompts.py     - LLM system prompts
    models.py      - Pydantic request/response schemas
    rag/
        engine.py  - heavy resources (LLM, embedder, Pinecone, Neo4j)
        context.py - context formatting + citation builders
        steps.py   - B1/B2/B3 pipeline functions
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import log
from models import ChatRequest, ChatResponse, SourceItem
from rag.engine import RagEngine
from rag.steps import step1_query_understanding, step2_retrieval, step3_answer


# ============================================================
# APP
# ============================================================

engine = RagEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine.init()
    yield
    engine.close()


app = FastAPI(title="RAG Chatbot - Luật GTĐB", lifespan=lifespan)

# CORS cho frontend dev (Vite mặc định port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        # B2 - Retrieval (Pinecone + Neo4j)
        blocks = step2_retrieval(engine, understood["reformulated_query"], req.top_k)
        # B3 - Answer Generation
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