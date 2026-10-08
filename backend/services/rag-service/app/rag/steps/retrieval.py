"""
B4 - Hybrid Retrieval (v3 — status filter + expansion + cleaner integration).

Cải tiến so với v2:
  P0: 1 round-trip Neo4j duy nhất (UNWIND) thay vì N round-trips.
  P1: Soft intent filter — boost score thay vì hard filter (giữ recall).
  P1: Reranker hook — optional cross-encoder sẵn sàng bật.
  P1: Pinecone metadata filter đẩy xuống DB (giảm token cost).

  --- Đợt sửa mới (B2/B4) ---
  P2: Status filter — loại Document hết hiệu lực khi policy yêu cầu require_active.
  P2: Context expansion — mở rộng anchor theo policy (siblings/parent/neighbors).
  P2: Mỗi evidence block có thêm: is_active, effective_from/to, expansion_kind,
      expanded_from (cho B5 wrap vào LegalContext).

Luồng:
  1. B4a. Vector search trên Pinecone (với metadata filter sớm).
  2. B4b. Soft intent boost: cộng thêm score cho match đúng document_type.
  3. B4c. Neo4j batch enrich (UNWIND): 1 query duy nhất cho tất cả match.
  4. B4d. Status filter (MỚI): drop inactive nếu policy yêu cầu.
  5. B4e. Rerank (optional): nếu có reranker model, rerank lại top_k.
  6. B4f. Context expansion (MỚI): mở rộng anchor theo policy (siblings/parent).
  7. Trả về list Hit đã được enrich + expand.
"""
from __future__ import annotations

from typing import Any

from app.core.config import PINECONE_TOP_K, RERANKER_ENABLED, RERANKER_TOP_N, log
from app.rag.context import (
    NEO4J_CONTEXT_BATCH_QUERY,
    build_citation,
    build_llm_context,
    collect_amendments,
)
from app.rag.steps.expansion import expand_all


# ============================================================
# INTENT BOOST (P1 - soft filter)
# ============================================================
_INTENT_BOOST = {
    "penalty_lookup": {"nghị định": 0.08, "nghi dinh": 0.08},
    "rule_lookup": {"luật": 0.08, "luat": 0.08},
    "procedure_lookup": {"luật": 0.04, "luật": 0.04},  # thủ tục thường nằm ở Luật
}


def _soft_intent_boost(intent: str, meta: dict[str, Any], base_score: float) -> float:
    """Cộng thêm score nhỏ cho match đúng document_type theo intent."""
    boost_map = _INTENT_BOOST.get(intent)
    if not boost_map:
        return base_score
    doc_type = (meta.get("document_type") or "").lower()
    boost = boost_map.get(doc_type, 0.0)
    return base_score + boost


# ============================================================
# RERANKER HOOK (P1)
# ============================================================
class _NoOpReranker:
    """Reranker giả khi không bật model — pass-through."""

    def rerank(self, query: str, blocks: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        return blocks[:top_n]


def _build_reranker():
    """Factory: trả reranker thật nếu bật, else NoOp."""
    if not RERANKER_ENABLED:
        return _NoOpReranker()
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        log.info("Loading reranker model ...")
        model = CrossEncoder("BAAI/bge-reranker-v2-m3")
        return _CrossEncoderReranker(model)
    except Exception as exc:
        log.warning("Reranker load failed (%s) — dùng NoOp.", exc)
        return _NoOpReranker()


class _CrossEncoderReranker:
    """Cross-encoder reranker thật (dùng khi RERANKER_ENABLED=true)."""

    def __init__(self, model):
        self.model = model

    def rerank(self, query: str, blocks: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        if not blocks:
            return []
        pairs = [(query, b.get("context_block", "")[:512]) for b in blocks]
        scores = self.model.predict(pairs)
        for b, s in zip(blocks, scores):
            b["rerank_score"] = float(s)
        blocks = sorted(blocks, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
        return blocks[:top_n]


# ============================================================
# PINECONE METADATA FILTER (P1)
# ============================================================
def _build_pinecone_filter(intent: str) -> dict[str, Any] | None:
    """
    Trả về filter expression cho Pinecone query (đẩy xuống DB).
    Hiện tại trả None — để soft-boost xử lý (giữ recall).
    """
    return None


# ============================================================
# STATUS FILTER HELPER (MỚI)
# ============================================================
def _enrich_with_status(
    engine,
    blocks: list[dict[str, Any]],
) -> None:
    """Đánh dấu is_active/effective_from/to cho mỗi block (in-place).

    Dùng session riêng cho mỗi document_id (dedup trước để tránh query trùng).
    """
    seen_doc_ids: dict[str, dict[str, Any]] = {}
    for b in blocks:
        meta = b.get("pinecone_meta") or {}
        doc_id = meta.get("document_id") or b.get("law_document_id")
        if not doc_id or doc_id in seen_doc_ids:
            continue
        # Import ở runtime để tránh circular
        from app.rag.steps.expansion import check_document_status
        status_info = check_document_status(engine.neo_session, doc_id, _today_iso())
        seen_doc_ids[doc_id] = status_info

    for b in blocks:
        meta = b.get("pinecone_meta") or {}
        doc_id = meta.get("document_id") or b.get("law_document_id")
        if doc_id and doc_id in seen_doc_ids:
            info = seen_doc_ids[doc_id]
            b["is_active"] = info["is_active"]
            b["effective_from"] = info["effective_from"]
            b["effective_to"] = info["effective_to"]


def _today_iso() -> str:
    """Trả về ngày hiện tại UTC ISO."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ============================================================
# MAIN: B4 - HYBRID RETRIEVAL
# ============================================================
def step_retrieve_hybrid(
    engine,
    cleaned: dict[str, Any],
    query_vector: list[float],
    top_k: int = 5,
    extra_top_k: int | None = None,
    query_text: str | None = None,
) -> list[dict[str, Any]]:
    """
    B4: Hybrid Retrieval v3 (status filter + expansion đã apply).

    Args:
        engine:        RagEngine instance.
        cleaned:       output B2 (chứa 'intent', 'cleaned_query', 'retrieval_policy').
        query_vector:  embedding vector.
        top_k:         số lượng kết quả cuối.
        extra_top_k:   lấy dư từ Pinecone (mặc định = PINECONE_TOP_K).
        query_text:    text gốc để rerank (nếu có reranker).

    Returns:
        list các dict (đã enrich + status filter + expand theo policy).

    Backward-compat:
      - Vẫn trả về list dict có các field cũ: citation, context_block, scores,...
      - Thêm field mới: is_active, effective_from/to, expansion_kind, expanded_from.
    """
    pinecone_top = extra_top_k or PINECONE_TOP_K
    intent = cleaned.get("intent", "general_info")
    policy = cleaned.get("retrieval_policy") or {}
    index = engine.get_pinecone_index()
    if index is None:
        raise RuntimeError("Pinecone index chưa được khởi tạo.")

    # ============================================================
    # B4a. Pinecone vector search (P1: metadata filter sớm)
    # ============================================================
    pinecone_filter = _build_pinecone_filter(intent)
    raw_matches = index.query(
        vector=query_vector,
        top_k=pinecone_top,
        include_metadata=True,
        filter=pinecone_filter,
    ).matches or []

    if not raw_matches:
        log.info("Hybrid retrieval: Pinecone trả về 0 match.")
        return []

    # ============================================================
    # B4b. Soft intent boost (P1) — KHÔNG hard filter
    # ============================================================
    boosted: list[tuple[float, Any]] = []
    for m in raw_matches:
        meta = m.metadata or {}
        new_score = _soft_intent_boost(intent, meta, m.score or 0.0)
        boosted.append((new_score, m))
    boosted.sort(key=lambda x: x[0], reverse=True)

    # ============================================================
    # B4c. Neo4j batch enrich (P0: 1 round-trip duy nhất)
    # ============================================================
    batch_matches: list[tuple[float, Any]] = boosted[:pinecone_top]
    batch_params = []
    scored_ids: list[str] = []
    match_by_id: dict[str, tuple[float, Any]] = {}
    for score, m in batch_matches:
        meta = m.metadata or {}
        document_id = meta.get("document_id")
        article_id = meta.get("article_id")
        if not document_id or not article_id:
            log.warning("Match thiếu document_id/article_id: %s", m.id)
            continue
        scored_ids.append(m.id)
        match_by_id[m.id] = (score, m)
        batch_params.append({
            "vector_id": m.id,
            "document_id": document_id,
            "chapter_id": meta.get("chapter_id") or None,
            "article_id": article_id,
            "clause_id": meta.get("clause_id") or None,
            "pinecone_score": score,
        })

    if not batch_params:
        return []

    # 1 query duy nhất!
    ctx_rows: list[dict[str, Any]] = []
    try:
        with engine.neo_session() as s:
            result = s.run(NEO4J_CONTEXT_BATCH_QUERY, matches=batch_params)
            ctx_rows = [dict(r) for r in result]
    except Exception as exc:
        log.exception("Neo4j batch enrich failed: %s", exc)
        ctx_rows = []

    # Index kết quả theo vector_id
    ctx_by_vid: dict[str, dict[str, Any]] = {r.get("vector_id", ""): r for r in ctx_rows}

    # ============================================================
    # Build initial blocks
    # ============================================================
    results: list[dict[str, Any]] = []
    for vid in scored_ids:
        ctx = ctx_by_vid.get(vid, {})
        score, m = match_by_id[vid]
        meta = m.metadata or {}
        results.append({
            "score": score,
            "pinecone_score": m.score,
            "boosted": abs(score - (m.score or 0.0)) > 1e-6,
            "vector_id": vid,
            "type": meta.get("type"),
            "citation": build_citation(ctx) if ctx else "",
            "context_block": build_llm_context(ctx) if ctx else "",
            "law_document_type": (ctx.get("document_type") or ""),
            "law_document_number": (ctx.get("document_number") or ""),
            "law_document_id": meta.get("document_id") or "",
            "law_title": (ctx.get("document_title") or ""),
            "law_date_enacted": (ctx.get("document_date_enacted") or ""),
            "law_date_effective": (ctx.get("document_date_effective") or ""),
            "law_issuing_authority": (ctx.get("document_issuing_authority") or ""),
            "chapter_number": str(ctx.get("chapter_number") or meta.get("chapter_number") or ""),
            "chapter_title": (ctx.get("chapter_title") or meta.get("chapter_title") or ""),
            "article_number": str(ctx.get("article_number") or meta.get("article_number") or ""),
            "article_title": (ctx.get("article_title") or meta.get("article_title") or ""),
            "clause_number": str(ctx.get("clause_number") or meta.get("clause_number") or ""),
            "related_amendments": collect_amendments(ctx),
            "pinecone_meta": meta,
            # --- B4 mới ---
            "is_active": True,       # default, sẽ được update bởi _enrich_with_status
            "effective_from": None,
            "effective_to": None,
            "expansion_kind": "anchor",
            "expanded_from": [],
        })

    # ============================================================
    # B4d. Status filter (MỚI)
    # ============================================================
    _enrich_with_status(engine, results)

    require_active = policy.get("filters", {}).get("require_active", False)
    if require_active:
        before = len(results)
        results = [b for b in results if b.get("is_active", True)]
        log.info("Status filter: %d → %d (require_active=True)", before, len(results))
    # Nếu require_active=False: giữ tất cả, B6/B7 sẽ cảnh báo evidence inactive.

    # ============================================================
    # B4e. Rerank (P1 - optional hook)
    # ============================================================
    reranker = _build_reranker()
    if query_text:
        results = reranker.rerank(query_text, results, top_n=min(top_k, RERANKER_TOP_N))
    else:
        results = results[:top_k]

    # ============================================================
    # B4f. Context Expansion (MỚI - theo policy)
    # ============================================================
    expansion_kind = policy.get("expansion", "none")
    if expansion_kind and expansion_kind != "none" and results:
        expanded_blocks, expansion_stats = expand_all(
            engine.neo_session, results, policy
        )
        if expanded_blocks:
            results = results + expanded_blocks
            log.info(
                "Context expansion: %d expanded (%s)",
                len(expanded_blocks),
                expansion_stats.get("kind_counts", {}),
            )

    log.info(
        "Hybrid retrieval: %d final blocks (boosted=%d, expanded=%d, reranked=%s)",
        len(results),
        sum(1 for r in results if r.get("boosted")),
        sum(1 for r in results if r.get("expansion_kind") != "anchor"),
        RERANKER_ENABLED,
    )
    return results
