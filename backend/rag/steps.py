"""
The three RAG pipeline steps:
  B1. Query Understanding (LLM -> structured JSON)
  B2. Retrieval (Pinecone vector search + Neo4j context lookup)
  B3. Answer Generation (LLM with citations -> natural language answer)
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from prompts import SYSTEM_ANSWER_GENERATION, SYSTEM_QUERY_UNDERSTANDING
from rag.context import NEO4J_CONTEXT_QUERY, build_citation, build_llm_context


# ============================================================
# B1: Query Understanding
# ============================================================

def step1_query_understanding(llm, question: str) -> dict[str, Any]:
    """Use LLM to reformulate the question into a search-optimized query."""
    messages = [
        SystemMessage(content=SYSTEM_QUERY_UNDERSTANDING),
        HumanMessage(content=f"Câu hỏi của người dùng: {question}"),
    ]
    raw = llm.invoke(messages)
    content = raw.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    try:
        return json.loads(content.strip())
    except Exception:
        return {
            "reformulated_query": question,
            "legal_domain": "giao thông đường bộ",
            "key_legal_terms": [],
        }


# ============================================================
# B2: Retrieval (Pinecone + Neo4j)
# ============================================================

def step2_retrieval(engine, query: str, top_k: int) -> list[dict[str, Any]]:
    """Embed query -> Pinecone top_k -> enrich each match via Neo4j."""
    qvec = engine.get_embedder().encode(
        [query], normalize_embeddings=True, convert_to_numpy=True,
    )[0].tolist()
    res = engine.get_pinecone_index().query(
        vector=qvec, top_k=top_k, include_metadata=True,
    )
    results: list[dict[str, Any]] = []
    for match in res.matches:
        meta = match.metadata or {}
        clause_id = meta.get("clause_id") or None
        point_id  = meta.get("point_id")  or None
        with engine.neo_session() as s:
            row = s.run(
                NEO4J_CONTEXT_QUERY,
                law_id=meta["law_id"],
                chapter_id=meta["chapter_id"],
                article_id=meta["article_id"],
                clause_id=clause_id,
                point_id=point_id,
            ).single()
            ctx = dict(row) if row else {}

        doc_type = ctx.get("law_document_type") or "Văn bản"
        doc_number = ctx.get("law_document_number") or ctx.get("law_number") or ""
        results.append({
            "score": match.score,
            "vector_id": match.id,
            "type": meta.get("type"),
            "citation": build_citation(ctx),
            "law_document_type": doc_type,
            "law_document_number": doc_number,
            "law_title": ctx.get("law_title", ""),
            "law_date_enacted": ctx.get("law_date_enacted", ""),
            "context_block": build_llm_context(ctx),
        })
    return results


# ============================================================
# B3: Answer Generation
# ============================================================

def step3_answer(llm, question: str, blocks: list[dict]) -> str:
    """Ask the LLM to answer the question grounded on the retrieved blocks."""
    if not blocks:
        return "Xin lỗi, tôi không tìm thấy thông tin pháp luật liên quan để trả lời."
    context_lines = []
    for i, b in enumerate(blocks, start=1):
        context_lines.append(
            f"--- Nguồn {i} (độ tương đồng: {b['score']:.2f}) ---\n{b['context_block']}"
        )
    user_prompt = (
        f"Câu hỏi: {question}\n\nCác điều luật liên quan:\n"
        + "\n\n".join(context_lines)
    )
    resp = llm.invoke([
        SystemMessage(content=SYSTEM_ANSWER_GENERATION),
        HumanMessage(content=user_prompt),
    ])
    return resp.content