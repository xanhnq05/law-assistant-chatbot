"""
B4 - Context Expansion Engine.

Mở rộng evidence từ anchor node (Pinecone hit) theo cấu trúc pháp luật:
  - SIBLINGS: các Khoản cùng Điều (HORIZONTAL)
  - PARENT:   Article (nếu anchor là Clause) hoặc Chapter (nếu anchor là Article) — UP
  - NEIGHBORS: parent + siblings + children cùng cấp

Theo PDF "tổng hợp sửa đổi các bước":
  - UP: 1 cấp
  - DOWN: 1 cấp
  - HORIZONTAL: chỉ mở rộng các Khoản cùng Điều
  - Không deep traversal mặc định

Cypher queries được viết để match schema trong app/rag/context.py:
  Document -[HAS_CHAPTER]-> Chapter -[HAS_ARTICLE]-> Article -[HAS_CLAUSE]-> Clause -[HAS_POINT]-> Point
"""
from __future__ import annotations

import logging
from typing import Any, Literal

log = logging.getLogger("rag-service")

ExpansionKind = Literal["anchor", "horizontal", "up", "down", "neighbor"]


# ============================================================
# CYPHER HELPERS
# ============================================================

# Lấy tất cả Clause cùng Article (HORIZONTAL siblings)
CYPHER_SIBLINGS_CLAUSES = """
MATCH (a:Article {id: $article_id})
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(k:Clause)
RETURN a.id AS article_id,
       a.number AS article_number,
       a.title AS article_title,
       k.id AS clause_id,
       k.number AS clause_number,
       k.text AS clause_text
"""

# Lấy toàn bộ Article con của Chapter (DOWN 1 cấp từ Chapter)
CYPHER_DOWN_CHAPTER_TO_ARTICLES = """
MATCH (c:Chapter {id: $chapter_id})
OPTIONAL MATCH (c)-[:HAS_ARTICLE]->(a:Article)
RETURN c.id AS chapter_id,
       c.number AS chapter_number,
       c.title AS chapter_title,
       a.id AS article_id,
       a.number AS article_number,
       a.title AS article_title
"""

# Lấy Chapter cha của Article (UP 1 cấp từ Article)
CYPHER_UP_ARTICLE_TO_CHAPTER = """
MATCH (a:Article {id: $article_id})
OPTIONAL MATCH (c:Chapter)-[:HAS_ARTICLE]->(a)
RETURN a.id AS article_id,
       c.id AS chapter_id,
       c.number AS chapter_number,
       c.title AS chapter_title
"""

# Lấy Article cha của Clause (UP 1 cấp từ Clause)
CYPHER_UP_CLAUSE_TO_ARTICLE = """
MATCH (k:Clause {id: $clause_id})
OPTIONAL MATCH (a:Article)-[:HAS_CLAUSE]->(k)
RETURN k.id AS clause_id,
       a.id AS article_id,
       a.number AS article_number,
       a.title AS article_title
"""

# Lấy Document header để biết status + effective
CYPHER_DOCUMENT_META = """
MATCH (d:Document {id: $document_id})
RETURN d.id AS document_id,
       d.status AS status,
       d.effective_from AS effective_from,
       d.effective_to AS effective_to
"""

# Document có amendment đang active không (nếu hết hạn mà có amendment active → vẫn tính)
CYPHER_DOC_HAS_ACTIVE_AMENDMENT = """
MATCH (a:Article {document_id: $document_id})
WHERE EXISTS {
    (a)-[:AMENDED_BY|REPLACED_BY]->(:Article)
}
RETURN a.id AS amended_article_id
LIMIT 1
"""


# ============================================================
# DOCUMENT STATUS CHECK
# ============================================================
def check_document_status(
    neo_session,
    document_id: str,
    today_iso: str,
) -> dict[str, Any]:
    """
    Check trạng thái hiệu lực của Document.

    Returns:
        {
            "is_active": bool,
            "has_active_amendment": bool,
            "status": str,
            "effective_from": str | None,
            "effective_to": str | None,
        }

    Rule:
      - status="active" + (no effective_to OR effective_to >= today) → active
      - Nếu hết hạn/bãi bỏ nhưng có active amendment → vẫn đánh dấu active
        (vì amendment mới có hiệu lực rồi)
      - Ngược lại → inactive.
    """
    fallback = {
        "is_active": True,
        "has_active_amendment": False,
        "status": "active",
        "effective_from": None,
        "effective_to": None,
    }

    if not document_id:
        return fallback

    try:
        with neo_session() as s:
            row = s.run(CYPHER_DOCUMENT_META, document_id=document_id).single()
            if not row:
                return fallback
            meta = dict(row)
            status = (meta.get("status") or "active").lower()
            eff_from = meta.get("effective_from")
            eff_to = meta.get("effective_to")

            # Check date-based active
            within_date_range = True
            if eff_from and eff_from > today_iso:
                within_date_range = False
            if eff_to and eff_to < today_iso:
                within_date_range = False

            raw_active = (status == "active") and within_date_range
            has_amend = False

            # Nếu inactive → check có amendment active không
            if not raw_active:
                amend_row = s.run(
                    CYPHER_DOC_HAS_ACTIVE_AMENDMENT, document_id=document_id
                ).single()
                has_amend = amend_row is not None

            return {
                "is_active": raw_active or has_amend,
                "has_active_amendment": has_amend,
                "status": status,
                "effective_from": eff_from,
                "effective_to": eff_to,
            }
    except Exception as exc:
        log.warning("check_document_status failed for doc=%s: %s", document_id, exc)
        return fallback


# ============================================================
# EXPANSION ENGINE
# ============================================================
def _build_block_from_clause_row(
    row: dict[str, Any], anchor_vector_id: str, document_id: str
) -> dict[str, Any] | None:
    """Build 1 expansion block từ row Clause siblings."""
    clause_id = row.get("clause_id")
    article_id = row.get("article_id")
    if not clause_id or not article_id:
        return None
    return {
        "vector_id": f"expanded:{clause_id}",
        "type": "clause",
        "expansion_kind": "horizontal",
        "expanded_from": [anchor_vector_id],
        "pinecone_score": 0.0,  # expansion không có score gốc
        "score": 0.0,           # sẽ được sắp xếp bởi B5
        "boosted": False,
        "context_block": (
            f"Điều {row.get('article_number') or ''}"
            + (f" - {row.get('article_title') or ''}" if row.get('article_title') else "")
            + (f"\n    Khoản {row.get('clause_number') or ''}: {row.get('clause_text') or ''}"
               if row.get('clause_text') else "")
        ),
        "citation": (
            f"Điều {row.get('article_number') or ''}"
            + (f", Khoản {row.get('clause_number') or ''}" if row.get('clause_number') else "")
        ),
        "law_document_id": document_id,
        "article_number": str(row.get("article_number") or ""),
        "article_title": row.get("article_title") or "",
        "clause_number": str(row.get("clause_number") or ""),
        "clause_text": row.get("clause_text") or "",
        "chapter_number": "",
        "chapter_title": "",
        "related_amendments": [],
        "pinecone_meta": {
            "type": "clause",
            "document_id": document_id,
            "article_id": article_id,
            "clause_id": clause_id,
        },
    }


def _build_block_from_article_row(
    row: dict[str, Any],
    anchor_vector_id: str,
    document_id: str,
    *,
    kind: str,
) -> dict[str, Any] | None:
    """Build 1 expansion block từ row Article (parent/down)."""
    article_id = row.get("article_id")
    if not article_id:
        return None
    clause_id = row.get("clause_id") or ""
    return {
        "vector_id": f"expanded:{article_id}{':' + clause_id if clause_id else ''}",
        "type": "clause" if clause_id else "article",
        "expansion_kind": kind,
        "expanded_from": [anchor_vector_id],
        "pinecone_score": 0.0,
        "score": 0.0,
        "boosted": False,
        "context_block": (
            f"Điều {row.get('article_number') or ''}"
            + (f" - {row.get('article_title') or ''}" if row.get('article_title') else "")
            + (f"\n    Khoản {row.get('clause_number') or ''}: {row.get('clause_text') or ''}"
               if row.get('clause_text') else "")
        ),
        "citation": (
            f"Điều {row.get('article_number') or ''}"
            + (f", Khoản {row.get('clause_number') or ''}" if row.get('clause_number') else "")
        ),
        "law_document_id": document_id,
        "article_number": str(row.get("article_number") or ""),
        "article_title": row.get("article_title") or "",
        "clause_number": str(row.get("clause_number") or ""),
        "clause_text": row.get("clause_text") or "",
        "chapter_number": str(row.get("chapter_number") or ""),
        "chapter_title": row.get("chapter_title") or "",
        "related_amendments": [],
        "pinecone_meta": {
            "type": "article" if not clause_id else "clause",
            "document_id": document_id,
            "article_id": article_id,
            "clause_id": clause_id or None,
        },
    }


def expand_anchor(
    neo_session,
    anchor_block: dict[str, Any],
    expansion: str,
) -> list[dict[str, Any]]:
    """
    Mở rộng 1 anchor block theo policy.expansion.

    Args:
        neo_session:    engine.neo_session() context manager.
        anchor_block:   1 block từ Pinecone (B4 output đã enrich).
        expansion:      "none" | "siblings" | "parent" | "neighbors"

    Returns:
        list các block mở rộng (không bao gồm anchor).
        Mỗi block có expansion_kind ∈ {"horizontal", "up", "down", "neighbor"}.
    """
    if expansion == "none" or not expansion:
        return []

    out: list[dict[str, Any]] = []
    meta = anchor_block.get("pinecone_meta") or {}
    document_id = (
        meta.get("document_id")
        or anchor_block.get("law_document_id")
        or ""
    )
    article_id = meta.get("article_id") or anchor_block.get("article_id") or ""
    clause_id = meta.get("clause_id") or anchor_block.get("clause_id") or ""
    anchor_vid = anchor_block.get("vector_id") or ""

    if not document_id:
        return []

    try:
        with neo_session() as s:
            # ---- HORIZONTAL: siblings cùng Article ----
            if expansion in ("siblings", "neighbors") and article_id and not clause_id:
                # Chỉ expand từ Article level (không từ Clause - tránh trùng)
                rows = s.run(
                    CYPHER_SIBLINGS_CLAUSES, article_id=article_id
                )
                for raw in rows:
                    row = dict(raw)
                    if not row.get("clause_id"):
                        continue
                    block = _build_block_from_clause_row(row, anchor_vid, document_id)
                    if block:
                        # Đánh dấu "neighbor" nếu policy là neighbors
                        if expansion == "neighbors":
                            block["expansion_kind"] = "neighbor"
                        out.append(block)

            # ---- UP: parent (Clause → Article, Article → Chapter) ----
            if expansion in ("parent", "neighbors"):
                if clause_id:
                    # Clause → Article
                    up_rows = s.run(CYPHER_UP_CLAUSE_TO_ARTICLE, clause_id=clause_id)
                    for raw in up_rows:
                        row = dict(raw)
                        kind = "neighbor" if expansion == "neighbors" else "up"
                        block = _build_block_from_article_row(
                            row, anchor_vid, document_id, kind=kind
                        )
                        if block:
                            out.append(block)
                elif article_id:
                    # Article → Chapter
                    up_rows = s.run(
                        CYPHER_UP_ARTICLE_TO_CHAPTER, article_id=article_id
                    )
                    for raw in up_rows:
                        row = dict(raw)
                        kind = "neighbor" if expansion == "neighbors" else "up"
                        # Chapter - chỉ là context label, không build block đầy đủ
                        chapter_id = row.get("chapter_id")
                        if chapter_id and expansion == "parent":
                            # Với parent policy, thêm Article gốc đã được expand
                            block = {
                                "vector_id": f"expanded:{anchor_vid}-chapter",
                                "type": "chapter",
                                "expansion_kind": kind,
                                "expanded_from": [anchor_vid],
                                "pinecone_score": 0.0,
                                "score": 0.0,
                                "boosted": False,
                                "context_block": (
                                    f"Chương {row.get('chapter_number') or ''}"
                                    + (f": {row.get('chapter_title') or ''}"
                                       if row.get('chapter_title') else "")
                                ),
                                "citation": f"Chương {row.get('chapter_number') or ''}",
                                "law_document_id": document_id,
                                "chapter_number": str(row.get("chapter_number") or ""),
                                "chapter_title": row.get("chapter_title") or "",
                                "article_number": "",
                                "article_title": "",
                                "clause_number": "",
                                "related_amendments": [],
                                "pinecone_meta": {
                                    "type": "chapter",
                                    "document_id": document_id,
                                    "chapter_id": chapter_id,
                                },
                            }
                            out.append(block)

            # ---- DOWN: Chapter → Articles (chỉ dùng nếu anchor ở Chapter) ----
            if expansion == "neighbors":
                # Nếu anchor là chapter-level, expand down to articles
                chapter_id = meta.get("chapter_id") or anchor_block.get("chapter_id") or ""
                if chapter_id and not article_id:
                    down_rows = s.run(
                        CYPHER_DOWN_CHAPTER_TO_ARTICLES, chapter_id=chapter_id
                    )
                    for raw in down_rows:
                        row = dict(raw)
                        block = _build_block_from_article_row(
                            row, anchor_vid, document_id, kind="neighbor"
                        )
                        if block:
                            out.append(block)
    except Exception as exc:
        log.warning("expand_anchor failed for vid=%s: %s", anchor_vid, exc)
        return out

    return out


def expand_all(
    neo_session,
    anchors: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    today_iso: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Expand tất cả anchor theo policy.

    Args:
        neo_session:    engine.neo_session() context manager.
        anchors:        list các block anchor (đã neo4j-enriched, trước expansion).
        policy:         dict từ build_retrieval_policy (chỉ dùng field "expansion").
        today_iso:      ngày hiện tại (YYYY-MM-DD) cho status filter; None = auto.

    Returns:
        (expanded_blocks, stats)
        expanded_blocks: list các block mở rộng (không bao gồm anchor).
        stats: {kind_counts, dropped_inactive}
    """
    expansion = policy.get("expansion", "none")
    if expansion == "none" or not anchors:
        return [], {"kind_counts": {}, "dropped_inactive": 0}

    expanded: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = {}

    for anchor in anchors:
        meta = anchor.get("pinecone_meta") or {}
        document_id = (
            meta.get("document_id")
            or anchor.get("law_document_id")
            or ""
        )
        # Status filter trên anchor (B4 sẽ check require_active ngoài)
        # Ở đây ta set is_active cho anchor dựa trên status check
        if document_id:
            status_info = check_document_status(
                neo_session, document_id, today_iso or _today_iso()
            )
            anchor["is_active"] = status_info["is_active"]
            anchor["effective_from"] = status_info["effective_from"]
            anchor["effective_to"] = status_info["effective_to"]

        new_blocks = expand_anchor(neo_session, anchor, expansion)
        for b in new_blocks:
            expanded.append(b)
            kind_counts[b["expansion_kind"]] = kind_counts.get(b["expansion_kind"], 0) + 1

    return expanded, {"kind_counts": kind_counts, "dropped_inactive": 0}


# ============================================================
# HELPERS
# ============================================================
def _today_iso() -> str:
    """Trả về ngày hiện tại dạng ISO YYYY-MM-DD (UTC). Cho testing có thể override."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
