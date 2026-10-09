"""Document upload service — Cloud-First design.

FLOW:
    1. Validate files (size, extension, content-type)
    2. Generate doc_id từ metadata (idempotent slugify)
    3. Upload files lên Cloud Storage original/ (qua OriginalFileRepository)
    4. Lưu document record vào Mongo (status=PROCESSING)
    5. Trigger parse pipeline:
        - Download files từ Cloud
        - Extract paragraphs
        - Parse → law.json
        - Upload law.json lên Cloud structured/ (auto-snapshot)
        - (Amendment only) Detect relationships + upload relationships.json
    6. Update Mongo status=READY

PHASE 2 CLOUD CHANGES:
    - KHÔNG ghi local output/document/{doc_id}.json nữa
    - intermediate_json_path trong Mongo trỏ đến Cloud path:
        "cloud:{bucket}:{law_id}/structured/law.json"
    - delete cascade sẽ xoá cả folder {law_id}/ trên Cloud
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, UploadFile, status

from app.core.config import (
    SUPABASE_BUCKET_DOCUMENTS,
    log,
)
from app.db import get_documents_collection, get_processing_logs_collection
from app.schemas.document import (
    DocumentMetadata,
    DocumentRecord,
    DocumentType,
    ProcessingStatus,
    UploadedFileInfo,
)
from app.services.cloud_storage import (
    CloudStorage,
    DocumentRepository,
    OriginalFileRepository,
    is_amendment,
    slugify_from_metadata,
)

# ============================================================
# File constants — re-export từ cloud_storage layer
# ============================================================
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/CDFV2",
    "application/x-msword",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


# ============================================================
# Validators
# ============================================================
def _validate_files(files: List[UploadFile]) -> None:
    """Validate content_type + extension cho tất cả files + duplicate filename.

    Raises HTTPException nếu có bất kỳ file nào không hợp lệ.
    """
    seen: set[str] = set()
    for file in files:
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Filename is required",
            )

        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chỉ chấp nhận file {', '.join(sorted(ALLOWED_EXTENSIONS))}. Got: {ext}",
            )

        if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
            log.warning(
                "Suspicious content_type=%s for filename=%s",
                file.content_type,
                file.filename,
            )

        # Duplicate filename trong cùng 1 request
        if file.filename in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Trùng tên file trong request: '{file.filename}'. Mỗi file phải có tên duy nhất.",
            )
        seen.add(file.filename)


# ============================================================
# Mongo path helpers
# ============================================================
def _cloud_path(bucket: str, relative_path: str) -> str:
    """Build mongo-stored path string dạng 'cloud:{bucket}:{relative_path}'."""
    return f"cloud:{bucket}:{relative_path}"


def _parse_cloud_path(stored: str) -> Optional[Tuple[str, str]]:
    """Parse 'cloud:{bucket}:{path}' → (bucket, path). Return None nếu không match."""
    if not stored or not stored.startswith("cloud:"):
        return None
    parts = stored.split(":", 2)
    if len(parts) != 3:
        return None
    return parts[1], parts[2]


# ============================================================
# Pipeline runner — invoked as background task
# ============================================================
def _run_pipeline_background(
    *,
    doc_id: str,
    law_id: str,
    metadata: "DocumentMetadata",
    cs: "CloudStorage",
    file_repo: "OriginalFileRepository",
) -> None:
    """Run parse pipeline in background. Catches all exceptions."""
    from app.services.document_processing_service import (
        process_document_from_cloud,
    )

    try:
        parse_result = process_document_from_cloud(
            doc_id=doc_id,
            law_id=law_id,
            metadata=metadata,
            cs=cs,
            file_repo=file_repo,
        )
        log.info(
            "[bg] Parse pipeline for %s: success=%s status=%s stats=%s",
            law_id,
            parse_result.get("success"),
            parse_result.get("status"),
            parse_result.get("stats"),
        )
    except Exception as exc:
        log.exception("[bg] Parse pipeline failed for %s: %s", law_id, exc)
        # Mark FAILED so user thấy trong UI
        try:
            coll = get_documents_collection()
            coll.update_one(
                {"doc_id": doc_id},
                {"$set": {
                    "status": ProcessingStatus.FAILED.value,
                    "updated_at": datetime.now(timezone.utc),
                }},
            )
        except Exception:
            log.exception("Failed to mark %s as FAILED after pipeline error", doc_id)


# ============================================================
# Main entry
# ============================================================
async def handle_upload(
    *,
    files: List[UploadFile],
    metadata: DocumentMetadata,
    user_id: str,
    background_tasks: Optional[Any] = None,
) -> Tuple[str, List[UploadedFileInfo]]:
    """Upload files → Cloud → save Mongo record (status=PROCESSING).

    Nếu `background_tasks` (FastAPI BackgroundTasks) được cung cấp, parse
    pipeline sẽ chạy ngầm. Nếu không, vẫn chạy sync (giữ backward compat).

    Returns:
        (doc_id, list of uploaded file info) — trả về NGAY sau khi Mongo record
        đã được tạo với status=PROCESSING. User có thể vào xem processing log
        trong khi pipeline chạy nền.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cần upload ít nhất 1 file.",
        )

    # 1) Validate (batch)
    _validate_files(files)

    # 2) Generate IDs
    law_id = slugify_from_metadata(metadata)
    doc_id = law_id  # doc_id == law_id (consistent với Cloud layout)

    # 3) AMENDMENT sanity check
    if is_amendment(metadata) and not metadata.amends_document_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AMENDMENT document cần chỉ định `amends_document_id`.",
        )

    # 4) Initialize Cloud storage
    cs = CloudStorage(SUPABASE_BUCKET_DOCUMENTS)
    file_repo = OriginalFileRepository(cs)

    # NEW: Check duplicate filename với files đã có trên Cloud
    # Tránh overwrite ngầm. Nếu user thực sự muốn replace, dùng endpoint riêng.
    try:
        existing_files = set(file_repo.list_originals(law_id))
    except Exception:
        existing_files = set()

    for f in files:
        if f.filename and f.filename in existing_files:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"File '{f.filename}' đã tồn tại trong Document này (law_id={law_id}). "
                    f"Xoá file cũ hoặc đổi tên file mới."
                ),
            )

    # 5) Upload files lên Cloud original/
    uploaded: List[UploadedFileInfo] = []

    for f in files:
        content = await f.read()
        size = len(content)
        if size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {f.filename} vượt quá {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.",
            )
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {f.filename} rỗng.",
            )

        try:
            upload_result = file_repo.upload_original(
                law_id=law_id,
                filename=f.filename or "unnamed",
                content=content,
                content_type=f.content_type or "application/octet-stream",
            )
        except Exception as exc:
            log.exception("Cloud upload failed for %s: %s", f.filename, exc)
            # Best-effort cleanup: xoá files đã upload của law_id (tránh orphan)
            self_delete_originals_safely(cs, law_id, uploaded)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Upload Cloud thất bại cho file {f.filename}: {exc}",
            )

        # Build public URL best-effort
        public_url = None
        try:
            public_url = file_repo.get_public_url(law_id, upload_result["safe_filename"])
        except Exception:
            pass

        uploaded.append(
            UploadedFileInfo(
                filename=f.filename or upload_result["safe_filename"],
                supabase_path=upload_result["supabase_path"],
                size_bytes=upload_result["size_bytes"],
                content_type=upload_result["content_type"],
                public_url=public_url,
            )
        )
        log.info(
            "Uploaded %s → %s/%s (%d bytes)",
            f.filename,
            SUPABASE_BUCKET_DOCUMENTS,
            upload_result["supabase_path"],
            size,
        )

    # 6) Lưu Mongo record (status=PROCESSING)
    now = datetime.now(timezone.utc)
    record: Dict[str, Any] = {
        "doc_id": doc_id,
        "law_id": law_id,
        "user_id": user_id,
        "document_type": metadata.document_type.value,
        "status": ProcessingStatus.PROCESSING.value,
        "metadata": metadata.model_dump(mode="json"),
        "files": [f.model_dump(mode="json") for f in uploaded],
        # Cloud paths thay cho local intermediate_json_path
        "structured_law_path": _cloud_path(
            SUPABASE_BUCKET_DOCUMENTS, f"{law_id}/structured/law.json"
        ),
        "structured_relationships_path": _cloud_path(
            SUPABASE_BUCKET_DOCUMENTS, f"{law_id}/structured/relationships.json"
        ),
        "created_at": now,
        "updated_at": now,
    }

    coll = get_documents_collection()
    record_for_set = {k: v for k, v in record.items() if k != "created_at"}
    coll.update_one(
        {"doc_id": doc_id},
        {"$set": record_for_set, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    log.info(
        "Document record upserted (status=PROCESSING): doc_id=%s law_id=%s type=%s files=%d",
        doc_id,
        law_id,
        metadata.document_type.value,
        len(uploaded),
    )

    # 7) Schedule parse pipeline
    if background_tasks is not None:
        # Async mode — chạy nền, response trả về ngay
        background_tasks.add_task(
            _run_pipeline_background,
            doc_id=doc_id,
            law_id=law_id,
            metadata=metadata,
            cs=cs,
            file_repo=file_repo,
        )
        log.info("Pipeline scheduled in background for %s", law_id)
    else:
        # Sync mode (backward compat)
        try:
            from app.services.document_processing_service import (
                process_document_from_cloud,
            )

            parse_result = process_document_from_cloud(
                doc_id=doc_id,
                law_id=law_id,
                metadata=metadata,
                cs=cs,
                file_repo=file_repo,
            )
            log.info(
                "Parse pipeline for %s: success=%s status=%s stats=%s version=%s",
                law_id,
                parse_result.get("success"),
                parse_result.get("status"),
                parse_result.get("stats"),
                parse_result.get("version_label"),
            )
        except Exception as exc:
            log.exception("Parse pipeline raised unhandled exception for %s: %s", law_id, exc)

    return doc_id, uploaded


def self_delete_originals_safely(
    cs: CloudStorage, law_id: str, already_uploaded: List[UploadedFileInfo]
) -> None:
    """Best-effort cleanup khi 1 trong nhiều file upload fail.

    Xoá files đã upload thành công + record Mongo (nếu có).
    """
    for f in already_uploaded:
        try:
            cs.delete(f.supabase_path)
        except Exception:
            log.warning("Cleanup: failed to delete %s", f.supabase_path, exc_info=True)
    try:
        coll = get_documents_collection()
        coll.delete_one({"law_id": law_id})
    except Exception:
        log.warning("Cleanup: failed to delete Mongo record", exc_info=True)


# ============================================================
# List / Detail
# ============================================================
def list_documents(user_id: str | None = None, limit: int = 50) -> List[DocumentRecord]:
    """List documents. Filter theo user_id nếu có."""
    coll = get_documents_collection()
    query: Dict[str, Any] = {}
    if user_id:
        query["user_id"] = user_id

    cursor = coll.find(query).sort("created_at", -1).limit(limit)

    out: List[DocumentRecord] = []
    for doc in cursor:
        doc.pop("_id", None)
        try:
            out.append(DocumentRecord.model_validate(doc))
        except Exception as exc:
            log.warning("Skip invalid document record: %s", exc)
    return out


def get_document(doc_id: str) -> DocumentRecord:
    """Lấy 1 document theo doc_id. Raise 404 nếu không có."""
    coll = get_documents_collection()
    raw = coll.find_one({"doc_id": doc_id})
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' không tồn tại.",
        )
    raw.pop("_id", None)
    try:
        return DocumentRecord.model_validate(raw)
    except Exception as exc:
        log.error("Invalid document record for %s: %s", doc_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document record bị lỗi schema: {exc}",
        )


def get_processing_logs(doc_id: str) -> List[Dict[str, Any]]:
    """Lấy processing logs cho doc_id (best-effort)."""
    coll = get_processing_logs_collection()
    cursor = coll.find({"doc_id": doc_id}).sort("timestamp", 1)
    out: List[Dict[str, Any]] = []
    for row in cursor:
        row.pop("_id", None)
        out.append(
            {
                "stage": row.get("stage", ""),
                "status": row.get("status", ""),
                "message": row.get("message", ""),
                "timestamp": row.get("timestamp"),
            }
        )
    return out


# ============================================================
# Metadata update
# ============================================================
def update_metadata(doc_id: str, patch: Dict[str, Any]) -> DocumentRecord:
    """Patch metadata.

    NOTE: KHÔNG snapshot law.json tự động (caller phải trigger reparse nếu muốn
    regenerate law.json). Metadata chỉ là "title/number/year" — không ảnh hưởng
    nội dung structured JSON.
    """
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body rỗng — không có trường nào để cập nhật.",
        )

    coll = get_documents_collection()
    current = coll.find_one({"doc_id": doc_id})
    if not current:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' không tồn tại.",
        )

    # Merge metadata
    current_meta = current.get("metadata", {})
    merged = {**current_meta, **patch}

    # AMENDMENT validation
    if (
        current.get("document_type") == DocumentType.AMENDMENT.value
        and not merged.get("amends_document_id")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AMENDMENT document cần có `amends_document_id`.",
        )

    now = datetime.now(timezone.utc)
    coll.update_one(
        {"doc_id": doc_id},
        {"$set": {"metadata": merged, "updated_at": now}},
    )

    log.info("Updated metadata for %s (fields=%s)", doc_id, list(patch.keys()))
    return get_document(doc_id)


# ============================================================
# Delete (CASCADE: Cloud folder + Mongo)
# ============================================================
def delete_document(doc_id: str) -> Dict[str, Any]:
    """Xoá document + cascade toàn bộ Cloud folder {law_id}/.

    CHÍNH SÁCH BẢO VỆ THAM CHIẾU:
        Trước khi xoá 1 document, kiểm tra xem có AMENDMENT nào còn
        trỏ tới nó qua `metadata.amends_document_id` hay không. Nếu có
        → TỪ CHỐI xoá (409 Conflict) và trả về danh sách các amendment con
        để user xử lý trước (xoá amendment con, hoặc chuyển chúng sang
        trỏ document gốc khác). Lý do: nếu xoá original mà amendments còn
        trỏ tới sẽ tạo dangling reference → Neo4j relationship mồ côi,
        admin UI select box hiển thị doc_id không tồn tại, gây nhầm lẫn.

    Returns:
        {
          'doc_id': str,
          'law_id': str,
          'deleted_files': [str],      # original/* paths
          'deleted_structured': bool,
          'deleted_versions_count': int,
          'message': str,
        }
    """
    coll = get_documents_collection()
    raw = coll.find_one({"doc_id": doc_id})
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' không tồn tại.",
        )

    # 0) CHẶN XOÁ nếu còn amendment con trỏ tới document này
    #    Query: tìm doc có metadata.amends_document_id == doc_id
    #    (không phân biệt case vì doc_id được slugify uppercase)
    child_amendments = list(
        coll.find(
            {"metadata.amends_document_id": doc_id},
            {"_id": 0, "doc_id": 1, "metadata.title": 1, "status": 1},
        ).sort("doc_id", 1)
    )
    if child_amendments:
        child_ids = [c["doc_id"] for c in child_amendments]
        # 409 Conflict: trạng thái hiện tại mâu thuẫn với thao tác xoá
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"Không thể xoá '{doc_id}' vì còn {len(child_ids)} "
                    f"văn bản sửa đổi đang tham chiếu tới nó. "
                    f"Vui lòng xoá hoặc chuyển các văn bản sửa đổi "
                    f"trước khi xoá văn bản gốc."
                ),
                "doc_id": doc_id,
                "child_amendments": [
                    {
                        "doc_id": c["doc_id"],
                        "title": (c.get("metadata") or {}).get("title", ""),
                        "status": c.get("status", "UNKNOWN"),
                    }
                    for c in child_amendments
                ],
                "child_count": len(child_ids),
            },
        )

    law_id = raw.get("law_id") or doc_id
    cs = CloudStorage(SUPABASE_BUCKET_DOCUMENTS)

    # 1) Delete Cloud folder {law_id}/ (cascade original + structured + versions)
    try:
        doc_repo = DocumentRepository(cs)
        delete_result = doc_repo.delete_law_folder(law_id)
        deleted_count = delete_result.get("deleted", 0)
        log.info("Deleted %d files under %s/", deleted_count, law_id)
    except Exception as exc:
        log.exception("Cascade delete failed for %s/: %s", law_id, exc)
        deleted_count = 0

    # 2) Delete Mongo record
    coll.delete_one({"doc_id": doc_id})
    log.info("Deleted Mongo record: %s", doc_id)

    # 3) Optionally delete processing_logs
    try:
        logs_coll = get_processing_logs_collection()
        logs_coll.delete_many({"doc_id": doc_id})
    except Exception:
        log.warning("Failed to delete processing logs for %s", doc_id, exc_info=True)

    # 4) Cascade: Neo4j
    neo4j_result = {}
    try:
        from app.services.neo4j_import_service import Neo4jImportService
        from app.core.config import NEO4J_IMPORT_ENABLED
        if NEO4J_IMPORT_ENABLED:
            svc = Neo4jImportService()
            neo4j_result = svc.delete_document(law_id)
            log.info("Neo4j cascade delete OK: %s", neo4j_result)
    except Exception as exc:
        log.warning("Neo4j cascade delete failed for %s: %s", law_id, exc)

    # 5) Cascade: Pinecone
    pinecone_result = {}
    try:
        from app.services.pinecone_import_service import PineconeImportService
        from app.core.config import PINECONE_IMPORT_ENABLED, PINECONE_NAMESPACE
        if PINECONE_IMPORT_ENABLED:
            svc = PineconeImportService()
            n_del = svc.delete_document(law_id, namespace=PINECONE_NAMESPACE)
            pinecone_result = {"deleted": n_del > 0}
            log.info("Pinecone cascade delete OK: %s", pinecone_result)
    except Exception as exc:
        log.warning("Pinecone cascade delete failed for %s: %s", law_id, exc)

    return {
        "doc_id": doc_id,
        "law_id": law_id,
        "deleted_files_count": deleted_count,
        "neo4j": neo4j_result,
        "pinecone": pinecone_result,
        "message": f"Document {doc_id} deleted (cascade: {deleted_count} files)",
    }


# ============================================================
# Re-parse
# ============================================================
def trigger_reparse(doc_id: str) -> Tuple[ProcessingStatus, List[str]]:
    """Re-run parse pipeline for an existing document."""
    coll = get_documents_collection()
    raw = coll.find_one({"doc_id": doc_id})
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' không tồn tại.",
        )

    now = datetime.now(timezone.utc)
    coll.update_one(
        {"doc_id": doc_id},
        {"$set": {"status": ProcessingStatus.PROCESSING.value, "updated_at": now}},
    )

    from app.schemas.document import DocumentMetadata
    from app.services.document_processing_service import process_document_from_cloud

    metadata_dict = raw.get("metadata", {})
    try:
        metadata = DocumentMetadata.model_validate(metadata_dict)
    except Exception as exc:
        log.error("Invalid stored metadata for %s: %s", doc_id, exc)
        coll.update_one(
            {"doc_id": doc_id},
            {"$set": {"status": ProcessingStatus.FAILED.value, "updated_at": now}},
        )
        return ProcessingStatus.FAILED, [f"Invalid metadata: {exc}"]

    law_id = raw.get("law_id") or doc_id
    cs = CloudStorage(SUPABASE_BUCKET_DOCUMENTS)
    file_repo = OriginalFileRepository(cs)
    doc_repo = DocumentRepository(cs)

    try:
        result = process_document_from_cloud(
            doc_id=doc_id,
            law_id=law_id,
            metadata=metadata,
            cs=cs,
            file_repo=file_repo,
            doc_repo=doc_repo,
        )
        final_status = ProcessingStatus(result["status"])
        message = result.get("message", "")
        stats = result.get("stats", {})
        log_msg = (
            f"Re-parse complete: status={final_status.value}, "
            f"stats={stats}, message={message}, version={result.get('version_label', '')}"
        )
    except Exception as exc:
        log.exception("Re-parse failed for %s: %s", doc_id, exc)
        coll.update_one(
            {"doc_id": doc_id},
            {"$set": {"status": ProcessingStatus.FAILED.value, "updated_at": now}},
        )
        return ProcessingStatus.FAILED, [f"Re-parse failed: {exc}"]

    return final_status, [log_msg]
