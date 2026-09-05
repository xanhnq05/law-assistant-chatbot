"""
Import legal documents and their relationships into Neo4j.

Structure:
    Document (Law/Nghị định/...)
      └── Chapter
            └── Article
                  └── Clause
                        └── Point

Input:
    - doc/document/*.json     : Các văn bản luật (mỗi file = 1 document)
    - doc/relationship/*.json : Quan hệ sửa đổi/bổ sung/thay thế/bãi bỏ
                                giữa các node nhỏ (article/clause/point) của
                                2 document khác nhau.

Output (Neo4j):
    Nodes: Document, Chapter, Article, Clause, Point
    Edges:
        - (:Document)-[:HAS_CHAPTER]->(:Chapter)
        - (:Chapter)-[:HAS_ARTICLE]->(:Article)
        - (:Article)-[:HAS_CLAUSE]->(:Clause)
        - (:Clause)-[:HAS_POINT]->(:Point)
        - (node_a)-[:AMENDS|ADDS|REPLACES|REPEALS]->(node_b)
        - (node_b)-[:AMENDED_BY|ADDED_IN|REPLACED_BY|REPEALED_BY]->(node_a)
          (chiều ngược lại, tiện cho truy xuất)

Usage:
    cd data_import
    python import_data_neo4j.py

Env (.env hoặc env_data_import.env):
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from neo4j import GraphDatabase


# ============================================================
# 1. LOGGING & CONFIG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("legal-graph")

# Load env from data_import/.env (ưu tiên) rồi mới đến backend/.env nếu có.
_load_paths = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent / "env_data_import.env",
    Path(__file__).resolve().parent.parent / "backend" / ".env",
]
for p in _load_paths:
    if p.exists():
        load_dotenv(p, override=False)

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

if not all([NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD]):
    log.error("Missing one of: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD")
    sys.exit(1)


# ============================================================
# 2. PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DOC_DOCUMENT_DIR = (ROOT_DIR / "doc" / "document").resolve()
DOC_RELATIONSHIP_DIR = (ROOT_DIR / "doc" / "relationship").resolve()

for d, name in [
    (DOC_DOCUMENT_DIR, "doc/document"),
    (DOC_RELATIONSHIP_DIR, "doc/relationship"),
]:
    if not d.exists():
        log.error(f"Folder not found: {name} -> {d}")
        sys.exit(1)


# ============================================================
# 3. LOAD JSON FILES
# ============================================================

def load_documents(folder: Path) -> list[dict[str, Any]]:
    """Load all *.json under folder. Skip schema/relationship files."""
    docs: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        name = path.name.lower()
        if name.endswith(".schema.json") or "schema" in name:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            docs.append(obj)
            log.info("Loaded document: %s (id=%s)", path.name,
                     obj.get("document", {}).get("id", "?"))
        except Exception as e:
            log.exception("Failed to read %s: %s", path.name, e)
    if not docs:
        log.error("No document JSON found in %s", folder)
        sys.exit(1)
    return docs


def load_relationships(folder: Path) -> list[dict[str, Any]]:
    """Load all relationship *.json files. Skip schema files."""
    rels: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        if "schema" in path.name.lower():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if "relationships" in obj:
                rels.append(obj)
                log.info("Loaded relationship: %s (src=%s -> tgt=%s, %d edges)",
                         path.name,
                         obj.get("source_document"),
                         obj.get("target_document"),
                         len(obj.get("relationships", [])))
        except Exception as e:
            log.exception("Failed to read relationship %s: %s", path.name, e)
    return rels


# ============================================================
# 4. HELPERS
# ============================================================

def _safe_str(v: Any) -> str | None:
    """Trim string or return None. Avoid storing empty strings."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return v


def _infer_document_type(doc: dict[str, Any]) -> str:
    """Đoán loại văn bản: 'Luật', 'Nghị định', 'Pháp lệnh', 'Văn bản'."""
    t = _safe_str(doc.get("type"))
    if t:
        return t
    law_id = (doc.get("id") or "").upper()
    if law_id.startswith("L"):
        return "Luật"
    if law_id.startswith("PL"):
        return "Pháp lệnh"
    return "Văn bản"


def normalize_node_id(target_ref: str, source_doc_id: str, target_doc_id: str) -> str | None:
    """
    Convert short ref like 'A6.K3.Pm' or 'A6.K1a' into a full Neo4j node id
    theo format id thực tế của dữ liệu: '<doc>-A-<art>-K<clause>-P<point>'

    Format examples (target_ref):
        A42                -> Article '42'                  -> '<doc>-A-42'
        A6.K3              -> Clause '3' of Article '6'     -> '<doc>-A-6-K3'
        A6.K3.Pm           -> Point 'm' of Clause '3'...    -> '<doc>-A-6-K3-Pm'
        A6.K1a             -> Clause '1a' of Article '6'    -> '<doc>-A-6-K1a'

    Return: full node id, or None if not parseable.
    """
    if not target_ref:
        return None

    ref = target_ref.strip()
    # Không upper() phần nhãn điểm (vd: 'Pi', 'Pđ', 'Pk1') vì trong DB lưu
    # nguyên case từ JSON gốc. Chỉ upper phần prefix 'A' và 'K'.
    m = re.match(r"^[Aa](\d+)(?:\.[Kk](\d+\w*)(?:\.([Pp]\w+))?)?$", ref)
    if not m:
        return None

    article_num, clause_num, point_label = m.groups()
    # Format thực tế: D168-2024-ND-CP-A-6-K3-Pm (giữ nguyên case của point label)
    parts = [target_doc_id, "A", article_num]
    if clause_num:
        parts.append(f"K{clause_num}")
    if point_label:
        parts.append(point_label)
    return "-".join(parts)


# ============================================================
# 5. NEO4J: CONSTRAINTS
# ============================================================

CONSTRAINT_QUERIES = [
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (n:Chapter)   REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article)   REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT clause_id IF NOT EXISTS FOR (n:Clause)     REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT point_id IF NOT EXISTS FOR (n:Point)       REQUIRE n.id IS UNIQUE",
]

# Index phụ để traversal nhanh theo (doc, article, ...)
EXTRA_INDEXES = [
    "CREATE INDEX article_doc IF NOT EXISTS FOR (n:Article) ON (n.document_id)",
    "CREATE INDEX clause_doc  IF NOT EXISTS FOR (n:Clause)  ON (n.document_id)",
    "CREATE INDEX point_doc   IF NOT EXISTS FOR (n:Point)   ON (n.document_id)",
]


def create_constraints(session) -> None:
    for q in CONSTRAINT_QUERIES + EXTRA_INDEXES:
        try:
            session.run(q)
        except Exception as e:
            # Indexes may already exist with different names - log and continue.
            log.warning("Constraint/Index warning: %s | %s", q.split("FOR")[0].strip(), e)


# ============================================================
# 6. NEO4J: UPSERT NODES (per document, trong 1 transaction)
# ============================================================

def upsert_document(session, doc: dict[str, Any]) -> None:
    """Upsert the root Document node."""
    d = doc.get("document") or {}
    session.run(
        """
        MERGE (l:Document {id: $id})
        SET l.number            = $number,
            l.title             = $title,
            l.type              = $type,
            l.source_file       = $source_file,
            l.status            = $status,
            l.date_enacted      = $date_enacted,
            l.date_effective    = $date_effective,
            l.issuing_authority = $issuing_authority,
            l.part_note         = $part_note,
            l.effective_notes   = $effective_notes,
            l.source_version    = $source_version
        """,
        id=d.get("id"),
        number=d.get("number"),
        title=_safe_str(d.get("title")),
        type=_infer_document_type(d),
        source_file=d.get("source_file"),
        status=d.get("status"),
        date_enacted=d.get("date_enacted"),
        date_effective=d.get("date_effective"),
        issuing_authority=_safe_str(d.get("issuing_authority")),
        part_note=_safe_str(d.get("part_note")),
        effective_notes=_safe_str(d.get("effective_date_notes")),
        source_version=d.get("source_version"),
    )


def upsert_chapters_for_doc(session, doc_id: str, chapters: list[dict[str, Any]]) -> None:
    """Upsert tất cả Chapter của 1 document + edge HAS_CHAPTER."""
    if not chapters:
        return
    rows = [
        {
            "id":          c.get("id"),
            "document_id": c.get("document_id", doc_id),
            "number":      c.get("number"),
            "title":       _safe_str(c.get("title")),
        }
        for c in chapters
        if c.get("id")
    ]
    if not rows:
        return
    session.run(
        """
        MATCH (d:Document {id: $doc_id})
        UNWIND $rows AS row
        MERGE (c:Chapter {id: row.id})
        SET c.document_id = row.document_id,
            c.number      = row.number,
            c.title       = row.title
        MERGE (d)-[:HAS_CHAPTER]->(c)
        """,
        doc_id=doc_id,
        rows=rows,
    )


def upsert_articles_for_doc(session, chapters: list[dict[str, Any]]) -> None:
    """Upsert tất cả Article của tất cả Chapter + edge HAS_ARTICLE."""
    rows: list[dict[str, Any]] = []
    for c in chapters:
        for a in c.get("articles", []) or []:
            if not a.get("id"):
                continue
            rows.append({
                "id":          a.get("id"),
                "document_id": a.get("document_id", c.get("document_id")),
                "chapter_id":  a.get("chapter_id", c.get("id")),
                "number":      a.get("number"),
                "title":       _safe_str(a.get("title")),
                "text":        _safe_str(a.get("text")),
            })
    if not rows:
        return
    session.run(
        """
        UNWIND $rows AS row
        MATCH (c:Chapter {id: row.chapter_id})
        MERGE (a:Article {id: row.id})
        SET a.document_id = row.document_id,
            a.chapter_id  = row.chapter_id,
            a.number      = row.number,
            a.title       = row.title,
            a.text        = row.text
        MERGE (c)-[:HAS_ARTICLE]->(a)
        """,
        rows=rows,
    )


def upsert_clauses_for_doc(session, chapters: list[dict[str, Any]]) -> None:
    """Upsert tất cả Clause + edge HAS_CLAUSE."""
    rows: list[dict[str, Any]] = []
    for c in chapters:
        for a in c.get("articles", []) or []:
            for k in a.get("clauses", []) or []:
                if not k.get("id"):
                    continue
                rows.append({
                    "id":          k.get("id"),
                    "document_id": k.get("document_id", a.get("document_id")),
                    "article_id":  k.get("article_id", a.get("id")),
                    "number":      k.get("number"),
                    "text":        _safe_str(k.get("text")),
                })
    if not rows:
        return
    session.run(
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id})
        MERGE (k:Clause {id: row.id})
        SET k.document_id = row.document_id,
            k.article_id  = row.article_id,
            k.number      = row.number,
            k.text        = row.text
        MERGE (a)-[:HAS_CLAUSE]->(k)
        """,
        rows=rows,
    )


def upsert_points_for_doc(session, chapters: list[dict[str, Any]]) -> None:
    """Upsert tất cả Point + edge HAS_POINT."""
    rows: list[dict[str, Any]] = []
    for c in chapters:
        for a in c.get("articles", []) or []:
            for k in a.get("clauses", []) or []:
                for p in k.get("points", []) or []:
                    if not p.get("id"):
                        continue
                    rows.append({
                        "id":          p.get("id"),
                        "document_id": p.get("document_id", k.get("document_id")),
                        "clause_id":   p.get("clause_id", k.get("id")),
                        "article_id":  k.get("article_id", a.get("id")),
                        "number":      p.get("number"),
                        "text":        _safe_str(p.get("text")),
                    })
    if not rows:
        return
    session.run(
        """
        UNWIND $rows AS row
        MATCH (k:Clause {id: row.clause_id})
        MERGE (p:Point {id: row.id})
        SET p.document_id = row.document_id,
            p.clause_id   = row.clause_id,
            p.article_id  = row.article_id,
            p.number      = row.number,
            p.text        = row.text
        MERGE (k)-[:HAS_POINT]->(p)
        """,
        rows=rows,
    )


def import_document_hierarchy(tx, doc: dict[str, Any]) -> dict[str, int]:
    """Import toàn bộ hierarchy của 1 document trong 1 transaction.
    Trả về dict đếm số node đã ghi."""
    chapters = doc.get("chapters", []) or []
    doc_id = doc["document"]["id"]
    upsert_document(tx, doc)
    upsert_chapters_for_doc(tx, doc_id, chapters)
    upsert_articles_for_doc(tx, chapters)
    upsert_clauses_for_doc(tx, chapters)
    upsert_points_for_doc(tx, chapters)
    return {
        "document": 1,
        "chapters": sum(1 for c in chapters if c.get("id")),
        "articles": sum(1 for c in chapters for a in (c.get("articles") or []) if a.get("id")),
        "clauses":  sum(1 for c in chapters for a in (c.get("articles") or [])
                        for k in (a.get("clauses") or []) if k.get("id")),
        "points":   sum(1 for c in chapters for a in (c.get("articles") or [])
                        for k in (a.get("clauses") or [])
                        for p in (k.get("points") or []) if p.get("id")),
    }


# ============================================================
# 7. RELATIONSHIPS (2 chiều)
# ============================================================

# Ánh xạ loại quan hệ -> tên chiều xuôi / chiều ngược.
REL_FORWARD = {
    "AMENDS":   "AMENDS",
    "ADDS":     "ADDS",
    "REPLACES": "REPLACES",
    "REPEALS":  "REPEALS",
}
REL_BACKWARD = {
    "AMENDS":   "AMENDED_BY",
    "ADDS":     "ADDED_IN",
    "REPLACES": "REPLACED_BY",
    "REPEALS":  "REPEALED_BY",
}


def _resolve_endpoints(rel: dict[str, Any], src_doc_id: str, tgt_doc_id: str):
    """
    Xác định (source_node_id, target_node_id, source_label, target_label, rel_type)
    cho một edge.

    Source: Article node trong document nguồn, xác định bằng
            (source_document_id + source_article_number).
    Target: resolve từ target_ref (dạng 'A<n>[.K<n>][.P<lbl>']).
    """
    rel_type = (rel.get("relationship") or rel.get("type") or "").upper()
    if rel_type not in REL_FORWARD:
        log.warning("Unknown relationship type: %r", rel_type)
        return None

    # --- Source node ---
    src_doc = rel.get("source_document_id") or src_doc_id
    src_art_num = rel.get("source_article_number")
    if not src_art_num:
        log.warning("Relationship missing source_article_number: %s", rel)
        return None
    # Source luôn là Article — không có thông tin clause/point cho source.
    source_label = "Article"
    # Source id sẽ được resolve sau bằng query MATCH vì article id thực tế
    # có thể chứa thêm chapter prefix.
    source_ref = f"article:{src_doc}:{src_art_num}"

    # --- Target node ---
    target_ref = rel.get("target_ref")
    if not target_ref:
        log.warning("Relationship missing target_ref: %s", rel)
        return None
    target_id = normalize_node_id(target_ref, src_doc_id, tgt_doc_id)
    if not target_id:
        log.warning("Cannot parse target_ref: %s", target_ref)
        return None

    n_parts = len(target_ref.split("."))
    target_label = {1: "Article", 2: "Clause", 3: "Point"}.get(n_parts, "Article")
    target_ref_full = target_id  # dùng id đã build sẵn

    return (source_ref, target_ref_full, source_label, target_label, rel_type, src_doc)


def upsert_relationship_edges(session, rel_file: dict[str, Any]) -> int:
    """Upsert các cạnh quan hệ 2 chiều từ 1 file relationship.

    Hỗ trợ cả 2 dạng key ở root:
      - Schema chính thức: source_document / target_document
      - Dạng rút gọn:     source / target
    Và 2 dạng type:
      - Schema chính thức: type (trong mỗi item)
      - Dạng rút gọn:     relationship
    """
    src_doc_id = (
        rel_file.get("source_document")
        or rel_file.get("source_document_id")
        or rel_file.get("source")
    )
    tgt_doc_id = (
        rel_file.get("target_document")
        or rel_file.get("target_document_id")
        or rel_file.get("target")
    )
    if not src_doc_id or not tgt_doc_id:
        log.warning("Relationship file missing source/target document id: keys=%s",
                    list(rel_file.keys()))
        return 0

    forward_type = REL_FORWARD  # local alias
    backward_type = REL_BACKWARD

    edges: list[dict[str, Any]] = []
    for rel in rel_file.get("relationships", []):
        resolved = _resolve_endpoints(rel, src_doc_id, tgt_doc_id)
        if not resolved or resolved[0] is None:
            continue
        source_ref, tgt_id, src_label, tgt_label, rel_type, src_doc = resolved
        # source_ref có dạng "article:<doc_id>:<article_num>" — sẽ resolve bằng
        # MATCH (a:Article {document_id, number}) lúc query.
        reason = rel.get("reason") or rel.get("description")
        edges.append({
            "source_ref":   source_ref,   # 'article:<doc>:<num>'
            "tgt_id":       tgt_id,
            "src_label":    src_label,
            "tgt_label":    tgt_label,
            "rel_type":     rel_type,
            "fwd_rel":      REL_FORWARD[rel_type],
            "bwd_rel":      REL_BACKWARD[rel_type],
            "reason":       _safe_str(reason),
            "src_article":  rel.get("source_article_number"),
            "src_doc":      src_doc,
        })

    if not edges:
        return 0

    # Gộp theo (source_ref, tgt_id, fwd_rel) để tránh duplicate nếu file có trùng.
    seen = set()
    unique_edges = []
    for e in edges:
        key = (e["source_ref"], e["tgt_id"], e["fwd_rel"])
        if key in seen:
            continue
        seen.add(key)
        unique_edges.append(e)

    # Vì Cypher không cho phép MERGE với type động, ta chạy 4 câu query
    # (mỗi loại quan hệ 1 câu) — vừa nhanh vừa không cần APOC.
    #
    # Source node tìm bằng (document_id, number) vì article id thực tế có
    # thêm chapter prefix (vd: D238-2026-ND-CP-CI-A1), không thể dựng sẵn.
    total_written = 0
    skipped = 0
    for rel_type, fwd in REL_FORWARD.items():
        rows = [e for e in unique_edges if e["fwd_rel"] == fwd]
        if not rows:
            continue
        bwd = REL_BACKWARD[rel_type]
        params = {
            "rows": [
                {
                    "src_doc":      r["src_doc"],
                    "src_article":  r["src_article"],
                    "tgt_id":       r["tgt_id"],
                    "src_label":    r["src_label"],
                    "reason":       r["reason"],
                    "tgt_label":    r["tgt_label"],
                }
                for r in rows
            ]
        }
        # Chiều xuôi: (src:Article)-[fwd]->(tgt)
        result = session.run(
            f"""
            UNWIND $rows AS e
            MATCH (a:Article {{document_id: e.src_doc, number: e.src_article}})
            MATCH (b) WHERE b.id = e.tgt_id
            MERGE (a)-[r:{fwd}]->(b)
            SET r.reason         = e.reason,
                r.source_article = e.src_article,
                r.target_ref     = e.tgt_id,
                r.target_label   = e.tgt_label
            RETURN count(r) AS n
            """,
            **params,
        ).single()
        fwd_count = result["n"] if result else 0

        # Chiều ngược: (tgt)-[bwd]->(src:Article)
        result = session.run(
            f"""
            UNWIND $rows AS e
            MATCH (a:Article {{document_id: e.src_doc, number: e.src_article}})
            MATCH (b) WHERE b.id = e.tgt_id
            MERGE (b)-[r:{bwd}]->(a)
            SET r.reason         = e.reason,
                r.source_article = e.src_article,
                r.target_ref     = a.id,
                r.target_label   = e.src_label
            RETURN count(r) AS n
            """,
            **params,
        ).single()
        bwd_count = result["n"] if result else 0

        total_written += fwd_count
        if fwd_count != len(rows):
            skipped += len(rows) - fwd_count
            log.warning("  [%s] matched %d/%d rows (%d skipped)",
                        fwd, fwd_count, len(rows), len(rows) - fwd_count)

    if skipped:
        log.warning("Total %d relationships skipped (source/target node missing).",
                    skipped)
    return total_written


# ============================================================
# 8. SUMMARY / VERIFY
# ============================================================

def print_graph_summary(session) -> None:
    counts = session.run(
        """
        MATCH (d:Document) WITH count(d) AS docs
        OPTIONAL MATCH (c:Chapter)  WITH docs, count(c) AS chapters
        OPTIONAL MATCH (a:Article)  WITH docs, chapters, count(a) AS articles
        OPTIONAL MATCH (k:Clause)   WITH docs, chapters, articles, count(k) AS clauses
        OPTIONAL MATCH (p:Point)    WITH docs, chapters, articles, clauses, count(p) AS points
        RETURN docs, chapters, articles, clauses, points
        """
    ).single()
    rels = session.run(
        """
        MATCH ()-[r]->()
        WHERE type(r) IN ['AMENDS','ADDS','REPLACES','REPEALS',
                          'AMENDED_BY','ADDED_IN','REPLACED_BY','REPEALED_BY']
        RETURN type(r) AS t, count(r) AS n
        """
    ).data()
    if counts:
        log.info(
            "Graph -> Documents:%d  Chapters:%d  Articles:%d  Clauses:%d  Points:%d",
            counts["docs"], counts["chapters"], counts["articles"],
            counts["clauses"], counts["points"],
        )
    if rels:
        log.info("Relationships:")
        for row in rels:
            log.info("  -%s- : %d", row["t"], row["n"])


# ============================================================
# 9. MAIN
# ============================================================

def main() -> None:
    log.info("=== Import legal documents into Neo4j ===")
    log.info("Document folder:   %s", DOC_DOCUMENT_DIR)
    log.info("Relationship dir:  %s", DOC_RELATIONSHIP_DIR)

    documents = load_documents(DOC_DOCUMENT_DIR)
    relationships = load_relationships(DOC_RELATIONSHIP_DIR)

    log.info("Found %d document(s), %d relationship file(s)",
             len(documents), len(relationships))

    log.info("Connecting to Neo4j at %s ...", NEO4J_URI)
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )
    driver.verify_connectivity()
    log.info("Connected to Neo4j successfully!")

    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            log.info("Creating constraints & indexes ...")
            create_constraints(session)

            # Clear cũ để tránh duplicate khi re-run (idempotent reset).
            log.info("Clearing old relationship edges (forward + backward) ...")
            session.run(
                """
                MATCH ()-[r]->()
                WHERE type(r) IN ['AMENDS','ADDS','REPLACES','REPEALS',
                                  'AMENDED_BY','ADDED_IN','REPLACED_BY','REPEALED_BY']
                DELETE r
                """
            )

            # ---- 1. Import documents + hierarchy ----
            log.info("--- Importing document hierarchy ---")
            for doc in documents:
                doc_id = doc["document"].get("id")
                title = doc["document"].get("title")
                log.info("Importing Document: %s (%s)", title, doc_id)
                counts = session.execute_write(import_document_hierarchy, doc)
                log.info("  Up: %s", counts)

            # ---- 2. Import relationships ----
            log.info("--- Importing relationships ---")
            for rel_file in relationships:
                src = (
                    rel_file.get("source_document")
                    or rel_file.get("source_document_id")
                    or rel_file.get("source")
                )
                tgt = (
                    rel_file.get("target_document")
                    or rel_file.get("target_document_id")
                    or rel_file.get("target")
                )
                log.info("Importing relationships: %s -> %s", src, tgt)
                written = session.execute_write(upsert_relationship_edges, rel_file)
                log.info("  %d unique edges written", written)

            # ---- 3. Verify ----
            print_graph_summary(session)

    finally:
        driver.close()

    log.info("IMPORT COMPLETED!")


if __name__ == "__main__":
    main()
