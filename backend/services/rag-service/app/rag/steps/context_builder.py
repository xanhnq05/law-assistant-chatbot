"""
B5 - Context Builder (public surface).

Public functions:
    - build_context_for_llm(blocks): str       — backward-compat (giữ nguyên)
    - build_sources_for_response(blocks): list — backward-compat (giữ nguyên)
    - build_legal_context(...): LegalContext   — NEW: contract chính thức B5 → B6/B7

B5 là contract/interface giữa B4 (Retrieval) và B6/B7 (Gen + Verify).
Tuyệt đối KHÔNG gọi LLM, KHÔNG suy luận legal content, KHÔNG retrieval lại.

Backward compatibility:
    - 2 hàm cũ KHÔNG đổi signature / output. Orchestrator cũ vẫn chạy được.
    - LegalContext là lớp trừu tượng mới; B6/B7 nên migrate dần sang dùng nó.
"""
from __future__ import annotations

from typing import Any

from app.rag.context import build_citation, build_llm_context, collect_amendments
from app.rag.schemas.legal_context import (
    LegalContext,
    LegalContextBuilder,
    RequestInfo,
)


# ============================================================
# BACKWARD-COMPAT: format LLM-ready text + sources
# ============================================================
def build_context_for_llm(blocks: list[dict[str, Any]]) -> str:
    """
    Tổng hợp list blocks (output của B4) thành 1 chuỗi context cho LLM.

    Format:
        --- Nguồn 1 (độ tương đồng: 0.87) ---
        <context_block>
        (Quan hệ: AMENDS -> Article 6 of Nghị định 168)

        --- Nguồn 2 ...

    Lưu ý:
      - Dedup: nếu 2 blocks có cùng citation → chỉ giữ block có score cao hơn.
      - Nếu có related_amendments: highlight để LLM chú ý văn bản đang hiệu lực.
    """
    if not blocks:
        return ""

    # ============================================================
    # 1. Dedup theo citation (giữ block score cao nhất)
    # ============================================================
    seen: dict[str, dict[str, Any]] = {}
    for b in blocks:
        citation = b.get("citation") or b.get("vector_id") or ""
        if not citation:
            continue
        if citation not in seen or seen[citation]["score"] < b["score"]:
            seen[citation] = b

    deduped = list(seen.values())

    # ============================================================
    # 2. Sắp xếp theo score giảm dần
    # ============================================================
    deduped.sort(key=lambda b: b.get("score", 0.0), reverse=True)

    # ============================================================
    # 3. Format LLM-ready
    # ============================================================
    lines: list[str] = []
    for i, b in enumerate(deduped, start=1):
        score = b.get("score", 0.0)
        header = f"--- Nguồn {i} (độ tương đồng: {score:.3f}) ---"
        body = b.get("context_block") or ""
        lines.append(header)
        if body:
            lines.append(body)
        # Highlight quan hệ nếu có
        rels = b.get("related_amendments") or []
        if rels:
            rel_text = "; ".join(
                f"{r.get('type')} -> {r.get('target_label','')} {r.get('target_number','')}"
                + (f" ({r.get('reason')})" if r.get("reason") else "")
                for r in rels[:3]
            )
            lines.append(f"[Quan hệ: {rel_text}]")
        lines.append("")

    return "\n".join(lines).strip()


def build_sources_for_response(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert list blocks (B4) thành list SourceItem-serializable dicts.

    Dedup theo citation để FE không hiển thị trùng.
    """
    seen: dict[str, dict[str, Any]] = {}
    for b in blocks:
        citation = b.get("citation") or b.get("vector_id") or ""
        if not citation:
            continue
        if citation not in seen or seen[citation]["score"] < b["score"]:
            seen[citation] = {
                "citation": citation,
                "score": round(float(b.get("score", 0.0)), 4),
                "context_block": b.get("context_block") or "",
                "law_document_type": b.get("law_document_type", ""),
                "law_document_number": b.get("law_document_number", ""),
                "law_title": b.get("law_title", ""),
                "law_date_enacted": b.get("law_date_enacted", ""),
                "law_date_effective": b.get("law_date_effective", ""),
                "law_issuing_authority": b.get("law_issuing_authority", ""),
                "chapter_number": b.get("chapter_number", ""),
                "chapter_title": b.get("chapter_title", ""),
                "article_number": b.get("article_number", ""),
                "article_title": b.get("article_title", ""),
                "clause_number": b.get("clause_number", ""),
                "related_amendments": b.get("related_amendments", []),
            }

    items = list(seen.values())
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


# ============================================================
# NEW: BUILD LEGAL CONTEXT (B5 official contract)
# ============================================================
def build_legal_context(
    *,
    question: str,
    cleaned: dict[str, Any],
    retrieved_blocks: list[dict[str, Any]],
    retrieval_query: str | None = None,
    max_evidence: int = 10,
) -> LegalContext:
    """Build LegalContext (B5 official output) từ:
        - `question`              : raw user query (từ B1)
        - `cleaned`               : B2 output (cleaned_query, intent, ...)
        - `retrieved_blocks`      : B4 output (list[dict])
        - `retrieval_query`       : B3 enriched query (mặc định = cleaned_query + terms)
        - `max_evidence`          : cap số evidence cho B6 context window

    Returns:
        LegalContext (Pydantic). Gồm:
            - request     (echo từ B2/B3)
            - evidence[]  (structured source of truth)
            - hierarchy   (group theo Document→Chapter→Article→Clause)
            - formatted_context (LLM-ready string, reuse build_context_for_llm)
            - citations[] (1-1 với evidence, có FK evidence_id)
            - stats       (cho B7 + debug)

    Lưu ý:
        - Hàm này KHÔNG gọi LLM, KHÔNG retrieval.
        - `formatted_context` reuse `build_context_for_llm()` cũ để
          KHÔNG phá vỡ format mà B6 đã test.
        - `evidence` và `citations` derive từ B4 block + dedup theo stable_id.
    """
    # Build RequestInfo
    key_terms = list(cleaned.get("key_legal_terms") or [])
    normalized = str(cleaned.get("cleaned_query") or question or "")
    if retrieval_query is None:
        if key_terms:
            retrieval_query = f"{normalized}\nThuật ngữ: {' '.join(key_terms[:5])}"
        else:
            retrieval_query = normalized

    request = RequestInfo(
        original_query=str(question or ""),
        normalized_query=normalized,
        retrieval_query=retrieval_query,
        language="vi",  # project hiện chỉ VI; để configurable sau
        intent=str(cleaned.get("intent") or "general_info"),
        legal_domain=str(cleaned.get("legal_domain") or ""),
        key_terms=key_terms,
    )

    # Reuse existing formatter để B6 không phải đổi
    formatted_context = build_context_for_llm(retrieved_blocks)

    builder = LegalContextBuilder(max_evidence=max_evidence)
    return builder.build(
        request=request,
        retrieved_blocks=retrieved_blocks,
        formatted_context=formatted_context,
    )
