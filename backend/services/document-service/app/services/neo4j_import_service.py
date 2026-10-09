"""Neo4j import service — Lift from data_import/import_data_neo4j.py.

Lift & integrate logic import từ `data_import/import_data_neo4j.py` thành
service trong document-service để:
    1. Auto-trigger sau khi parse xong law.json/relationships.json
    2. Idempotent (MERGE) — re-upload an toàn
    3. Có thể xoá cascade (xóa Document + relationships)

Usage:
    svc = Neo4jImportService(driver=get_neo4j_driver())
    result = svc.import_document(law_dict)
    result = svc.import_relationships(rel_dict)
    result = svc.delete_document(law_id)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from neo4j import Driver, GraphDatabase

from app.core.config import (
    NEO4J_URI,
    NEO4J_USERNAME,
    NEO4J_PASSWORD,
    NEO4J_DATABASE,
)

log = logging.getLogger("document-service.neo4j_import")


def _safe_str(v: Any) -> Optional[str]:
    """Trim string or return None."""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return v


def _infer_document_type(doc: Dict[str, Any]) -> str:
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


def normalize_node_id(target_ref: str, source_doc_id: str, target_doc_id: str) -> Optional[str]:
    """Convert short ref like 'A6.K3.Pm' → full node id '<doc>-A-<art>-K3-Pm'."""
    if not target_ref:
        return None

    ref = target_ref.strip()
    m = re.match(r"^[Aa](\d+)(?:\.[Kk](\d+\w*)(?:\.([Pp]\w+))?)?$", ref)
    if not m:
        return None

    article_num, clause_num, point_label = m.groups()
    parts = [target_doc_id, "A", article_num]
    if clause_num:
        parts.append(f"K{clause_num}")
    if point_label:
        parts.append(point_label)
    return "-".join(parts)


def _build_node_id_from_ref(ref: str, doc_id: str) -> Optional[str]:
    """Build a node id from a short ref like 'A3' or 'A3.K5' for the source doc.

    Returns full ID like '<doc>-A-3' or '<doc>-A-3-K5'.
    """
    if not ref:
        return None
    ref = ref.strip()
    # If already has doc prefix
    if ref.startswith(doc_id):
        return ref
    m = re.match(r"^[Aa](\d+)(?:\.[Kk](\d+\w*))?$", ref)
    if not m:
        return None
    art_num = m.group(1)
    cl_num = m.group(2)
    parts = [doc_id, "A", art_num]
    if cl_num:
        parts.append(f"K{cl_num}")
    return "-".join(parts)


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


class Neo4jImportService:
    """Service import law.json + relationships.json vào Neo4j graph."""

    def __init__(self, driver: Optional[Driver] = None):
        if driver is not None:
            self._driver = driver
        else:
            if not all([NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD]):
                raise ValueError("Missing Neo4j credentials (NEO4J_URI/USERNAME/PASSWORD)")
            self._driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
            )
            self._driver.verify_connectivity()
        self._database = NEO4J_DATABASE or "neo4j"

    # ---------------- Schema ----------------
    def ensure_constraints(self) -> None:
        """Tạo unique constraints + indexes (idempotent)."""
        constraint_queries = [
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (n:Chapter)   REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article)   REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT clause_id IF NOT EXISTS FOR (n:Clause)     REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT point_id IF NOT EXISTS FOR (n:Point)       REQUIRE n.id IS UNIQUE",
        ]
        extra_indexes = [
            "CREATE INDEX article_doc IF NOT EXISTS FOR (n:Article) ON (n.document_id)",
            "CREATE INDEX clause_doc  IF NOT EXISTS FOR (n:Clause)  ON (n.document_id)",
            "CREATE INDEX point_doc   IF NOT EXISTS FOR (n:Point)   ON (n.document_id)",
        ]
        with self._driver.session(database=self._database) as session:
            for q in constraint_queries + extra_indexes:
                try:
                    session.run(q)
                except Exception as e:
                    log.warning("Constraint/Index skip: %s | %s",
                                q.split("FOR")[0].strip(), e)

    # ---------------- Document hierarchy import ----------------
    def import_document(self, doc: Dict[str, Any]) -> Dict[str, int]:
        """Import toàn bộ hierarchy của 1 document vào Neo4j.

        Returns dict đếm số node đã ghi.
        """
        doc_id = doc.get("document", {}).get("id")
        if not doc_id:
            raise ValueError("document.id missing")

        chapters = doc.get("chapters", []) or []

        with self._driver.session(database=self._database) as session:
            # Đảm bảo constraints luôn tồn tại
            self.ensure_constraints_with_session(session)

            # Upsert Document
            session.execute_write(self._tx_upsert_document, doc)

            # Upsert chapters/articles/clauses/points
            session.execute_write(self._tx_upsert_hierarchy, chapters)

        return {
            "document": 1,
            "chapters": sum(1 for c in chapters if c.get("id")),
            "articles": sum(
                1 for c in chapters
                for a in (c.get("articles") or [])
                if a.get("id")
            ) + sum(
                1 for c in chapters
                for s in (c.get("sections") or [])
                for a in (s.get("articles") or [])
                if a.get("id")
            ),
            "clauses":  sum(
                1 for c in chapters
                for a in (c.get("articles") or [])
                for k in (a.get("clauses") or [])
                if k.get("id")
            ) + sum(
                1 for c in chapters
                for s in (c.get("sections") or [])
                for a in (s.get("articles") or [])
                for k in (a.get("clauses") or [])
                if k.get("id")
            ),
            "points":   sum(
                1 for c in chapters
                for a in (c.get("articles") or [])
                for k in (a.get("clauses") or [])
                for p in (k.get("points") or [])
                if p.get("id")
            ) + sum(
                1 for c in chapters
                for s in (c.get("sections") or [])
                for a in (s.get("articles") or [])
                for k in (a.get("clauses") or [])
                for p in (k.get("points") or [])
                if p.get("id")
            ),
        }

    def ensure_constraints_with_session(self, session) -> None:
        """Same as ensure_constraints() but reuses open session (for tx)."""
        constraint_queries = [
            "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (n:Chapter)   REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article)   REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT clause_id IF NOT EXISTS FOR (n:Clause)     REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT point_id IF NOT EXISTS FOR (n:Point)       REQUIRE n.id IS UNIQUE",
        ]
        for q in constraint_queries:
            try:
                session.run(q)
            except Exception:
                pass  # already exists

    @staticmethod
    def _tx_upsert_document(tx, doc: Dict[str, Any]) -> None:
        d = doc.get("document") or {}
        tx.run(
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

    @staticmethod
    def _iter_articles(chapters: List[Dict[str, Any]]):
        """Yield (article, chapter) cho tất cả articles trong document,
        bao gồm cả articles lồng trong sections[].articles[].
        """
        for c in chapters:
            for a in c.get("articles", []) or []:
                yield a, c
            for s in c.get("sections", []) or []:
                for a in s.get("articles", []) or []:
                    yield a, c

    @staticmethod
    def _tx_upsert_hierarchy(tx, chapters: List[Dict[str, Any]]) -> None:
        """Upsert chapters + articles + clauses + points trong 1 transaction.

        Lưu ý: Articles có thể nằm trực tiếp trong chapter hoặc trong
        section (chapter → sections[].articles). Cả 2 đều được import.
        """
        # --- Chapters ---
        ch_rows = [
            {
                "id": c.get("id"),
                "document_id": c.get("document_id") or (c.get("id") and c["id"].rsplit("-CH-", 1)[0]),
                "number": c.get("number"),
                "title": _safe_str(c.get("title")),
            }
            for c in chapters if c.get("id")
        ]
        if ch_rows:
            # Gộp UNWIND MERGE và MATCH luôn trong cùng 1 query (Neo4j không
            # cho phép MATCH không có RETURN/FINISH ở cuối).
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (c:Chapter {id: row.id})
                SET c.document_id = row.document_id,
                    c.number      = row.number,
                    c.title       = row.title
                WITH c, row
                MATCH (d:Document {id: row.document_id})
                MERGE (d)-[:HAS_CHAPTER]->(c)
                """,
                rows=ch_rows,
            )

        # --- Articles (cả trong chapter lẫn trong sections) ---
        art_rows = []
        for a, c in Neo4jImportService._iter_articles(chapters):
            if a.get("id"):
                art_rows.append({
                    "id": a.get("id"),
                    "document_id": a.get("document_id") or c.get("document_id"),
                    "chapter_id": a.get("chapter_id") or c.get("id"),
                    "number": a.get("number"),
                    "title": _safe_str(a.get("title")),
                    "text": _safe_str(a.get("text")),
                })
        if art_rows:
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (a:Article {id: row.id})
                SET a.document_id = row.document_id,
                    a.chapter_id  = row.chapter_id,
                    a.number      = row.number,
                    a.title       = row.title,
                    a.text        = row.text
                WITH a, row
                MATCH (c:Chapter {id: row.chapter_id})
                MERGE (c)-[:HAS_ARTICLE]->(a)
                """,
                rows=art_rows,
            )

        # --- Clauses ---
        cl_rows = []
        for a, c in Neo4jImportService._iter_articles(chapters):
            for k in a.get("clauses", []) or []:
                if k.get("id"):
                    cl_rows.append({
                        "id": k.get("id"),
                        "document_id": k.get("document_id") or a.get("document_id"),
                        "article_id": k.get("article_id") or a.get("id"),
                        "number": k.get("number"),
                        "text": _safe_str(k.get("text")),
                    })
        if cl_rows:
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (k:Clause {id: row.id})
                SET k.document_id = row.document_id,
                    k.article_id  = row.article_id,
                    k.number      = row.number,
                    k.text        = row.text
                WITH k, row
                MATCH (a:Article {id: row.article_id})
                MERGE (a)-[:HAS_CLAUSE]->(k)
                """,
                rows=cl_rows,
            )

        # --- Points ---
        pt_rows = []
        for a, c in Neo4jImportService._iter_articles(chapters):
            for k in a.get("clauses", []) or []:
                for p in k.get("points", []) or []:
                    if p.get("id"):
                        pt_rows.append({
                            "id": p.get("id"),
                            "document_id": p.get("document_id") or k.get("document_id"),
                            "clause_id": p.get("clause_id") or k.get("id"),
                            "article_id": k.get("article_id") or a.get("id"),
                            "number": p.get("number"),
                            "text": _safe_str(p.get("text")),
                        })
        if pt_rows:
            tx.run(
                """
                UNWIND $rows AS row
                MERGE (p:Point {id: row.id})
                SET p.document_id = row.document_id,
                    p.clause_id   = row.clause_id,
                    p.article_id  = row.article_id,
                    p.number      = row.number,
                    p.text        = row.text
                WITH p, row
                MATCH (k:Clause {id: row.clause_id})
                MERGE (k)-[:HAS_POINT]->(p)
                """,
                rows=pt_rows,
            )

    # ---------------- Relationships import ----------------
    def import_relationships(self, rel_file: Dict[str, Any]) -> int:
        """Upsert các cạnh quan hệ 2 chiều từ 1 file relationship.

        Schema:
            {
              "source_document": str,
              "target_document": str,
              "relationships": [
                {
                  "source_ref": str,  # full ID, vd: "D236-2026-ND-CP-A-3" or "D236-...-K5"
                  "target_ref": str,  # short form: "A3", "A3.K5", "A3.K5.Pi"
                  "type": "AMENDS"|"ADDS"|"REPLACES"|"REPEALS",
                  "description": str (optional)
                }
              ]
            }

        Source node: resolve `source_ref` bằng MATCH theo id.
        Target node: build full ID từ `target_ref` + target_document id.
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
            log.warning("Relationship file missing source/target")
            return 0

        edges = []
        for rel in rel_file.get("relationships", []) or []:
            rel_type = (
                rel.get("type") or rel.get("relationship") or ""
            ).upper()
            if rel_type not in REL_FORWARD:
                continue

            # --- Source ---
            source_ref = rel.get("source_ref") or rel.get("source")
            if not source_ref:
                continue
            # source_ref can be either full ID or short form
            if not source_ref.startswith(src_doc_id):
                # Try to build full ID
                src_id = _build_node_id_from_ref(source_ref, src_doc_id)
            else:
                src_id = source_ref

            # --- Target ---
            target_ref = rel.get("target_ref") or rel.get("target")
            if not target_ref:
                continue
            target_id = normalize_node_id(target_ref, src_doc_id, tgt_doc_id)
            if not target_id:
                continue

            # Determine target label by ref depth
            n_parts = len(target_ref.split("."))
            tgt_label = {1: "Article", 2: "Clause", 3: "Point"}.get(n_parts, "Article")

            edges.append({
                "src_id":      src_id,
                "tgt_id":      target_id,
                "src_label":   "Article",  # source is usually Article (or Clause if source_ref has K)
                "tgt_label":   tgt_label,
                "rel_type":    rel_type,
                "fwd_rel":     REL_FORWARD[rel_type],
                "bwd_rel":     REL_BACKWARD[rel_type],
                "reason":      _safe_str(rel.get("description") or rel.get("reason")),
            })

        # Deduplicate
        seen = set()
        unique_edges = []
        for e in edges:
            key = (e["src_id"], e["tgt_id"], e["fwd_rel"])
            if key in seen:
                continue
            seen.add(key)
            unique_edges.append(e)

        if not unique_edges:
            return 0

        total = 0
        with self._driver.session(database=self._database) as session:
            for rel_type, fwd in REL_FORWARD.items():
                rows = [e for e in unique_edges if e["fwd_rel"] == fwd]
                if not rows:
                    continue
                bwd = REL_BACKWARD[rel_type]
                params = {
                    "rows": [
                        {
                            "src_id": r["src_id"],
                            "tgt_id": r["tgt_id"],
                            "reason": r["reason"],
                            "tgt_label": r["tgt_label"],
                            "src_label": r["src_label"],
                        }
                        for r in rows
                    ]
                }
                # Forward: (src)-[fwd]->(tgt) — match by id
                res = session.run(
                    f"""
                    UNWIND $rows AS e
                    MATCH (a) WHERE a.id = e.src_id
                    MATCH (b) WHERE b.id = e.tgt_id
                    MERGE (a)-[r:{fwd}]->(b)
                    SET r.reason       = e.reason,
                        r.source_ref   = e.src_id,
                        r.target_ref   = e.tgt_id,
                        r.target_label = e.tgt_label
                    RETURN count(r) AS n
                    """,
                    **params,
                ).single()
                fwd_count = res["n"] if res else 0

                # Backward: (tgt)-[bwd]->(src)
                res = session.run(
                    f"""
                    UNWIND $rows AS e
                    MATCH (a) WHERE a.id = e.src_id
                    MATCH (b) WHERE b.id = e.tgt_id
                    MERGE (b)-[r:{bwd}]->(a)
                    SET r.reason       = e.reason,
                        r.source_ref   = e.tgt_id,
                        r.target_ref   = e.src_id,
                        r.target_label = e.src_label
                    RETURN count(r) AS n
                    """,
                    **params,
                ).single()
                bwd_count = res["n"] if res else 0

                total += fwd_count
                log.info("[%s] fwd=%d bwd=%d (rows=%d)",
                         fwd, fwd_count, bwd_count, len(rows))

        return total

    # ---------------- Delete cascade ----------------
    def delete_document(self, law_id: str) -> Dict[str, int]:
        """Xoá toàn bộ Document + chapters/articles/clauses/points
        + forward/backward relationships liên quan.

        Returns dict đếm số node/edge đã xoá.
        """
        with self._driver.session(database=self._database) as session:
            # First: DETACH all nodes belonging to this doc_id.
            # DETACH deletes relationships too.
            doc_res = session.run(
                """
                MATCH (n) WHERE n.document_id = $doc_id
                DETACH DELETE n
                RETURN count(n) AS n
                """,
                doc_id=law_id,
            ).single()

            # Then: delete Document root if exists
            root_res = session.run(
                """
                MATCH (d:Document {id: $doc_id})
                DETACH DELETE d
                RETURN count(d) AS n
                """,
                doc_id=law_id,
            ).single()

        return {
            "children_deleted": doc_res["n"] if doc_res else 0,
            "document_deleted": root_res["n"] if root_res else 0,
        }

    def close(self) -> None:
        self._driver.close()
