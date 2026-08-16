"""
Import legal documents from JSON files into Neo4j.

Behavior:
  * Reads EVERY *.json file under doc/ folder (recursive).
  * Normalizes two input schemas:
      Schema A (Luật): { document, chapters: [...] }
      Schema B (Nghị định): { document, structure: { chapters: [...] } }
  * Groups chapters by document.id -- several JSON files can contribute
    chapters/articles/clauses/points to the SAME Law node when they share
    the same document.id.
  * Uses a single session.execute_write() transaction per file with
    UNWIND batches for performance.
  * Creates uniqueness constraints on (Law|Chapter|Article|Clause|Point).id
    before importing (idempotent).
  * Stores document_type, issuing_authority, date_enacted, date_effective
    on the Law node so the LLM can distinguish between Luật vs Nghị định.

Run:
    cd data_import
    python import_data_neo4j.py
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
from collections import defaultdict
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

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

if not all([NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD]):
    log.error("Missing one of: NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD in .env")
    sys.exit(1)


# ============================================================
# 2. PATHS
# ============================================================

# Source folder location: source/import_data_neo4j.py  ->  ../doc
SCRIPT_DIR = Path(__file__).resolve().parent
DOC_DIR = (SCRIPT_DIR.parent / "doc").resolve()

if not DOC_DIR.exists():
    log.error(f"doc/ folder not found at: {DOC_DIR}")
    sys.exit(1)


# ============================================================
# 3. LOAD JSON FILES
# ============================================================

def load_all_documents(DOC_DIR: Path) -> list[dict[str, Any]]:
    """Read every .json file under DOC_DIR and return the parsed objects."""
    json_paths = sorted(glob.glob(str(DOC_DIR / "**" / "*.json"), recursive=True))
    if not json_paths:
        log.error(f"No .json files found in {DOC_DIR}")
        sys.exit(1)

    documents: list[dict[str, Any]] = []
    for path in json_paths:
        rel = Path(path).relative_to(DOC_DIR)
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            documents.append(doc)
            log.info(f"Loaded {rel}  (doc.id={doc.get('document', {}).get('id', '?')})")
        except Exception as e:
            log.exception(f"Failed to read {rel}: {e}")

    if not documents:
        log.error("All JSON files failed to load.")
        sys.exit(1)

    return documents


# ============================================================
# 4. AGGREGATE BY document.id
# ============================================================

def _extract_chapters(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return chapters regardless of which schema the file uses.

    Schema A (Luật files): root level `chapters` key.
    Schema B (Nghị định files): `document.structure.chapters`.
    """
    chapters = doc.get("chapters") or []
    if chapters:
        return chapters
    document = doc.get("document") or {}
    structure = document.get("structure") or doc.get("structure") or {}
    return structure.get("chapters") or []


def merge_documents_by_id(documents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Group files that share document.id into a single 'law' entry.
    Resulting list contains unique Laws; chapters/articles/clauses/points
    coming from multiple files are appended together.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for doc in documents:
        d = doc.get("document") or {}
        law_id = d.get("id")
        if not law_id:
            log.warning("Skipping a document missing document.id")
            continue

        if law_id not in buckets:
            buckets[law_id] = {
                "document": dict(d),
                "_sources": [],
                "chapters": [],
            }
        else:
            # Merge extra fields from siblings without overwriting existing ones.
            for k, v in d.items():
                buckets[law_id]["document"].setdefault(k, v)

        buckets[law_id]["_sources"].append(d.get("source_file"))
        buckets[law_id]["chapters"].extend(_extract_chapters(doc))

    for law in buckets.values():
        law["_sources"] = sorted({s for s in law["_sources"] if s})

    return list(buckets.values())


# ============================================================
# 5. NEO4J: CONSTRAINTS
# ============================================================

CONSTRAINT_QUERIES = [
    "CREATE CONSTRAINT law_id IF NOT EXISTS FOR (n:Law)     REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT chapter_id IF NOT EXISTS FOR (n:Chapter) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT clause_id IF NOT EXISTS FOR (n:Clause)   REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT point_id IF NOT EXISTS FOR (n:Point)     REQUIRE n.id IS UNIQUE",
]


def create_constraints(session) -> None:
    for q in CONSTRAINT_QUERIES:
        session.run(q)


# ============================================================
# 6. NEO4J: UPSERTS (UNWIND batches inside a single transaction)
# ============================================================

def _infer_document_type(law_id: str, raw: str) -> str:
    if raw:
        return raw
    if not law_id:
        return "Văn bản"
    upper = law_id.upper()
    if upper.startswith("L"):
        return "Luật"
    if upper.startswith("PL"):
        return "Pháp lệnh"
    return "Văn bản"


def upsert_law(session, law: dict[str, Any]) -> None:
    d = law["document"]
    doc_type = _infer_document_type(d.get("id", ""), d.get("document_type") or d.get("type") or "")
    session.run(
        """
        MERGE (l:Law {id: $id})
        SET l.number             = $number,
            l.title              = $title,
            l.source_file        = $source_file,
            l.status             = $status,
            l.date_enacted       = $date_enacted,
            l.date_effective     = $date_effective,
            l.source_files       = $source_files,
            l.document_type      = $document_type,
            l.document_number    = $document_number,
            l.issuing_authority  = $issuing_authority,
            l.effective_notes    = $effective_notes
        """,
        id=d.get("id"),
        number=d.get("number"),
        title=d.get("title"),
        source_file=d.get("source_file"),
        status=d.get("status"),
        date_enacted=d.get("date_enacted"),
        date_effective=d.get("date_effective"),
        source_files=law["_sources"],
        document_type=doc_type,
        document_number=d.get("document_number") or d.get("number"),
        issuing_authority=d.get("issuing_authority"),
        effective_notes=d.get("effective_date_notes"),
    )


def upsert_chapters(session, law_id: str, chapters: list[dict[str, Any]]) -> None:
    """Upsert all chapters + attach them to the Law in a single statement."""
    if not chapters:
        return
    rows = [
        {
            "id":          c.get("id"),
            "document_id": c.get("document_id", law_id),
            "number":      c.get("number"),
            "title":       c.get("title"),
            "page_start":  c.get("page_start"),
            "page_end":    c.get("page_end"),
        }
        for c in chapters
    ]
    session.run(
        """
        MATCH (l:Law {id: $law_id})
        UNWIND $rows AS row
        MERGE (c:Chapter {id: row.id})
        SET c.number     = row.number,
            c.title      = row.title,
            c.page_start = row.page_start,
            c.page_end   = row.page_end
        MERGE (l)-[:HAS_CHAPTER]->(c)
        """,
        law_id=law_id,
        rows=rows,
    )


def upsert_articles(session, chapters: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for c in chapters:
        for a in c.get("articles", []) or []:
            rows.append(
                {
                    "id":         a.get("id"),
                    "chapter_id": a.get("chapter_id", c.get("id")),
                    "number":     a.get("number"),
                    "title":      a.get("title"),
                    "text":       a.get("text"),
                    "page_start": a.get("page_start"),
                    "page_end":   a.get("page_end"),
                }
            )
    if not rows:
        return
    session.run(
        """
        UNWIND $rows AS row
        MATCH (c:Chapter {id: row.chapter_id})
        MERGE (a:Article {id: row.id})
        SET a.number     = row.number,
            a.title      = row.title,
            a.text       = row.text,
            a.page_start = row.page_start,
            a.page_end   = row.page_end
        MERGE (c)-[:HAS_ARTICLE]->(a)
        """,
        rows=rows,
    )


def upsert_clauses(session, chapters: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for c in chapters:
        for a in c.get("articles", []) or []:
            for k in a.get("clauses", []) or []:
                rows.append(
                    {
                        "id":         k.get("id"),
                        "article_id": k.get("article_id", a.get("id")),
                        "number":     k.get("number"),
                        "text":       k.get("text"),
                        "page_start": k.get("page_start"),
                        "page_end":   k.get("page_end"),
                    }
                )
    if not rows:
        return
    session.run(
        """
        UNWIND $rows AS row
        MATCH (a:Article {id: row.article_id})
        MERGE (k:Clause {id: row.id})
        SET k.number     = row.number,
            k.text       = row.text,
            k.page_start = row.page_start,
            k.page_end   = row.page_end
        MERGE (a)-[:HAS_CLAUSE]->(k)
        """,
        rows=rows,
    )


def upsert_points(session, chapters: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for c in chapters:
        for a in c.get("articles", []) or []:
            for k in a.get("clauses", []) or []:
                for p in k.get("points", []) or []:
                    rows.append(
                        {
                            "id":        p.get("id"),
                            "clause_id": p.get("clause_id", k.get("id")),
                            "number":    p.get("number"),
                            "text":      p.get("text"),
                            "page_start": p.get("page_start"),
                            "page_end":   p.get("page_end"),
                        }
                    )
    if not rows:
        return
    session.run(
        """
        UNWIND $rows AS row
        MATCH (k:Clause {id: row.clause_id})
        MERGE (p:Point {id: row.id})
        SET p.number     = row.number,
            p.text       = row.text,
            p.page_start = row.page_start,
            p.page_end   = row.page_end
        MERGE (k)-[:HAS_POINT]->(p)
        """,
        rows=rows,
    )


def import_law(tx, law: dict[str, Any]) -> None:
    """All writes for one law run inside a single transaction."""
    upsert_law(tx, law)
    chapters = law.get("chapters", [])
    upsert_chapters(tx, law["document"]["id"], chapters)
    upsert_articles(tx, chapters)
    upsert_clauses(tx, chapters)
    upsert_points(tx, chapters)


# ============================================================
# 7. SUMMARY / VERIFY
# ============================================================

def print_graph_summary(session) -> None:
    counts = session.run(
        """
        MATCH (l:Law)            WITH count(l) AS laws
        OPTIONAL MATCH (c:Chapter)  WITH laws, count(c) AS chapters
        OPTIONAL MATCH (a:Article)  WITH laws, chapters, count(a) AS articles
        OPTIONAL MATCH (k:Clause)   WITH laws, chapters, articles, count(k) AS clauses
        OPTIONAL MATCH (p:Point)    WITH laws, chapters, articles, clauses, count(p) AS points
        RETURN laws, chapters, articles, clauses, points
        """
    ).single()

    if counts:
        log.info(
            "Graph summary -> Laws:%d  Chapters:%d  Articles:%d  "
            "Clauses:%d  Points:%d",
            counts["laws"], counts["chapters"],
            counts["articles"], counts["clauses"], counts["points"],
        )


# ============================================================
# 8. MAIN
# ============================================================

def main() -> None:
    log.info(f"Scanning JSON files under: {DOC_DIR}")
    documents = load_all_documents(DOC_DIR)
    laws = merge_documents_by_id(documents)
    log.info(f"Unique Laws (by document.id): {len(laws)}")

    log.info(f"Connecting to Neo4j at {NEO4J_URI} ...")
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
    )
    driver.verify_connectivity()
    log.info("Connected to Neo4j successfully!")

    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            log.info("Creating constraints ...")
            create_constraints(session)

            for law in laws:
                law_id = law["document"]["id"]
                log.info(f"Importing Law: {law['document'].get('title')} ({law_id})")
                session.execute_write(import_law, law)
                chs = law.get("chapters", [])
                log.info(
                    "  Chapters:%d  Articles:%d  Clauses:%d  Points:%d",
                    len(chs),
                    sum(len(c.get("articles", []) or []) for c in chs),
                    sum(
                        len(a.get("clauses", []) or [])
                        for c in chs
                        for a in (c.get("articles", []) or [])
                    ),
                    sum(
                    len(p.get("points", []) or [])
                    for c in chs
                    for a in (c.get("articles", []) or [])
                    for k in (a.get("clauses", []) or [])
                    for p in (k.get("points", []) or [])
                ),
                )

            print_graph_summary(session)

    finally:
        driver.close()

    log.info("IMPORT COMPLETED!")


if __name__ == "__main__":
    main()
