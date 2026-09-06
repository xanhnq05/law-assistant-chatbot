"""
B5 - Context Builder.

Sắp xếp, dedup và format các block context từ B4 thành 1 prompt-ready
text đưa cho LLM ở B6.

Chiến lược:
  - Sắp xếp theo score giảm dần (vector similarity).
  - Dedup theo citation (cùng 1 article nhưng nhiều match → chỉ giữ 1).
  - Highlight quan hệ AMEND/REPLACE/REPEAL nếu có.
  - Build 1 system-friendly string cho LLM.
"""
from __future__ import annotations

from typing import Any


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
