"""
LangChain Orchestrator - chạy toàn bộ 7-step pipeline.

Theo image 1 & 2:
  User → B1 (Orchestrator) → B2 Cleaner → B3 Embedding →
  B4 Hybrid Retrieval → B5 Context Builder → B6 LLM Generation →
  B7 Symbolic Verification → Response

State machine:
  state.question          (str)            : câu hỏi gốc
  state.cleaned           (dict)           : output của B2
  state.query_vector      (list[float])    : output của B3
  state.retrieved_blocks  (list[dict])     : output của B4 (raw)
  state.legal_context     (LegalContext)   : output của B5 (B5 official contract)
  state.context_text      (str)            : alias của legal_context.formatted_context
                                             (giữ cho back-compat với B6 cũ)
  state.answer            (str)            : output của B6
  state.verification      (VerifyResult)   : output của B7
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config import RERANKER_ENABLED, log
from app.core.models import ChatResponse, SourceItem, VerificationResult
from app.rag.engine import RagEngine
from app.rag.schemas.legal_context import LegalContext
from app.rag.steps.cleaner import step_clean_query
from app.rag.steps.context_builder import (
    build_context_for_llm,
    build_legal_context,
    build_sources_for_response,
)
from app.rag.steps.embedding import step_embed_cleaned_query
from app.rag.steps.generator import step_generate_answer
from app.rag.steps.retrieval import step_retrieve_hybrid
from app.rag.steps.verification import step_verify_answer


# ============================================================
# CONFIG
# ============================================================
# Cap evidence B5 đưa vào LegalContext (để B6 prompt không bị tràn).
# B6 vẫn còn MAX_CONTEXT_CHARS=6000 như một lớp an toàn thứ 2.
B5_MAX_EVIDENCE = 10


@dataclass
class PipelineState:
    """State container cho 7-step pipeline."""

    question: str
    cleaned: dict[str, Any] = field(default_factory=dict)
    query_vector: list[float] = field(default_factory=list)
    retrieved_blocks: list[dict[str, Any]] = field(default_factory=list)
    legal_context: LegalContext | None = None  # B5 official contract
    context_text: str = ""  # alias legal_context.formatted_context (back-compat B6)
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
    history: list[dict[str, str]] | None = None,
) -> ChatResponse:
    """
    Chạy đầy đủ 7-step pipeline và trả về ChatResponse.

    Luồng (theo image 1):
      B1. Orchestrator (hàm này)
      B2. Query Cleaner
      B3. Embedding
      B4. Hybrid Retrieval (Pinecone + Neo4j + relationships)
      B5. Context Builder
      B6. LLM Generation (Groq) — nhận thêm history để multi-turn
      B7. Symbolic Verification (hybrid rule + LLM-as-Judge)

    Args:
        history: danh sách {role: "user"|"assistant", content: str} gần đây.
                 Tối đa 3 cặp (6 message) để tránh hết context window.
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
    # B5 - CONTEXT BUILDER (LegalContext — official B5 contract)
    # ============================================================
    log.info(
        "[B5] Building LegalContext from %d blocks (max_evidence=%d) ...",
        len(state.retrieved_blocks),
        B5_MAX_EVIDENCE,
    )
    # retrieval_query ưu tiên từ B3 enriched (cleaned + key_terms).
    # B3 đã có hàm step_embed_cleaned_query trả vector, nhưng text enriched
    # ta reconstruct lại ở đây để LegalContext.request.retrieval_query là
    # chính xác text đã embed.
    rq_parts = [state.cleaned.get("cleaned_query") or state.question]
    terms = state.cleaned.get("key_legal_terms") or []
    if terms:
        rq_parts.append("Thuật ngữ: " + " ".join(terms[:5]))
    retrieval_query = "\n".join(rq_parts)

    state.legal_context = build_legal_context(
        question=state.question,
        cleaned=state.cleaned,
        retrieved_blocks=state.retrieved_blocks,
        retrieval_query=retrieval_query,
        max_evidence=B5_MAX_EVIDENCE,
    )
    # Back-compat: B6 cũ đọc context_text (string). alias từ formatted_context.
    state.context_text = state.legal_context.formatted_context
    # Back-compat: API response vẫn trả sources[] (SourceItem model).
    state.sources = build_sources_for_response(state.retrieved_blocks)

    log.info(
        "[B5] LegalContext ready: %d evidence, %d citations, %d docs, ctx_chars=%d",
        len(state.legal_context.evidence),
        len(state.legal_context.citations),
        len(state.legal_context.hierarchy.documents),
        len(state.context_text),
    )

    # ============================================================
    # B6 - LLM GENERATION
    # ============================================================
    log.info("[B6] Generating answer via Groq (history=%d msgs) ...", len(history or []))
    state.answer = step_generate_answer(
        engine.get_llm(),
        question,
        state.context_text,
        history=history,
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
            # B5 LegalContext ưu tiên hơn raw retrieved_blocks
            # (B7 sẽ dùng citation ↔ evidence mapping để verify).
            legal_context=state.legal_context,
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
        # B5 LegalContext stats (cho debug + B7)
        "legal_context": {
            "evidence_count": len(state.legal_context.evidence) if state.legal_context else 0,
            "citation_count": len(state.legal_context.citations) if state.legal_context else 0,
            "hierarchy_docs": (
                len(state.legal_context.hierarchy.documents) if state.legal_context else 0
            ),
            "stats": state.legal_context.stats if state.legal_context else {},
        },
    }

    return ChatResponse(
        answer=state.answer,
        sources=[SourceItem(**s) for s in state.sources],
        verification=state.verification,
        debug=state.debug,
    )
