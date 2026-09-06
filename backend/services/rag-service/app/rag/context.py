"""
Context formatting & citation helpers.

Hai hàm chính:
    - build_llm_context(): Neo4j row -> block text đưa cho LLM
    - build_citation():    Citation ngắn gọn (vd: "Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4")
"""
from __future__ import annotations

from typing import Any


# ============================================================
# NEO4J CONTEXT QUERY (B4 - Hybrid Retrieval)
# ============================================================
# Trả về document-level + chapter + article + clause + relationships.
# Tận dụng OPTIONAL MATCH để luôn có document header dù cấp sâu hơn thiếu.
NEO4J_CONTEXT_QUERY = """
MATCH (d:Document {id:$document_id})
OPTIONAL MATCH (c:Chapter {id:$chapter_id})-[:HAS_ARTICLE]->(a:Article {id:$article_id})
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(k:Clause {id:$clause_id})
OPTIONAL MATCH (a)-[am:AMENDS|REPLACES|REPEALS|ADDS]->(related)
OPTIONAL MATCH (a)-[am2:AMENDED_BY|REPLACED_BY|REPEALED_BY|ADDED_IN]->(related2)
RETURN d.id                 AS document_id,
       d.number             AS document_number,
       d.title              AS document_title,
       d.type               AS document_type,
       d.issuing_authority  AS document_issuing_authority,
       d.date_enacted       AS document_date_enacted,
       d.date_effective     AS document_date_effective,
       c.id                 AS chapter_id,
       c.number             AS chapter_number,
       c.title              AS chapter_title,
       a.id                 AS article_id,
       a.number             AS article_number,
       a.title              AS article_title,
       a.text               AS article_text,
       k.id                 AS clause_id,
       k.number             AS clause_number,
       k.text               AS clause_text,
       collect(DISTINCT {
           type: type(am),
           target_id: related.id,
           target_label: labels(related)[0],
           target_number: related.number,
           reason: am.reason
       }) AS forward_amendments,
       collect(DISTINCT {
           type: type(am2),
           target_id: related2.id,
           target_label: labels(related2)[0],
           target_number: related2.number,
           reason: am2.reason
       }) AS backward_amendments
"""


# ============================================================
# NEO4J CONTEXT BATCH QUERY (P0 - 1 round-trip duy nhất)
# ============================================================
# Input: list các match với (vector_id, document_id, chapter_id, article_id, clause_id)
# Output: list các row (mỗi row ứng với 1 match), có cùng shape với NEO4J_CONTEXT_QUERY
# nhưng thêm field `vector_id` để map kết quả.
#
# Hiệu năng: 1 round-trip cho N match, thay vì N round-trips.
NEO4J_CONTEXT_BATCH_QUERY = """
UNWIND $matches AS m
MATCH (d:Document {id: m.document_id})
OPTIONAL MATCH (c:Chapter {id: m.chapter_id})-[:HAS_ARTICLE]->(a:Article {id: m.article_id})
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(k:Clause {id: m.clause_id})
OPTIONAL MATCH (a)-[am:AMENDS|REPLACES|REPEALS|ADDS]->(related)
OPTIONAL MATCH (a)-[am2:AMENDED_BY|REPLACED_BY|REPEALED_BY|ADDED_IN]->(related2)
WITH m, d, c, a, k,
     collect(DISTINCT {
         type: type(am),
         target_id: related.id,
         target_label: labels(related)[0],
         target_number: related.number,
         reason: am.reason
     }) AS fwd,
     collect(DISTINCT {
         type: type(am2),
         target_id: related2.id,
         target_label: labels(related2)[0],
         target_number: related2.number,
         reason: am2.reason
     }) AS bwd
RETURN m.vector_id          AS vector_id,
       m.pinecone_score    AS pinecone_score,
       d.id                AS document_id,
       d.number            AS document_number,
       d.title             AS document_title,
       d.type              AS document_type,
       d.issuing_authority AS document_issuing_authority,
       d.date_enacted      AS document_date_enacted,
       d.date_effective    AS document_date_effective,
       c.id                AS chapter_id,
       c.number            AS chapter_number,
       c.title             AS chapter_title,
       a.id                AS article_id,
       a.number            AS article_number,
       a.title             AS article_title,
       a.text              AS article_text,
       k.id                AS clause_id,
       k.number            AS clause_number,
       k.text              AS clause_text,
       fwd                 AS forward_amendments,
       bwd                 AS backward_amendments
"""


def _bool_or_str(v: Any) -> str:
    return "" if v is None else str(v)


# ============================================================
# BUILD CITATION
# ============================================================
def build_citation(ctx: dict[str, Any]) -> str:
    """Build a short citation string e.g. 'Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4'."""
    doc_type = ctx.get("document_type") or "Văn bản"
    doc_number = ctx.get("document_number") or ""
    citation_full = f"{doc_type} {doc_number}".strip()

    article_parts = []
    if ctx.get("article_number"):
        article_parts.append(f"Điều {ctx['article_number']}")
    if ctx.get("clause_number"):
        article_parts.append(f"Khoản {ctx['clause_number']}")

    if citation_full and article_parts:
        citation_full += " - "
    citation_full += ", ".join(article_parts)
    return citation_full


# ============================================================
# BUILD LLM CONTEXT BLOCK
# ============================================================
def build_llm_context(ctx: dict[str, Any]) -> str:
    """Format a Neo4j result row into a readable citation block cho LLM.

    Luôn bao gồm *document-level* metadata (type, number, issuer,
    enactment date) để LLM phân biệt rõ Luật vs Nghị định vs Pháp lệnh.
    """
    if not ctx:
        return ""

    parts: list[str] = []
    doc_type = ctx.get("document_type") or "Văn bản"
    doc_number = ctx.get("document_number") or ""
    doc_title = ctx.get("document_title") or ""
    authority = ctx.get("document_issuing_authority") or ""
    date_en = ctx.get("document_date_enacted") or ""
    date_eff = ctx.get("document_date_effective") or ""

    header = f"{doc_type} {doc_number}".strip() + (f" - {doc_title}" if doc_title else "")
    parts.append(header)

    meta_bits = []
    if authority:
        meta_bits.append(f"Cơ quan ban hành: {authority}")
    if date_en:
        meta_bits.append(f"Ngày ban hành: {date_en}")
    if date_eff:
        meta_bits.append(f"Ngày có hiệu lực: {date_eff}")
    if meta_bits:
        parts.append("  " + " | ".join(meta_bits))

    if ctx.get("chapter_number"):
        parts.append(f"  Chương {ctx['chapter_number']}: {ctx.get('chapter_title') or ''}")
    if ctx.get("article_number"):
        parts.append(f"  Điều {ctx['article_number']}: {ctx.get('article_title') or ''}")
        if ctx.get("article_text"):
            parts.append(f"    Nội dung: {ctx['article_text']}")
    if ctx.get("clause_number"):
        parts.append(f"    Khoản {ctx['clause_number']}: {ctx.get('clause_text') or ''}")

    # Phần relationships (B5 - Context Builder sẽ dùng để highlight quan hệ)
    amendments = (ctx.get("forward_amendments") or []) + (ctx.get("backward_amendments") or [])
    rels = [a for a in amendments if a and a.get("type") and a.get("target_id")]
    if rels:
        parts.append("  Quan hệ sửa đổi/bổ sung:")
        seen = set()
        for r in rels:
            key = (r.get("type"), r.get("target_id"))
            if key in seen:
                continue
            seen.add(key)
            target_label = r.get("target_label") or ""
            target_number = r.get("target_number") or ""
            reason = r.get("reason") or ""
            parts.append(
                f"    - {r.get('type')} -> {target_label} {target_number}"
                + (f" ({reason})" if reason else "")
            )

    return "\n".join(parts)


# ============================================================
# FLATTEN AMENDMENTS (cho SourceItem)
# ============================================================
def collect_amendments(ctx: dict[str, Any]) -> list[dict[str, str]]:
    """Trả về danh sách quan hệ dạng dict ngắn cho SourceItem."""
    out: list[dict[str, str]] = []
    amendments = (ctx.get("forward_amendments") or []) + (ctx.get("backward_amendments") or [])
    seen = set()
    for r in amendments:
        if not r or not r.get("type") or not r.get("target_id"):
            continue
        key = (r.get("type"), r.get("target_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "type": r.get("type", ""),
            "target_id": r.get("target_id", ""),
            "target_label": r.get("target_label", ""),
            "target_number": r.get("target_number", ""),
            "reason": r.get("reason", ""),
        })
    return out
