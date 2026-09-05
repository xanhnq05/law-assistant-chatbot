"""
Context formatting: Neo4j row -> human-readable citation block.

Always includes *document-level* metadata (type, number, issuer,
enactment date) so the answer LLM can clearly tell which instrument
the cited provision comes from (Luật vs Nghị định vs Pháp lệnh).

Neo4j label mapping:
    :Document  (was :Law in the old schema)
"""
from __future__ import annotations

from typing import Any


NEO4J_CONTEXT_QUERY = """
MATCH (d:Document {id:$document_id})
OPTIONAL MATCH (c:Chapter {id:$chapter_id})-[:HAS_ARTICLE]->(a:Article {id:$article_id})
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(k:Clause {id:$clause_id})
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
       k.text               AS clause_text
"""


def _bool_or_str(v: Any) -> str:
    return "" if v is None else str(v)


def build_llm_context(ctx: dict[str, Any]) -> str:
    """Format a Neo4j result row into a readable citation block."""
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
    return "\n".join(parts)


def build_citation(ctx: dict[str, Any]) -> str:
    """Build a short citation string e.g. 'Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4'."""
    parts = [f"Điều {ctx.get('article_number','')}"]
    if ctx.get("clause_number"):
        parts.append(f"Khoản {ctx['clause_number']}")
    doc_type = ctx.get("document_type") or "Văn bản"
    doc_number = ctx.get("document_number") or ""
    citation_full = f"{doc_type} {doc_number}".strip()
    if citation_full:
        citation_full += " - "
    citation_full += ", ".join(parts)
    return citation_full
