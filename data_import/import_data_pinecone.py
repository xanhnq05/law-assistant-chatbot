"""
Import legal documents from JSON files into Pinecone vector DB.

Strategy: Multi-level chunking (Parent-Context Chunking)
  - Article vector  : title + text (no clause text)
  - Clause vector   : clause text + ALL points gộp vào (parent context)
  - Point          : NOT embedded separately (gộp vào clause cha)

Metadata mỗi vector chứa ĐẦY ĐỦ id của các cấp cha:
    document_id, chapter_id, article_id, clause_id, point_id=""
  -> Dùng để truy xuất Neo4j sau khi retrieval.

Run:
    cd data_import
    python import_data_pinecone.py
"""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Iterable

# Ensure UTF-8 output for Vietnamese titles on Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv
from pinecone import Pinecone as _Pinecone
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


# ============================================================
# 1. LOGGING & CONFIG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pinecone-import")

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "law-rag-v1")
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
EMBEDDING_BATCH = 64

if not PINECONE_API_KEY:
    log.error("Missing PINECONE_API_KEY in .env")
    sys.exit(1)


# ============================================================
# 2. PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DOC_DOCUMENT_DIR = (SCRIPT_DIR.parent / "doc" / "document").resolve()
if not DOC_DOCUMENT_DIR.exists():
    log.error("Folder not found: doc/document -> %s", DOC_DOCUMENT_DIR)
    sys.exit(1)


# ============================================================
# 3. HELPERS
# ============================================================

def _safe_id(raw_id: str | None) -> str:
    """Pinecone requires ASCII vector IDs."""
    if not raw_id:
        return ""
    s = raw_id.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s


def _safe(v: str | None) -> str:
    return (v or "").strip() or ""


# ============================================================
# 4. LOAD JSON
# ============================================================

def load_documents(folder: Path) -> list[dict[str, Any]]:
    """Load all *.json under folder. Skip schema files."""
    docs: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        if "schema" in path.name.lower():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            docs.append(obj)
            doc_id = obj.get("document", {}).get("id", "?")
            log.info("Loaded %s (id=%s)", path.name, doc_id)
        except Exception:
            log.exception("Failed to read %s", path.name)
    if not docs:
        log.error("No document JSON found in %s", folder)
        sys.exit(1)
    return docs


# ============================================================
# 5. BUILD UNITS
# ============================================================

def _build_points_blob(clause: dict[str, Any]) -> str:
    """Gộp text của tất cả điểm thành 1 chuỗi."""
    points = clause.get("points", []) or []
    if not points:
        return ""
    return "\n".join(
        f"{p.get('number', '?')}) {_safe(p.get('text'))}"
        for p in points
    )


def _build_clause_blob(
    article: dict[str, Any],
    clause: dict[str, Any],
    chapter_title: str,
) -> str:
    """Build text được embed cho 1 clause vector (gộp clause + tất cả points)."""
    parts = []
    if chapter_title:
        parts.append(f"[Chương {chapter_title}]")
    parts.append(f"Điều {article.get('number', '')}. {_safe(article.get('title', ''))}")
    parts.append(f"Khoản {clause.get('number', '')}: {_safe(clause.get('text', ''))}")
    points_blob = _build_points_blob(clause)
    if points_blob:
        parts.append(f"Các điểm:\n{points_blob}")
    return "\n".join(parts).strip()


def _infer_doc_type(doc: dict[str, Any]) -> str:
    """Đoán loại văn bản."""
    t = _safe(doc.get("type"))
    if t:
        return t
    lid = (doc.get("id") or "").upper()
    if lid.startswith("L"):
        return "Luật"
    if lid.startswith("PL"):
        return "Pháp lệnh"
    return "Văn bản"


def build_units(documents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Emit Article vector + Clause vector (gộp points) cho mỗi document.

    Article vector : title + text gốc (không gộp clause)
    Clause vector  : clause text + tất cả points gộp vào
    """
    units: list[dict[str, Any]] = []

    for doc in documents:
        law = doc.get("document") or {}
        doc_id = law.get("id")
        doc_type = _infer_doc_type(law)
        doc_number = law.get("document_number") or law.get("number") or ""
        issuing_authority = _safe(law.get("issuing_authority"))
        date_enacted = law.get("date_enacted") or ""

        chapters = doc.get("chapters", []) or []
        if not chapters:
            document = law or {}
            structure = document.get("structure") or doc.get("structure") or {}
            chapters = structure.get("chapters") or []

        for chapter in chapters:
            chapter_id = chapter.get("id")
            chapter_title = _safe(chapter.get("title"))

            for article in chapter.get("articles", []) or []:
                article_id = article.get("id")
                article_text = _safe(article.get("text") or article.get("content") or "")

                # === Article unit ===
                if article.get("title") or article_text:
                    units.append({
                        "type": "article",
                        "id": article_id,
                        "document_id": doc_id,
                        "chapter_id": chapter_id,
                        "article_id": article_id,
                        "clause_id": "",
                        "point_id": "",
                        "document_type": doc_type,
                        "document_number": doc_number,
                        "issuing_authority": issuing_authority,
                        "date_enacted": date_enacted,
                        "chapter_number": chapter.get("number"),
                        "chapter_title": chapter_title,
                        "article_number": article.get("number"),
                        "article_title": _safe(article.get("title")),
                        "clause_number": "",
                        "clause_text": "",
                        "points_text": "",
                        "text": f"{_safe(article.get('title'))} {article_text}".strip(),
                    })

                # === Clause units (gộp points) ===
                for clause in article.get("clauses", []) or []:
                    clause_id = clause.get("id")
                    clause_text = _safe(clause.get("text", ""))
                    if not clause_text:
                        continue

                    points_blob = _build_points_blob(clause)
                    embed_text = _build_clause_blob(article, clause, chapter_title)

                    units.append({
                        "type": "clause",
                        "id": clause_id,
                        "document_id": doc_id,
                        "chapter_id": chapter_id,
                        "article_id": article_id,
                        "clause_id": clause_id,
                        "point_id": "",
                        "document_type": doc_type,
                        "document_number": doc_number,
                        "issuing_authority": issuing_authority,
                        "date_enacted": date_enacted,
                        "chapter_number": chapter.get("number"),
                        "chapter_title": chapter_title,
                        "article_number": article.get("number"),
                        "article_title": _safe(article.get("title")),
                        "clause_number": clause.get("number"),
                        "clause_text": clause_text,
                        "points_text": points_blob,
                        "text": embed_text,
                    })

    return units


# ============================================================
# 6. EMBEDDING (Local sentence-transformers)
# ============================================================

class HFEmbedder:
    def __init__(self, model: str, batch_size: int = 64):
        log.info("Loading local model: %s (downloads on first run) ...", model)
        self.model = SentenceTransformer(model)
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()


# ============================================================
# 7. PINECONE
# ============================================================

def ensure_index(pc: _Pinecone, name: str, dim: int) -> None:
    existing = {ix.name for ix in pc.list_indexes()}
    if name in existing:
        log.info("Pinecone index '%s' already exists.", name)
        return
    log.info("Creating Pinecone index '%s' (dim=%d, metric=cosine) ...", name, dim)
    pc.create_index(
        name=name,
        dimension=dim,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
    )
    for _ in range(30):
        if name in {ix.name for ix in pc.list_indexes()}:
            desc = pc.describe_index(name)
            if getattr(desc, "status", {}).get("ready", True):
                break
        time.sleep(2)
    log.info("Index '%s' ready.", name)


def upsert_in_batches(
    index,
    units: list[dict[str, Any]],
    vectors: list[list[float]],
    batch_size: int = 100,
) -> None:
    assert len(units) == len(vectors)
    n = len(units)
    for i in tqdm(range(0, n, batch_size), desc="Upserting", unit="batch"):
        batch_units = units[i : i + batch_size]
        batch_vecs = vectors[i : i + batch_size]
        ids = [f"{u['type']}:{_safe_id(u['id'])}" for u in batch_units]
        meta = [
            {
                "type":              u["type"],
                "document_id":       u["document_id"],
                "chapter_id":        u["chapter_id"] or "",
                "article_id":        u["article_id"],
                "clause_id":         u["clause_id"] or "",
                "point_id":          "",
                "source_file":       "",
                "document_type":     u.get("document_type") or "",
                "document_number":   u.get("document_number") or "",
                "issuing_authority": u.get("issuing_authority") or "",
                "date_enacted":     u.get("date_enacted") or "",
                "chapter_number":   str(u.get("chapter_number") or ""),
                "chapter_title":    u.get("chapter_title") or "",
                "article_number":   str(u.get("article_number") or ""),
                "article_title":    u.get("article_title") or "",
                "clause_number":   str(u.get("clause_number") or ""),
                "clause_text":     u.get("clause_text") or "",
                "points_text":      u.get("points_text") or "",
                "text":             u["text"],
            }
            for u in batch_units
        ]
        index.upsert(vectors=list(zip(ids, batch_vecs, meta)))


# ============================================================
# 8. VERIFY
# ============================================================

def verify(index, units: list[dict[str, Any]], embedder: HFEmbedder) -> None:
    log.info("Verifying with a sample query ...")
    sample_text = units[0]["text"][:200] if units else "trật tự an toàn giao thông đường bộ"
    qvec = embedder.embed([sample_text])[0]
    res = index.query(vector=qvec, top_k=3, include_metadata=True)
    print("\n--- Top 3 matches ---")
    for m in res.matches:
        meta = m.get("metadata", {})
        print(
            f"  score={m['score']:.3f}  "
            f"id={m['id']}  type={meta.get('type')}  "
            f"number={meta.get('article_number') or meta.get('clause_number')}  "
            f"title='{meta.get('article_title', meta.get('clause_text', ''))[:60]}'"
        )


# ============================================================
# 9. MAIN
# ============================================================

def main() -> None:
    log.info("=== Import to Pinecone ===")
    log.info("Document folder: %s", DOC_DOCUMENT_DIR)

    documents = load_documents(DOC_DOCUMENT_DIR)
    units = build_units(documents)
    log.info("Total vector units: %d", len(units))
    if not units:
        log.warning("Nothing to embed. Exiting.")
        return

    by_type = {}
    for u in units:
        by_type.setdefault(u["type"], []).append(u)
    for t, arr in sorted(by_type.items()):
        log.info("  - %s: %d vectors", t, len(arr))

    embedder = HFEmbedder(EMBEDDING_MODEL, batch_size=EMBEDDING_BATCH)
    texts = [u["text"] for u in units]
    vectors = embedder.embed(texts)
    log.info("Got %d vectors (dim=%d)", len(vectors), len(vectors[0]) if vectors else 0)

    pc = _Pinecone(api_key=PINECONE_API_KEY)
    existing = {ix.name for ix in pc.list_indexes()}

    # Rebuild: xóa index cũ nếu tồn tại
    if PINECONE_INDEX_NAME in existing:
        log.info("Deleting existing index '%s' ...", PINECONE_INDEX_NAME)
        pc.delete_index(PINECONE_INDEX_NAME)
        # Chờ xóa hoàn toàn (Pinecone serverless có thể mất vài giây)
        for _ in range(15):
            if PINECONE_INDEX_NAME not in {ix.name for ix in pc.list_indexes()}:
                break
            time.sleep(1)
        log.info("Index deleted.")

    ensure_index(pc, PINECONE_INDEX_NAME, EMBEDDING_DIM)
    index = pc.Index(PINECONE_INDEX_NAME)

    upsert_in_batches(index, units, vectors, batch_size=100)
    log.info("Upsert complete.")

    verify(index, units, embedder)
    log.info("PINECONE IMPORT DONE!")


if __name__ == "__main__":
    main()
