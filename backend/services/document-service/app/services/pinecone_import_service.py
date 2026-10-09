"""Pinecone import service — Lift from data_import/import_data_pinecone.py.

Multi-level chunking strategy:
    - Article vector  : title + full text (no clause text)
    - Clause vector   : clause text + ALL points gộp vào (parent context)

Metadata mỗi vector chứa ĐẦY ĐỦ id của các cấp cha:
    document_id, chapter_id, article_id, clause_id, point_id=""
  → dùng để truy xuất Neo4j sau khi retrieval.
"""
from __future__ import annotations

import logging
import os
import time
import unicodedata
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pinecone import Pinecone

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from app.core.config import (
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
)

log = logging.getLogger("document-service.pinecone_import")

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
EMBEDDING_BATCH = 32


def _safe_id(raw_id: Optional[str]) -> str:
    """Pinecone requires ASCII vector IDs."""
    if not raw_id:
        return ""
    s = raw_id.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s


def _safe(v: Optional[str]) -> str:
    return (v or "").strip() or ""


def _infer_doc_type(doc: Dict[str, Any]) -> str:
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


def _build_points_blob(clause: Dict[str, Any]) -> str:
    """Gộp text của tất cả điểm thành 1 chuỗi."""
    points = clause.get("points", []) or []
    if not points:
        return ""
    return "\n".join(
        f"{p.get('number', '?')}) {_safe(p.get('text'))}"
        for p in points
    )


def _build_clause_blob(
    article: Dict[str, Any],
    clause: Dict[str, Any],
    chapter_title: str,
) -> str:
    """Build text được embed cho 1 clause vector (gộp clause + points)."""
    parts = []
    if chapter_title:
        parts.append(f"[Chương {chapter_title}]")
    parts.append(f"Điều {article.get('number', '')}. {_safe(article.get('title', ''))}")
    parts.append(f"Khoản {clause.get('number', '')}: {_safe(clause.get('text', ''))}")
    points_blob = _build_points_blob(clause)
    if points_blob:
        parts.append(f"Các điểm:\n{points_blob}")
    return "\n".join(parts).strip()


def build_units(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Emit Article vector + Clause vector (gộp points) cho mỗi document."""
    units: List[Dict[str, Any]] = []
    for doc in documents:
        law = doc.get("document") or {}
        doc_id = law.get("id")
        if not doc_id:
            continue
        doc_type = _infer_doc_type(law)
        doc_number = law.get("number") or ""
        issuing_authority = _safe(law.get("issuing_authority"))
        date_enacted = law.get("date_enacted") or ""

        chapters = doc.get("chapters", []) or []

        for chapter in chapters:
            chapter_id = chapter.get("id")
            chapter_title = _safe(chapter.get("title"))

            for article in chapter.get("articles", []) or []:
                article_id = article.get("id")
                article_text = _safe(article.get("text") or article.get("content") or "")

                # --- Article unit ---
                if article.get("title") or article_text:
                    article_text_full = f"{_safe(article.get('title'))} {article_text}".strip()
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
                        "text": article_text_full,
                    })

                # --- Clause units (gộp points) ---
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


class HFEmbedder:
    """Sentence-transformer wrapper."""
    def __init__(self, model: str = EMBEDDING_MODEL, batch_size: int = EMBEDDING_BATCH):
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers not installed. Run: pip install sentence-transformers")
        log.info("Loading model: %s ...", model)
        self.model = SentenceTransformer(model)
        self.batch_size = batch_size

    def embed(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()


class PineconeImportService:
    """Service import law.json → vectors vào Pinecone."""

    def __init__(
        self,
        index_name: Optional[str] = None,
        api_key: Optional[str] = None,
        embedder: Optional[HFEmbedder] = None,
    ):
        api_key = api_key or PINECONE_API_KEY
        if not api_key:
            raise ValueError("Missing PINECONE_API_KEY")
        self._pc = Pinecone(api_key=api_key)
        self._index_name = index_name or PINECONE_INDEX_NAME or "law-rag-v1"
        self._embedder = embedder
        self._index = None

    @property
    def index(self):
        if self._index is None:
            self._index = self._pc.Index(self._index_name)
        return self._index

    def ensure_index(self, dim: int = EMBEDDING_DIM) -> None:
        existing = {ix.name for ix in self._pc.list_indexes()}
        if self._index_name in existing:
            log.info("Pinecone index '%s' already exists.", self._index_name)
            return
        log.info("Creating Pinecone index '%s' (dim=%d)...", self._index_name, dim)
        self._pc.create_index(
            name=self._index_name,
            dimension=dim,
            metric="cosine",
            spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
        )
        # Wait for ready
        for _ in range(30):
            if self._index_name in {ix.name for ix in self._pc.list_indexes()}:
                try:
                    desc = self._pc.describe_index(self._index_name)
                    if getattr(desc, "status", {}).get("ready", True):
                        break
                except Exception:
                    pass
            time.sleep(2)
        log.info("Index '%s' ready.", self._index_name)

    def import_document(
        self,
        document: Dict[str, Any],
        namespace: str = "",
        batch_size: int = 100,
    ) -> int:
        """Import 1 document vào Pinecone.

        Returns số vectors đã upsert.
        """
        units = build_units([document])
        if not units:
            log.info("No units generated for document %s", document.get("document", {}).get("id"))
            return 0

        # Filter vectors chỉ cho document này (just in case)
        doc_id = document.get("document", {}).get("id")
        units = [u for u in units if u.get("document_id") == doc_id]
        if not units:
            return 0

        return self._upsert_units(units, namespace=namespace, batch_size=batch_size)

    def import_relationships_units(
        self,
        document: Dict[str, Any],
        namespace: str = "",
        batch_size: int = 100,
    ) -> int:
        """Import additional relationship-context units (optional, future)."""
        return 0

    def _upsert_units(
        self,
        units: List[Dict[str, Any]],
        namespace: str = "",
        batch_size: int = 100,
    ) -> int:
        """Embed + upsert units vào Pinecone (theo batch)."""
        if not units:
            return 0

        if self._embedder is None:
            self._embedder = HFEmbedder()

        # Lazy init index
        self.ensure_index()

        n_total = 0
        for i in range(0, len(units), batch_size):
            batch_units = units[i: i + batch_size]
            texts = [u["text"] for u in batch_units]
            vectors = self._embedder.embed(texts)
            ids = [f"{u['type']}:{_safe_id(u['document_id'])}:{_safe_id(u['id'])}" for u in batch_units]
            meta = [
                {
                    "type":              u["type"],
                    "document_id":       u["document_id"],
                    "chapter_id":        u.get("chapter_id") or "",
                    "article_id":        u.get("article_id") or "",
                    "clause_id":         u.get("clause_id") or "",
                    "point_id":          "",
                    "document_type":     u.get("document_type", ""),
                    "document_number":   u.get("document_number", ""),
                    "issuing_authority": u.get("issuing_authority", ""),
                    "date_enacted":      u.get("date_enacted", ""),
                    "chapter_number":    str(u.get("chapter_number", "")),
                    "chapter_title":     u.get("chapter_title", ""),
                    "article_number":    str(u.get("article_number", "")),
                    "article_title":     u.get("article_title", ""),
                    "clause_number":     str(u.get("clause_number", "")),
                    "clause_text":       u.get("clause_text", "")[:8000],  # trim nếu quá dài
                    "points_text":       u.get("points_text", "")[:8000],
                }
                for u in batch_units
            ]

            try:
                self.index.upsert(
                    vectors=list(zip(ids, vectors, meta)),
                    namespace=namespace,
                )
                n_total += len(batch_units)
                log.info("Pinecone upsert batch %d-%d OK (%d total)",
                         i, i + len(batch_units), n_total)
            except Exception as exc:
                log.exception("Pinecone upsert batch %d-%d failed: %s",
                              i, i + len(batch_units), exc)
                raise
        return n_total

    def delete_document(self, law_id: str, namespace: str = "") -> int:
        """Xoá tất cả vectors thuộc 1 document_id.

        Returns số vectors đã xoá (best-effort).
        """
        # Build filter for document_id
        try:
            self.index.delete(
                filter={"document_id": {"$eq": law_id}},
                namespace=namespace,
            )
            log.info("Pinecone delete filter document_id=%s OK", law_id)
            return 1
        except Exception as exc:
            log.exception("Pinecone delete failed: %s", exc)
            return 0


# Standalone helper
def get_pinecone_service() -> PineconeImportService:
    return PineconeImportService()
