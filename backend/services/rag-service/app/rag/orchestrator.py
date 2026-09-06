"""
LangChain Orchestrator - chạy toàn bộ 7-step pipeline.

Theo image 1 & 2:
  User → B1 (Orchestrator) → B2 Cleaner → B3 Embedding →
  B4 Hybrid Retrieval → B5 Context Builder → B6 LLM Generation →
  B7 Symbolic Verification → Response

State machine:
  state.question          (str)        : câu hỏi gốc
  state.cleaned           (dict)       : output của B2
  state.query_vector      (list[float]): output của B3
  state.retrieved_blocks  (list[dict]) : output của B4
  state.context_text      (str)        : output của B5
  state.answer            (str)        : output của B6
  state.verification      (VerifyResult): output của B7
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import RERANKER_ENABLED, log
from app.core.models import ChatResponse, SourceItem, VerificationResult
from app.rag.engine import RagEngine
from app.rag.steps.cleaner import step_clean_query
from app.rag.steps.context_builder import (
    build_context_for_llm,
    build_sources_for_response,
)
from app.rag.steps.embedding import step_embed_cleaned_query
from app.rag.steps.generator import step_generate_answer
from app.rag.steps.retrieval import step_retrieve_hybrid
from app.rag.steps.verification import step_verify_answer


@dataclass
class PipelineState:
    """State container cho 7-step pipeline."""

    question: str
    cleaned: dict[str, Any] = field(default_factory=dict)
    query_vector: list[float] = field(default_factory=list)
    retrieved_blocks: list[dict[str, Any]] = field(default_factory=list)
    context_text: str = ""
    answer: str = ""
    verification: VerificationResult | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


# ============================================================
# MAIN PIPELINE RUNNER
# ============================================================
def run_pipeline(
    engine: RagEngine,
    question: str,
    top_k: int = 5,
    verify: bool = True,
) -> ChatResponse:
    """
    Chạy đầy đủ 7-step pipeline và trả về ChatResponse.

    Luồng (theo image 1):
      B1. Orchestrator (hàm này)
      B2. Query Cleaner
      B3. Embedding
      B4. Hybrid Retrieval (Pinecone + Neo4j + relationships)
      B5. Context Builder
      B6. LLM Generation (Groq)
      B7. Symbolic Verification (hybrid rule + LLM-as-Judge)
    """
    if engine.get_llm() is None:
        raise RuntimeError("RAG engine chưa được khởi tạo. Gọi engine.init() trước.")

    state = PipelineState(question=question)

    # ============================================================
    # B2 - CLEANER
    # ============================================================
    log.info("[B2] Cleaning query ...")
    state.cleaned = step_clean_query(engine.get_llm(), question)

    # ============================================================
    # B3 - EMBEDDING
    # ============================================================
    log.info("[B3] Embedding cleaned query ...")
    state.query_vector = step_embed_cleaned_query(engine, state.cleaned)

    # ============================================================
    # B4 - HYBRID RETRIEVAL (Pinecone + Neo4j + relationships)
    # ============================================================
    log.info(
        "[B4] Hybrid retrieval (top_k=%d, intent=%s, reranker=%s) ...",
        top_k,
        state.cleaned.get("intent"),
        RERANKER_ENABLED,
    )
    state.retrieved_blocks = step_retrieve_hybrid(
        engine=engine,
        cleaned=state.cleaned,
        query_vector=state.query_vector,
        top_k=top_k,
        query_text=question,  # cho reranker hook (P1)
    )

    # ============================================================
    # B5 - CONTEXT BUILDER
    # ============================================================
    log.info("[B5] Building context from %d blocks ...", len(state.retrieved_blocks))
    state.context_text = build_context_for_llm(state.retrieved_blocks)
    state.sources = build_sources_for_response(state.retrieved_blocks)

    # ============================================================
    # B6 - LLM GENERATION
    # ============================================================
    log.info("[B6] Generating answer via Groq ...")
    state.answer = step_generate_answer(
        engine.get_llm(),
        question,
        state.context_text,
    )

    # ============================================================
    # B7 - SYMBOLIC VERIFICATION
    # ============================================================
    if verify:
        log.info("[B7] Verifying answer (hybrid rule + LLM-as-Judge) ...")
        state.verification = step_verify_answer(
            verifier_llm=engine.get_verifier_llm(),
            question=question,
            answer=state.answer,
            context_blocks=state.retrieved_blocks,
        )
    else:
        from app.core.models import VerificationStatus
        state.verification = VerificationResult(
            status=VerificationStatus.WARN,
            confidence=0.0,
            issues=["verification_disabled"],
        )

    # ============================================================
    # BUILD RESPONSE
    # ============================================================
    state.debug = {
        "cleaned_query": state.cleaned.get("cleaned_query", ""),
        "legal_domain": state.cleaned.get("legal_domain", ""),
        "key_legal_terms": state.cleaned.get("key_legal_terms", []),
        "intent": state.cleaned.get("intent", ""),
        "retrieved_count": len(state.retrieved_blocks),
        "context_chars": len(state.context_text),
    }

    return ChatResponse(
        answer=state.answer,
        sources=[SourceItem(**s) for s in state.sources],
        verification=state.verification,
        debug=state.debug,
    )
