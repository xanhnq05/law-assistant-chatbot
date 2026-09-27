"""
B5 - LegalContext: Public contract giữa B4 (Retrieval) và B6/B7 (Gen + Verify).

Đây là "internal public API" của B5. Developer implement B6/B7 chỉ cần đọc
file này là biết B5 cung cấp gì, KHÔNG cần đọc code B4.

Design principles:
    1. B5 KHÔNG suy luận thêm nội dung pháp luật.
    2. B5 KHÔNG tạo evidence mới — chỉ wrap + organize + dedup + format.
    3. Mọi field đều derive từ B4 output (xem context.py / retrieval.py).
    4. Evidence là source of truth; formatted_context chỉ là presentation.
    5. Citation ↔ Evidence là 1-1 (B7 dùng để verify claim↔cite↔evidence↔source).

Backward compatibility:
    - build_context_for_llm() và build_sources_for_response() ở
      app/rag/steps/context_builder.py được GIỮ NGUYÊN — orchestrator cũ
      vẫn chạy được nếu chưa migrate sang LegalContext.
    - ChatResponse / SourceItem (Pydantic trong app/core/models.py)
      KHÔNG đổi — API public giữ nguyên.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.rag.context import build_citation

log = logging.getLogger("rag-service")


# ============================================================
# REQUEST (echo từ B2/B3/B4)
# ============================================================
class RequestInfo(BaseModel):
    """Echo của input đã qua B2/B3. B6 dùng original_query; B7 dùng intent."""

    model_config = ConfigDict(extra="ignore")

    original_query: str = Field(..., description="Câu hỏi user gốc, không qua xử lý.")
    normalized_query: str = Field(..., description="Output B2 (cleaned_query).")
    retrieval_query: str = Field(..., description="Query thực tế dùng cho embedding (B3).")
    language: str = Field(default="vi", description="Mặc định 'vi' (project hiện chỉ VI).")
    intent: str = Field(default="general_info", description="B2 intent: penalty/rule/procedure/general_info.")
    legal_domain: str = Field(default="", description="B2 legal_domain.")
    key_terms: list[str] = Field(default_factory=list, description="B2 key_legal_terms.")


# ============================================================
# STABLE ID (dùng để dedup + hierarchy)
# ============================================================
class StableId(BaseModel):
    """Neo4j node IDs cho mỗi evidence. Dùng làm dedup key chính."""

    model_config = ConfigDict(extra="ignore")

    document_id: str | None = None
    chapter_id: str | None = None
    article_id: str | None = None
    clause_id: str | None = None
    point_id: str | None = None

    def dedup_key(self) -> str:
        """Key ổn định để dedup — finest level có sẵn trong B4.

        Thứ tự ưu tiên: point > clause > article > chapter > document.
        Nếu chỉ có document_id → 2 văn bản khác nhau không bao giờ trùng key.
        """
        if self.point_id:
            return f"point:{self.point_id}"
        if self.clause_id:
            return f"clause:{self.clause_id}"
        if self.article_id:
            return f"article:{self.article_id}"
        if self.chapter_id:
            return f"chapter:{self.chapter_id}"
        if self.document_id:
            return f"document:{self.document_id}"
        return ""


# ============================================================
# SCORES
# ============================================================
class Scores(BaseModel):
    """Các signal từ B4 dùng cho prioritization + B7."""

    model_config = ConfigDict(extra="ignore")

    retrieval_score: float | None = Field(
        default=None, description="Pinecone cosine similarity (raw)."
    )
    final_score: float = Field(
        default=0.0, description="Score sau soft boost (B4 output chính)."
    )
    rerank_score: float | None = Field(
        default=None, description="Cross-encoder rerank score (nếu reranker bật)."
    )


# ============================================================
# EVIDENCE (structured source of truth)
# ============================================================
NodeType = Literal["Document", "Chapter", "Article", "Clause", "Point", "Unknown"]


class EvidenceItem(BaseModel):
    """Một evidence package từ B4. Đây là source of truth cho B6/B7.

    B5 không tự tạo content — chỉ chọn text phù hợp từ B4 block.
    """

    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(..., description="B5-assigned stable ID (EV-NNN).")
    vector_id: str | None = Field(default=None, description="Pinecone vector ID (B4).")
    node_type: NodeType = Field(default="Unknown")
    stable_id: StableId = Field(default_factory=StableId)
    content: str = Field(default="", description="Text pháp luật từ B4 (Neo4j article_text/clause_text).")
    context_block: str = Field(default="", description="LLM-ready block (giữ để back-compat).")
    hierarchy_path: list[str] = Field(
        default_factory=list,
        description="Path pháp lý: ['Document', 'Chương II', 'Điều 7', 'Khoản 2'].",
    )
    scores: Scores = Field(default_factory=Scores)
    source: Literal["pinecone", "neo4j", "hybrid"] = Field(default="pinecone")
    boosted: bool = Field(default=False, description="Có được soft intent boost không.")
    amendments: list[dict[str, str]] = Field(
        default_factory=list,
        description="Forward + backward AMENDS/REPLACES/REPEALS/ADDS từ Neo4j.",
    )
    # Full raw block từ B4 — giữ để back-compat với code B6/B7 đọc các field
    # khác (law_document_*, chapter_number, v.v.) mà không cần đổi schema.
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# HIERARCHY (group evidence theo cấu trúc pháp luật)
# ============================================================
class ClauseRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    clause_id: str = ""
    clause_label: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class ArticleRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    article_id: str = ""
    article_label: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    clauses: list[ClauseRef] = Field(default_factory=list)


class ChapterRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    chapter_id: str = ""
    chapter_label: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    articles: list[ArticleRef] = Field(default_factory=list)


class DocumentRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    document_id: str = ""
    document_label: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    chapters: list[ChapterRef] = Field(default_factory=list)


class HierarchyModel(BaseModel):
    """Group evidence theo cây Document → Chapter → Article → Clause.

    Evidence_id nào không có stable_id vẫn được gom vào 'ungrouped' để
    B7 không mất dấu — nhưng 'documents' là view chính.
    """

    model_config = ConfigDict(extra="ignore")

    documents: list[DocumentRef] = Field(default_factory=list)
    ungrouped_evidence_ids: list[str] = Field(default_factory=list)


# ============================================================
# CITATION
# ============================================================
class CitationDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = ""
    number: str = ""
    title: str = ""
    issuing_authority: str = ""
    date_enacted: str = ""
    date_effective: str = ""


class CitationItem(BaseModel):
    """Citation truy ngược được về evidence (B7 traceability contract)."""

    model_config = ConfigDict(extra="ignore")

    citation_id: str = Field(..., description="B5-assigned (CIT-NNN).")
    evidence_id: str = Field(..., description="FK → EvidenceItem.evidence_id.")
    short: str = Field(..., description="Citation ngắn (vd: 'Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4').")
    document: CitationDocument = Field(default_factory=CitationDocument)
    article: str = ""
    clause: str = ""
    point: str = ""
    source: Literal["neo4j", "pinecone"] = Field(
        default="neo4j",
        description="Nơi metadata citation chính được lấy (neo4j = authoritative).",
    )


# ============================================================
# LEGAL CONTEXT (root)
# ============================================================
class LegalContext(BaseModel):
    """Public output của B5. Input của B6/B7.

    Xem app/rag/schemas/legal_context.py đầu file để biết design principles.
    """

    model_config = ConfigDict(extra="ignore")

    request: RequestInfo
    evidence: list[EvidenceItem] = Field(default_factory=list)
    hierarchy: HierarchyModel = Field(default_factory=HierarchyModel)
    formatted_context: str = ""
    citations: list[CitationItem] = Field(default_factory=list)

    # Meta cho B7 + debug
    stats: dict[str, Any] = Field(default_factory=dict)


# ============================================================
# BUILDER (B5 core)
# ============================================================
class LegalContextBuilder:
    """Builder stateful cho LegalContext.

    - B5 KHÔNG dùng LLM, chỉ transform input.
    - Stable ID assignment (EV-NNN, CIT-NNN) là B5-owned → B7 có thể rely.
    """

    def __init__(self, max_evidence: int = 10) -> None:
        self._evidence_counter = 0
        self._citation_counter = 0
        self._max_evidence = max(1, int(max_evidence))

    # ---------- helpers ----------
    @staticmethod
    def _infer_node_type(block: dict[str, Any]) -> NodeType:
        """Infer node_type từ B4 block.

        B4 có field 'type' từ Pinecone metadata, và 'article_number'/'clause_number'
        từ Neo4j. Ưu tiên field 'type' (Pinecone); fallback theo depth.
        """
        raw = (block.get("type") or "").strip().lower()
        mapping = {
            "document": "Document",
            "chapter": "Chapter",
            "article": "Article",
            "clause": "Clause",
            "point": "Point",
        }
        if raw in mapping:
            return mapping[raw]  # type: ignore[return-value]
        # Fallback: deepest non-empty identifier
        if block.get("clause_number"):
            return "Clause"
        if block.get("article_number"):
            return "Article"
        if block.get("chapter_number"):
            return "Chapter"
        if block.get("law_document_number"):
            return "Document"
        return "Unknown"

    @staticmethod
    def _extract_stable_id(block: dict[str, Any]) -> StableId:
        """Extract stable IDs từ B4 block (Neo4j IDs ưu tiên hơn Pinecone meta)."""
        meta = block.get("pinecone_meta") or {}
        return StableId(
            document_id=block.get("law_document_id")
            or meta.get("document_id"),
            chapter_id=meta.get("chapter_id") or block.get("chapter_id"),
            article_id=meta.get("article_id") or block.get("article_id"),
            clause_id=meta.get("clause_id") or block.get("clause_id"),
            point_id=meta.get("point_id") or block.get("point_id"),
        )

    @staticmethod
    def _build_hierarchy_path(block: dict[str, Any], node_type: NodeType) -> list[str]:
        """Build human-readable hierarchy path từ B4 block."""
        path: list[str] = []
        doc_label = (
            f"{block.get('law_document_type','')} {block.get('law_document_number','')}".strip()
            or block.get("law_title", "")
        )
        if doc_label:
            path.append(doc_label)
        else:
            path.append("Document")
        if block.get("chapter_number"):
            path.append(f"Chương {block['chapter_number']}: {block.get('chapter_title','')}".rstrip(": "))
        if block.get("article_number"):
            path.append(f"Điều {block['article_number']}: {block.get('article_title','')}".rstrip(": "))
        if node_type in ("Clause", "Point") and block.get("clause_number"):
            path.append(f"Khoản {block['clause_number']}")
        if node_type == "Point" and block.get("point_number"):
            path.append(f"Điểm {block['point_number']}")
        return path

    @staticmethod
    def _pick_content(block: dict[str, Any]) -> str:
        """Chọn legal content thực sự từ B4 block.

        Ưu tiên:
          1. clause_text / point_text nếu có (sâu nhất)
          2. article_text
          3. context_block (fallback cuối — đã format đẹp nhưng không phải raw legal text)
        """
        # B4 hiện tại chưa populate clause_text / article_text trực tiếp vào block —
        # chúng nằm trong Neo4j ctx row. Orchestrator chỉ truyền context_block đã format.
        # Nên fallback an toàn nhất là context_block.
        if block.get("clause_text"):
            return str(block["clause_text"])
        if block.get("article_text"):
            return str(block["article_text"])
        return str(block.get("context_block") or "")

    @staticmethod
    def _infer_source(block: dict[str, Any]) -> Literal["pinecone", "neo4j", "hybrid"]:
        """Infer retrieval source. B4 hiện tại chủ yếu là pinecone-driven
        (Pinecone hit → Neo4j enrich), nên default = 'hybrid' khi có cả 2 tín hiệu."""
        has_pinecone = bool(block.get("vector_id") or block.get("pinecone_meta"))
        has_neo4j = bool(
            block.get("law_document_number")
            or block.get("article_number")
            or block.get("chapter_number")
        )
        if has_pinecone and has_neo4j:
            return "hybrid"
        if has_neo4j:
            return "neo4j"
        return "pinecone"

    @staticmethod
    def _build_citation_item(block: dict[str, Any], citation_id: str, evidence_id: str) -> CitationItem:
        """Build CitationItem từ B4 block. Short citation reuse build_citation() có sẵn."""
        short = str(block.get("citation") or build_citation(block) or "")
        return CitationItem(
            citation_id=citation_id,
            evidence_id=evidence_id,
            short=short,
            document=CitationDocument(
                type=str(block.get("law_document_type") or ""),
                number=str(block.get("law_document_number") or ""),
                title=str(block.get("law_title") or ""),
                issuing_authority=str(block.get("law_issuing_authority") or ""),
                date_enacted=str(block.get("law_date_enacted") or ""),
                date_effective=str(block.get("law_date_effective") or ""),
            ),
            article=f"Điều {block['article_number']}" if block.get("article_number") else "",
            clause=f"Khoản {block['clause_number']}" if block.get("clause_number") else "",
            point=f"Điểm {block['point_number']}" if block.get("point_number") else "",
            source="neo4j",  # citation text luôn derive từ Neo4j metadata (authoritative)
        )

    # ---------- main build ----------
    def build(
        self,
        *,
        request: RequestInfo,
        retrieved_blocks: list[dict[str, Any]],
        formatted_context: str = "",
    ) -> LegalContext:
        """Build LegalContext từ B4 output.

        Pipeline:
            1. Dedup theo stable_id (point → clause → article → chapter → document)
            2. Sort theo final_score desc (ưu tiên signal đã có từ B4)
            3. Cap max_evidence
            4. Build evidence[] với evidence_id ổn định
            5. Build hierarchy từ evidence
            6. Build citations[] 1-1 với evidence
        """
        stats: dict[str, Any] = {
            "b4_count": len(retrieved_blocks),
            "deduped_count": 0,
            "kept_count": 0,
            "dropped_count": 0,
        }

        if not retrieved_blocks:
            return LegalContext(
                request=request,
                evidence=[],
                hierarchy=HierarchyModel(),
                formatted_context=formatted_context,
                citations=[],
                stats=stats,
            )

        # 1) Dedup
        deduped = self._dedup(retrieved_blocks)
        stats["deduped_count"] = len(deduped)

        # 2) Sort by final_score desc
        deduped.sort(key=lambda b: float(b.get("score", 0.0) or 0.0), reverse=True)

        # 3) Cap
        kept = deduped[: self._max_evidence]
        stats["kept_count"] = len(kept)
        stats["dropped_count"] = max(0, len(deduped) - len(kept))

        # 4) Build evidence
        evidence_items: list[EvidenceItem] = []
        for block in kept:
            self._evidence_counter += 1
            evidence_id = f"EV-{self._evidence_counter:03d}"
            node_type = self._infer_node_type(block)
            stable_id = self._extract_stable_id(block)
            evidence_items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    vector_id=block.get("vector_id"),
                    node_type=node_type,
                    stable_id=stable_id,
                    content=self._pick_content(block),
                    context_block=str(block.get("context_block") or ""),
                    hierarchy_path=self._build_hierarchy_path(block, node_type),
                    scores=Scores(
                        retrieval_score=block.get("pinecone_score"),
                        final_score=float(block.get("score", 0.0) or 0.0),
                        rerank_score=block.get("rerank_score"),
                    ),
                    source=self._infer_source(block),
                    boosted=bool(block.get("boosted", False)),
                    amendments=list(block.get("related_amendments") or []),
                    metadata=block,
                )
            )

        # 5) Build hierarchy
        hierarchy = self._build_hierarchy(evidence_items)

        # 6) Build citations 1-1
        citations: list[CitationItem] = []
        for ev in evidence_items:
            self._citation_counter += 1
            citation_id = f"CIT-{self._citation_counter:03d}"
            citations.append(
                self._build_citation_item(ev.metadata, citation_id, ev.evidence_id)
            )

        return LegalContext(
            request=request,
            evidence=evidence_items,
            hierarchy=hierarchy,
            formatted_context=formatted_context,
            citations=citations,
            stats=stats,
        )

    # ---------- internals ----------
    @staticmethod
    def _dedup(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Dedup theo stable_id (Neo4j IDs). Giữ block có final_score cao nhất.

        Lý do KHÔNG dedup theo citation string: cùng citation ("Điều 6, Khoản 4")
        có thể đến từ 2 văn bản khác nhau (Luật vs Nghị định). Stable ID là chính xác.
        """
        seen: dict[str, dict[str, Any]] = {}
        for b in blocks:
            meta = b.get("pinecone_meta") or {}
            key_parts = [
                b.get("law_document_id") or meta.get("document_id") or "",
                meta.get("chapter_id") or b.get("chapter_id") or "",
                meta.get("article_id") or b.get("article_id") or "",
                meta.get("clause_id") or b.get("clause_id") or "",
                meta.get("point_id") or b.get("point_id") or "",
            ]
            key = "|".join(key_parts)
            if not key.strip("|"):
                # Không có stable ID — fallback dùng citation string
                key = f"fallback:{b.get('citation') or b.get('vector_id') or id(b)}"

            score = float(b.get("score", 0.0) or 0.0)
            if key not in seen or float(seen[key].get("score", 0.0) or 0.0) < score:
                seen[key] = b
        return list(seen.values())

    @staticmethod
    def _build_hierarchy(evidence_items: list[EvidenceItem]) -> HierarchyModel:
        """Group evidence theo cây Document → Chapter → Article → Clause."""
        docs: dict[str, DocumentRef] = {}
        ungrouped: list[str] = []

        for ev in evidence_items:
            sid = ev.stable_id
            if not sid.document_id:
                ungrouped.append(ev.evidence_id)
                continue

            doc = docs.get(sid.document_id)
            if doc is None:
                doc = DocumentRef(
                    document_id=sid.document_id,
                    document_label=ev.hierarchy_path[0] if ev.hierarchy_path else "",
                    evidence_ids=[],
                )
                docs[sid.document_id] = doc
            doc.evidence_ids.append(ev.evidence_id)

            if not sid.chapter_id:
                continue

            chapter = next((c for c in doc.chapters if c.chapter_id == sid.chapter_id), None)
            if chapter is None:
                chapter = ChapterRef(
                    chapter_id=sid.chapter_id,
                    chapter_label=(
                        ev.hierarchy_path[1] if len(ev.hierarchy_path) > 1 else ""
                    ),
                    evidence_ids=[],
                )
                doc.chapters.append(chapter)
            chapter.evidence_ids.append(ev.evidence_id)

            if not sid.article_id:
                continue

            article = next((a for a in chapter.articles if a.article_id == sid.article_id), None)
            if article is None:
                article = ArticleRef(
                    article_id=sid.article_id,
                    article_label=(
                        ev.hierarchy_path[2] if len(ev.hierarchy_path) > 2 else ""
                    ),
                    evidence_ids=[],
                )
                chapter.articles.append(article)
            article.evidence_ids.append(ev.evidence_id)

            if not sid.clause_id:
                continue

            clause = next((k for k in article.clauses if k.clause_id == sid.clause_id), None)
            if clause is None:
                clause = ClauseRef(
                    clause_id=sid.clause_id,
                    clause_label=(
                        ev.hierarchy_path[3] if len(ev.hierarchy_path) > 3 else ""
                    ),
                    evidence_ids=[],
                )
                article.clauses.append(clause)
            clause.evidence_ids.append(ev.evidence_id)

        return HierarchyModel(documents=list(docs.values()), ungrouped_evidence_ids=ungrouped)
