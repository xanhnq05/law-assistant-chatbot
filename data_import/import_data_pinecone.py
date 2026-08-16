"""
Import legal documents from JSON files into Pinecone vector DB.

Behavior:
  * Reads EVERY *.json file under doc/ folder (recursive).
  * Normalizes two input schemas:
      Schema A (Luật): { document, chapters: [...] }
      Schema B (Nghị định): { document, structure: { chapters: [...] } }
  * Builds text units from Article / Clause / Point nodes -- one vector
    per non-empty text unit.
  * Vector ID format: "{type}:{id}"  e.g. "article:L36-2024-QH15-CI-A02"
  * Embeddings: Local sentence-transformers
    sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2  (384 dim,
    strong Vietnamese support, no API key needed).
  * Metadata per vector:
        type, id, law_id, chapter_id, article_id, clause_id, point_id,
        document_type, document_number, issuing_authority, date_enacted,
        source_file, number, title, text, page_start, page_end

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
from pathlib import Path
from typing import Any, Iterable

import unicodedata

from dotenv import load_dotenv
from pinecone import Pinecone as _Pinecone  # workaround for pinecone 9.x missing init exports
Pinecone = _Pinecone
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


def _safe_id(raw_id: str) -> str:
    """Pinecone requires ASCII vector IDs.
    Vietnamese id may include 'đ' / 'Đ' -- normalize to 'd' / 'D'."""
    if raw_id is None:
        return ""
    # đ/Đ -> d/D first (NFKD keeps them, then strip combining marks)
    s = raw_id.replace("đ", "d").replace("Đ", "D")
    # Strip remaining diacritics just in case
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s


# ============================================================
# 1. CONFIG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pinecone-import")

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = "law-rag-v1"

# Local sentence-transformers model (multilingual, strong Vietnamese support).
# The model will be downloaded on first run (~470MB), then cached offline.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
EMBEDDING_BATCH = 64            # texts per local encode() call

if not PINECONE_API_KEY:
    log.error("Missing PINECONE_API_KEY in .env")
    sys.exit(1)


# ============================================================
# 2. PATHS
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
DOC_DIR = (SCRIPT_DIR.parent / "doc").resolve()


# ============================================================
# 3. LOAD JSON
# ============================================================

def load_all_documents(DOC_DIR: Path) -> list[dict[str, Any]]:
    json_paths = sorted(glob.glob(str(DOC_DIR / "**" / "*.json"), recursive=True))
    if not json_paths:
        log.error(f"No .json files found in {DOC_DIR}")
        sys.exit(1)

    documents: list[dict[str, Any]] = []
    for path in json_paths:
        rel = Path(path).relative_to(DOC_DIR)
        try:
            with open(path, "r", encoding="utf-8") as f:
                documents.append(json.load(f))
            log.info(f"Loaded {rel}")
        except Exception:
            log.exception(f"Failed to read {rel}")

    return documents


# ============================================================
# 4. BUILD UNITS
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


def build_units(documents: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Walk all documents and emit one dict per (Article|Clause|Point) that has
    a non-empty text/title.  Each dict = one vector to upsert.
    """
    units: list[dict[str, Any]] = []

    for doc in documents:
        law = doc.get("document") or {}
        law_id = law.get("id")
        source_file = law.get("source_file")
        # document_type may be missing on Luật files; default to "Luật".
        raw_doc_type = law.get("document_type") or law.get("type") or ""
        if raw_doc_type:
            document_type = raw_doc_type
        elif law_id and law_id.upper().startswith("L"):
            document_type = "Luật"
        elif law_id and law_id.upper().startswith("PL"):
            document_type = "Pháp lệnh"
        else:
            document_type = "Văn bản"
        document_number = law.get("document_number") or law.get("number") or ""
        issuing_authority = law.get("issuing_authority") or ""
        date_enacted = law.get("date_enacted") or ""

        chapters = _extract_chapters(doc)

        for chapter in chapters:
            chapter_id = chapter.get("id")

            for article in chapter.get("articles", []) or []:
                article_id = article.get("id")
                # Schema B (Nghị định 168) stores full text in `content`,
                # Schema A (Luật 36) stores it in `text` (or in clauses).
                article_text = (article.get("text") or article.get("content") or "").strip()
                # Use the article's title + text as the embedded text.
                article_blob = " ".join(
                    filter(None, [article.get("title", ""), article_text])
                ).strip()
                if article_blob:
                    units.append({
                        "type": "article",
                        "id": article_id,
                        "law_id": law_id,
                        "chapter_id": chapter_id,
                        "article_id": article_id,
                        "clause_id": "",
                        "point_id": "",
                        "source_file": source_file,
                        "document_type": document_type,
                        "document_number": document_number,
                        "issuing_authority": issuing_authority,
                        "date_enacted": date_enacted,
                        "number": article.get("number"),
                        "title": article.get("title"),
                        "text": article_blob,
                        "page_start": article.get("page_start"),
                        "page_end": article.get("page_end"),
                    })

                for clause in article.get("clauses", []) or []:
                    clause_id = clause.get("id")
                    clause_blob = (clause.get("text") or "").strip()
                    if clause_blob:
                        units.append({
                            "type": "clause",
                            "id": clause_id,
                            "law_id": law_id,
                            "chapter_id": chapter_id,
                            "article_id": article_id,
                            "clause_id": clause_id,
                            "point_id": "",
                            "source_file": source_file,
                            "document_type": document_type,
                            "document_number": document_number,
                            "issuing_authority": issuing_authority,
                            "date_enacted": date_enacted,
                            "number": clause.get("number"),
                            "title": "",
                            "text": clause_blob,
                            "page_start": clause.get("page_start"),
                            "page_end": clause.get("page_end"),
                        })

                    for point in clause.get("points", []) or []:
                        point_id = point.get("id")
                        point_blob = (point.get("text") or "").strip()
                        if point_blob:
                            units.append({
                                "type": "point",
                                "id": point_id,
                                "law_id": law_id,
                                "chapter_id": chapter_id,
                                "article_id": article_id,
                                "clause_id": clause_id,
                                "point_id": point_id,
                                "source_file": source_file,
                                "document_type": document_type,
                                "document_number": document_number,
                                "issuing_authority": issuing_authority,
                                "date_enacted": date_enacted,
                                "number": point.get("number"),
                                "title": "",
                                "text": point_blob,
                                "page_start": point.get("page_start"),
                                "page_end": point.get("page_end"),
                            })

    return units


# ============================================================
# 5. EMBEDDING (Local sentence-transformers)
# ============================================================

class HFEmbedder:
    """Local sentence-transformers embedder. Loads model on first use."""

    def __init__(self, model: str, batch_size: int = 64):
        log.info(f"Loading local model: {model} (downloads on first run) ...")
        self.model = SentenceTransformer(model)
        self.batch_size = batch_size

    def embed(self, texts: list[str]) -> list[list[float]]:
        # SentenceTransformer.encode returns np.ndarray of shape (n, dim).
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True,  # cosine-friendly
        )
        return embeddings.tolist()


# ============================================================
# 6. PINECONE
# ============================================================

def ensure_index(pc: Pinecone, name: str, dim: int) -> None:
    """Create the index if missing."""
    existing = {ix.name for ix in pc.list_indexes()}
    if name in existing:
        log.info(f"Pinecone index '{name}' already exists.")
        return
    log.info(f"Creating Pinecone index '{name}' (dim={dim}, metric=cosine) ...")
    pc.create_index(
        name=name,
        dimension=dim,
        metric="cosine",
        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
    )
    # Wait for it to be ready.
    for _ in range(30):
        if name in {ix.name for ix in pc.list_indexes()}:
            desc = pc.describe_index(name)
            if getattr(desc, "status", {}).get("ready", True):
                break
        time.sleep(2)
    log.info(f"Index '{name}' ready.")


def upsert_in_batches(index, units: list[dict[str, Any]], vectors: list[list[float]],
                      batch_size: int = 100) -> None:
    """Upsert (id, vector, metadata) tuples to Pinecone in batches of 100."""
    assert len(units) == len(vectors)
    n = len(units)
    for i in tqdm(range(0, n, batch_size), desc="Upserting", unit="batch"):
        batch_units = units[i : i + batch_size]
        batch_vecs = vectors[i : i + batch_size]
        ids = [f"{u['type']}:{_safe_id(u['id'])}" for u in batch_units]
        meta = [
            {
                "type":              u["type"],
                "law_id":            u["law_id"],
                "chapter_id":        u["chapter_id"],
                "article_id":        u["article_id"],
                "clause_id":         u["clause_id"],
                "point_id":          u["point_id"],
                "source_file":       u["source_file"] or "",
                "document_type":     u.get("document_type") or "",
                "document_number":   u.get("document_number") or "",
                "issuing_authority": u.get("issuing_authority") or "",
                "date_enacted":      u.get("date_enacted") or "",
                "number":            str(u["number"]) if u["number"] is not None else "",
                "title":             u["title"] or "",
                "text":              u["text"],
                "page_start":        int(u["page_start"]) if u.get("page_start") is not None else 0,
                "page_end":          int(u["page_end"])   if u.get("page_end")   is not None else 0,
            }
            for u in batch_units
        ]
        index.upsert(vectors=list(zip(ids, batch_vecs, meta)))


# ============================================================
# 7. VERIFY
# ============================================================

def verify(index, sample: list[dict[str, Any]], embedder: HFEmbedder) -> None:
    log.info("Verifying with a sample query ...")
    query_text = (
        sample[0]["text"][:200] if sample else "trật tự an toàn giao thông đường bộ"
    )
    qvec = embedder.embed([query_text])[0]
    res = index.query(vector=qvec, top_k=3, include_metadata=True)
    print("\n--- Top 3 matches ---")
    for m in res.matches:
        meta = m.get("metadata", {})
        print(f"  score={m['score']:.3f}  "
              f"id={m['id']}  type={meta.get('type')}  "
              f"number={meta.get('number')}  title='{meta.get('title','')[:60]}'")


# ============================================================
# 8. MAIN
# ============================================================

def main() -> None:
    log.info(f"Scanning JSON files under: {DOC_DIR}")
    documents = load_all_documents(DOC_DIR)
    units = build_units(documents)
    log.info(f"Total vector units to embed: {len(units)}")
    if not units:
        log.warning("Nothing to embed. Exiting.")
        return

    embedder = HFEmbedder(EMBEDDING_MODEL, batch_size=EMBEDDING_BATCH)
    log.info(f"Embedding with model: {EMBEDDING_MODEL}")
    texts = [u["text"] for u in units]
    vectors = embedder.embed(texts)
    log.info(f"Got {len(vectors)} vectors (dim={len(vectors[0]) if vectors else 0})")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    ensure_index(pc, PINECONE_INDEX_NAME, EMBEDDING_DIM)
    index = pc.Index(PINECONE_INDEX_NAME)

    upsert_in_batches(index, units, vectors, batch_size=100)
    log.info("Upsert complete.")

    verify(index, units, embedder)
    log.info("Pinecone IMPORT DONE!")


if __name__ == "__main__":
    main()