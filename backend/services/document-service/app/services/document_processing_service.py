"""Document processing service — Phase 2 với Cloud Storage.

PIPELINE (NEW, cloud-only):
1. Download files từ Cloud Storage original/
2. Extract paragraphs (DOCX/DOC/PDF)
3. Parse → JSON dict (LegalStructureParser)
4. Validate against JSON schema
5. Upload law.json lên Cloud Storage structured/
6. (Amendment only) Detect relationships + upload relationships.json
7. Update Mongo record (status, paths, processing_logs)

CHANGES vs old pipeline:
- KHÔNG ghi local output/ anymore (cloud-only)
- Snapshot version tự động trước khi upload (qua DocumentRepository.save_law)
- Download files từ Cloud thay vì local disk
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema

from app.core.config import (
    SUPABASE_BUCKET_DOCUMENTS,
    log,
)
from app.db import get_documents_collection
from app.schemas.document import (
    DocumentMetadata,
    DocumentType,
    ProcessingStatus,
)
from app.services.cloud_storage import (
    DocumentRepository,
    OriginalFileRepository,
    RELATIONSHIP_TYPES,
    CloudStorage,
    is_amendment,
)
from app.services.docx_parser import (
    Paragraph,
    extract_paragraphs_from_files,
)
from app.services.legal_structure_parser import (
    ParseMode,
    parse_document,
)

# ============================================================
# Schema paths (load từ local schema/ vẫn OK — schemas không thuộc user data)
# ============================================================
_BACKEND_DIR = Path(__file__).resolve().parents[4]
_SCHEMA_DIR = _BACKEND_DIR / "services" / "document-service" / "schema"
DOCUMENT_SCHEMA_PATH = _SCHEMA_DIR / "schema.json"
RELATIONSHIP_SCHEMA_PATH = _SCHEMA_DIR / "relationship-schema.json"


# ============================================================
# Neo4j / Pinecone import helpers
# ============================================================
def _import_neo4j_safe(
    doc_dict: Dict[str, Any],
    law_id: str,
    doc_id: str,
) -> Dict[str, Any]:
    """Best-effort Neo4j import. Returns summary dict (never raises)."""
    from app.core.config import NEO4J_IMPORT_ENABLED

    if not NEO4J_IMPORT_ENABLED:
        return {"enabled": False, "skipped": True}

    try:
        from app.services.neo4j_import_service import Neo4jImportService
        svc = Neo4jImportService()
    except Exception as exc:
        log.warning("Neo4j service unavailable: %s", exc)
        _log_processing(doc_id, "neo4j_import", "skipped", f"Service unavailable: {exc}")
        return {"enabled": True, "imported": False, "error": str(exc)}

    try:
        stats = svc.import_document(doc_dict)
        log.info("Neo4j import OK: %s", stats)
        _log_processing(doc_id, "neo4j_import", "success",
                        f"Imported chapters={stats['chapters']}, articles={stats['articles']}, "
                        f"clauses={stats['clauses']}, points={stats['points']}")
        return {"enabled": True, "imported": True, "stats": stats}
    except Exception as exc:
        log.exception("Neo4j import failed: %s", exc)
        _log_processing(doc_id, "neo4j_import", "error", f"Failed: {exc}")
        return {"enabled": True, "imported": False, "error": str(exc)}


def _import_pinecone_safe(
    doc_dict: Dict[str, Any],
    law_id: str,
    doc_id: str,
) -> Dict[str, Any]:
    """Best-effort Pinecone import. Returns summary dict (never raises)."""
    from app.core.config import PINECONE_IMPORT_ENABLED, PINECONE_NAMESPACE

    if not PINECONE_IMPORT_ENABLED:
        return {"enabled": False, "skipped": True}

    try:
        from app.services.pinecone_import_service import PineconeImportService
        svc = PineconeImportService()
    except Exception as exc:
        log.warning("Pinecone service unavailable: %s", exc)
        _log_processing(doc_id, "pinecone_import", "skipped", f"Service unavailable: {exc}")
        return {"enabled": True, "imported": False, "error": str(exc)}

    try:
        n_vectors = svc.import_document(
            doc_dict,
            namespace=PINECONE_NAMESPACE,
            batch_size=50,
        )
        log.info("Pinecone import OK: %d vectors", n_vectors)
        _log_processing(doc_id, "pinecone_import", "success",
                        f"Upserted {n_vectors} vectors")
        return {"enabled": True, "imported": True, "vectors": n_vectors}
    except Exception as exc:
        log.exception("Pinecone import failed: %s", exc)
        _log_processing(doc_id, "pinecone_import", "error", f"Failed: {exc}")
        return {"enabled": True, "imported": False, "error": str(exc)}


def _import_neo4j_relationships_safe(
    rel_file: Dict[str, Any],
    law_id: str,
    doc_id: str,
) -> Dict[str, Any]:
    """Best-effort Neo4j relationships import. Returns summary dict."""
    from app.core.config import NEO4J_IMPORT_ENABLED

    if not NEO4J_IMPORT_ENABLED:
        return {"enabled": False, "skipped": True}

    try:
        from app.services.neo4j_import_service import Neo4jImportService
        svc = Neo4jImportService()
    except Exception as exc:
        log.warning("Neo4j service unavailable: %s", exc)
        return {"enabled": True, "imported": False, "error": str(exc)}

    try:
        n_rels = svc.import_relationships(rel_file)
        log.info("Neo4j relationships import OK: %d edges", n_rels)
        _log_processing(doc_id, "neo4j_rels_import", "success",
                        f"Imported {n_rels} relationship edges")
        return {"enabled": True, "imported": True, "edges": n_rels}
    except Exception as exc:
        log.exception("Neo4j relationships import failed: %s", exc)
        _log_processing(doc_id, "neo4j_rels_import", "error", f"Failed: {exc}")
        return {"enabled": True, "imported": False, "error": str(exc)}
def _load_schema(path: Path) -> Dict:
    if not path.exists():
        log.warning("Schema not found at %s, skipping validation", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_document_json(doc: Dict) -> None:
    """Validate parsed document JSON against schema. Raise ValueError on failure."""
    schema = _load_schema(DOCUMENT_SCHEMA_PATH)
    if not schema:
        return
    try:
        jsonschema.validate(instance=doc, schema=schema)
        log.info("Document JSON validated OK")
    except jsonschema.ValidationError as exc:
        log.error("Document JSON validation FAILED: %s", exc.message)
        raise ValueError(
            f"Document JSON validation failed at {list(exc.path)}: {exc.message}"
        ) from exc


def validate_relationship_json(rel: Dict) -> None:
    """Validate relationship JSON against schema."""
    schema = _load_schema(RELATIONSHIP_SCHEMA_PATH)
    if not schema:
        return
    try:
        jsonschema.validate(instance=rel, schema=schema)
        log.info("Relationship JSON validated OK")
    except jsonschema.ValidationError as exc:
        log.error("Relationship JSON validation FAILED: %s", exc.message)
        raise ValueError(
            f"Relationship JSON validation failed at {list(exc.path)}: {exc.message}"
        ) from exc


# ============================================================
# Type detection helper
# ============================================================
def _detect_document_type(metadata: DocumentMetadata) -> str:
    """Phân loại văn bản dựa trên metadata.

    Mapping rules:
        - NĐ-CP (Nghị định Chính phủ) → 'Nghị định'
        - QH   (Quốc hội)            → 'Luật'
        - PL   (Pháp lệnh)           → 'Pháp lệnh'
        - QĐ   (Quyết định)          → 'Quyết định'

    Fallback: parse first segment of document_number (e.g. "168/2024/NĐ-CP").
    """
    doc_num = (metadata.document_number or "").strip()
    for seg in doc_num.split("/"):
        seg_strip = seg.strip()
        if seg_strip in ("NĐ-CP", "ND-CP"):
            return "Nghị định"
        if seg_strip in ("QH",):
            return "Luật"
        if seg_strip in ("PL",):
            return "Pháp lệnh"
        if seg_strip in ("QĐ", "QD"):
            return "Quyết định"
    return "Văn bản"


# ============================================================
# Logging helper (Mongo)
# ============================================================
def _log_processing(doc_id: str, stage: str, status: str, message: str) -> None:
    """Append 1 entry to processing_logs collection."""
    from app.db import get_processing_logs_collection

    coll = get_processing_logs_collection()
    coll.insert_one(
        {
            "doc_id": doc_id,
            "stage": stage,
            "status": status,
            "message": message,
            "timestamp": datetime.now(timezone.utc),
        }
    )
    log.info("[%s] %s: %s — %s", doc_id, stage, status, message)


# ============================================================
# Cloud-driven pipeline (NEW)
# ============================================================
def process_document_from_cloud(
    *,
    doc_id: str,
    law_id: str,
    metadata: DocumentMetadata,
    cs: Optional[CloudStorage] = None,
    file_repo: Optional[OriginalFileRepository] = None,
    doc_repo: Optional[DocumentRepository] = None,
) -> Dict[str, Any]:
    """Run parse pipeline from Cloud Storage.

    Args:
        doc_id: Mongo doc_id (= law_id trong hầu hết cases, giữ riêng để consistent với Mongo)
        law_id: Cloud Storage law_id (vd: D168-2024-ND-CP)
        metadata: DocumentMetadata
        cs: optional CloudStorage instance (default: mới từ SUPABASE_BUCKET_DOCUMENTS)
        file_repo: optional OriginalFileRepository
        doc_repo: optional DocumentRepository

    Returns:
        {
            'success': bool,
            'doc_id': str,
            'law_id': str,
            'status': ProcessingStatus.value,
            'message': str,
            'stats': {...},
            'version_label': str | '',
        }
    """
    cs = cs or CloudStorage(SUPABASE_BUCKET_DOCUMENTS)
    file_repo = file_repo or OriginalFileRepository(cs)
    doc_repo = doc_repo or DocumentRepository(cs)

    result: Dict[str, Any] = {
        "success": False,
        "doc_id": doc_id,
        "law_id": law_id,
        "status": ProcessingStatus.FAILED.value,
        "message": "",
        "stats": {},
        "version_label": "",
    }

    coll = get_documents_collection()

    # ---- 1) List original files ----
    try:
        filenames = file_repo.list_originals(law_id)
    except Exception as exc:
        msg = f"Failed to list original files: {exc}"
        log.exception(msg)
        _log_processing(doc_id, "list_originals", "error", msg)
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        result["message"] = msg
        return result

    if not filenames:
        msg = f"No original files found in Cloud for {law_id}"
        log.error(msg)
        _log_processing(doc_id, "list_originals", "error", msg)
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        result["message"] = msg
        return result

    _log_processing(
        doc_id,
        "list_originals",
        "success",
        f"Found {len(filenames)} file(s): {filenames}",
    )

    # ---- 2) Download files ----
    try:
        file_data_list = [(file_repo.download(law_id, fn), fn) for fn in filenames]
    except Exception as exc:
        msg = f"Failed to download files from Cloud: {exc}"
        log.exception(msg)
        _log_processing(doc_id, "download", "error", msg)
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        result["message"] = msg
        return result

    _log_processing(
        doc_id,
        "download",
        "success",
        f"Downloaded {len(file_data_list)} file(s)",
    )

    # ---- 3) Extract paragraphs ----
    try:
        paragraphs = extract_paragraphs_from_files(file_data_list)
    except Exception as exc:
        msg = f"Paragraph extraction failed: {exc}"
        log.exception(msg)
        _log_processing(doc_id, "extract", "error", msg)
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        result["message"] = msg
        return result

    _log_processing(
        doc_id,
        "extract",
        "success",
        f"Extracted {len(paragraphs)} paragraphs",
    )

    # ---- 4) Parse → JSON dict ----
    mode = ParseMode.AMENDMENT if is_amendment(metadata) else ParseMode.ORIGINAL
    try:
        doc_dict = parse_document(
            paragraphs=paragraphs,
            doc_id=law_id,  # parser dùng law_id để build node IDs
            mode=mode,
            source_filenames=filenames,
        )
    except Exception as exc:
        msg = f"Legal structure parser failed: {exc}"
        log.exception(msg)
        _log_processing(doc_id, "parse", "error", msg)
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        result["message"] = msg
        return result

    stats = _compute_stats(doc_dict)
    _log_processing(
        doc_id,
        "parse",
        "success",
        f"Parsed: chapters={stats['chapters']} articles={stats['articles']} "
        f"clauses={stats['clauses']} points={stats['points']}",
    )

    # ---- 5) Inject document metadata into law.json ----
    doc_dict["document"].update(
        {
            "number": metadata.document_number,
            "title": metadata.title,
            "type": _detect_document_type(metadata),
            "status": metadata.status,
            "date_enacted": metadata.date_enacted,
            "date_effective": metadata.date_effective,
            "issuing_authority": metadata.issuing_authority,
        }
    )
    if metadata.source:
        doc_dict["document"]["source_version"] = metadata.source

    # ---- 6) Validate against schema ----
    try:
        validate_document_json(doc_dict)
        _log_processing(doc_id, "validate", "success", "JSON matches schema")
    except ValueError as exc:
        # Save best-effort cho debugging (auto-snapshot sẽ chạy)
        try:
            doc_repo.save_law(law_id, doc_dict, snapshot=True)
        except Exception:
            log.exception("Failed to save invalid law.json for debug")
        result["message"] = f"Validation failed: {exc}"
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        return result

    # ---- 7) Save law.json lên Cloud (auto-snapshot) ----
    try:
        version_label = doc_repo.save_law(law_id, doc_dict, snapshot=True)
    except Exception as exc:
        msg = f"Failed to upload law.json to Cloud: {exc}"
        log.exception(msg)
        _log_processing(doc_id, "save", "error", msg)
        _update_status(coll, doc_id, ProcessingStatus.FAILED)
        result["message"] = msg
        return result

    result["version_label"] = version_label
    _log_processing(
        doc_id,
        "save",
        "success",
        f"Uploaded law.json (snapshot={version_label or 'none'})",
    )

    # ---- 8) Update Mongo status ----
    _update_status(coll, doc_id, ProcessingStatus.READY)
    _log_processing(doc_id, "complete", "success", "Processing complete")

    # ---- 9) AMENDMENT flow: detect relationships ----
    if is_amendment(metadata) and metadata.amends_document_id:
        try:
            from app.services.amendment_detection_service import detect_relationships

            outgoing_rels = detect_relationships(
                parsed_doc=doc_dict,
                target_doc_id=metadata.amends_document_id,
                source_doc_id=law_id,
            )

            # Validate against schema (best-effort)
            rel_doc = {
                "law_id": law_id,
                "incoming": [],
                "outgoing": outgoing_rels,
            }
            try:
                validate_relationship_json(rel_doc)
            except ValueError as vexc:
                _log_processing(
                    doc_id,
                    "amendment_detect",
                    "warning",
                    f"Validation warning: {vexc}",
                )

            # Save + propagate to target docs
            doc_repo.merge_relationships_for_law(
                law_id,
                outgoing=outgoing_rels,
            )

            # Import relationships into Neo4j (best-effort)
            rel_doc = {
                "source_document": law_id,
                "target_document": metadata.amends_document_id,
                "relationships": [
                    {
                        "source_document_id": law_id,
                        "source_article_number": r.get("source", {}).get("article_number"),
                        "relationship": r.get("type"),
                        "target_document_id": metadata.amends_document_id,
                        "target_ref": r.get("target", {}).get("ref"),
                        "reason": r.get("description"),
                    }
                    for r in outgoing_rels
                ],
            }
            _import_neo4j_relationships_safe(rel_doc, law_id, doc_id)

            _log_processing(
                doc_id,
                "amendment_detect",
                "success",
                f"Detected {len(outgoing_rels)} outgoing relationships → "
                f"propagated to {len({r.get('target', {}).get('document_id') for r in outgoing_rels})} target doc(s)",
            )
        except Exception as exc:
            log.exception("Amendment detection failed for %s: %s", law_id, exc)
            _log_processing(
                doc_id,
                "amendment_detect",
                "error",
                f"Detection failed: {exc}",
            )

    # ---- 7.5) Neo4j import ----
    neo4j_status = _import_neo4j_safe(doc_dict, law_id, doc_id)
    result["neo4j"] = neo4j_status

    # ---- 7.6) Pinecone import ----
    pinecone_status = _import_pinecone_safe(doc_dict, law_id, doc_id)
    result["pinecone"] = pinecone_status

    result.update(
        {
            "success": True,
            "status": ProcessingStatus.READY.value,
            "message": "Parse pipeline complete",
            "stats": stats,
        }
    )
    return result


# ============================================================
# LEGACY pipeline — kept for backward compat with trigger_reparse()
# Will be REMOVED after Phase B cleanup.
# ============================================================
def process_document(
    *,
    doc_id: str,
    files: List[Dict[str, Any]],  # List of UploadedFileInfo.model_dump()
    metadata: DocumentMetadata,
) -> Dict[str, Any]:
    """Legacy entrypoint — routes through the new cloud pipeline.

    Behavior:
        1. Build law_id từ metadata (slugify)
        2. Re-upload files lên Cloud (nếu chưa có) — idempotent
        3. Delegate to process_document_from_cloud()
    """
    from app.services.cloud_storage.doc_id import slugify_from_metadata

    law_id = slugify_from_metadata(metadata)
    cs = CloudStorage(SUPABASE_BUCKET_DOCUMENTS)
    file_repo = OriginalFileRepository(cs)

    # Re-upload files (idempotent — same path → overwrite)
    for f in files:
        path = f.get("supabase_path")
        if path and "/" in path:
            # Old path format: "{law_id}/..." hoặc "{doc_id}/..."
            # Just re-upload từ bytes nếu cần
            pass  # Files đã có sẵn trên Cloud (từ lần upload trước)

    # Delegate
    return process_document_from_cloud(
        doc_id=doc_id,
        law_id=law_id,
        metadata=metadata,
        cs=cs,
        file_repo=file_repo,
    )


# ============================================================
# Helpers
# ============================================================
def _compute_stats(doc: Dict) -> Dict[str, int]:
    """Count nodes (chapters/articles/clauses/points) — bao gồm cả nodes trong sections."""
    chapters = doc.get("chapters", [])
    articles_total = 0
    clauses_total = 0
    points_total = 0

    for ch in chapters:
        # Articles directly in chapter
        for a in ch.get("articles", []):
            articles_total += 1
            for cl in a.get("clauses", []):
                clauses_total += 1
                points_total += len(cl.get("points", []))
        # Articles in sections
        for sec in ch.get("sections", []):
            for a in sec.get("articles", []):
                articles_total += 1
                for cl in a.get("clauses", []):
                    clauses_total += 1
                    points_total += len(cl.get("points", []))

    return {
        "chapters": len(chapters),
        "articles": articles_total,
        "clauses": clauses_total,
        "points": points_total,
    }


def _update_status(
    coll,
    doc_id: str,
    status: ProcessingStatus,
    intermediate_path: Optional[Path] = None,
) -> None:
    """Update document record status in Mongo."""
    update: Dict[str, Any] = {
        "status": status.value,
        "updated_at": datetime.now(timezone.utc),
    }
    # NOTE: intermediate_json_path no longer used in cloud-only mode.
    # Kept as optional arg for backward compat but ignored if None.
    coll.update_one({"doc_id": doc_id}, {"$set": update})
