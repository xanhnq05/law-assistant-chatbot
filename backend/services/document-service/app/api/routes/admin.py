"""Admin API routes cho document-service.

Phase 1:
- GET  /admin/health       : public health check
- GET  /admin/me           : JWT required, trả {id, email, role}
- POST /admin/documents/upload : multipart, JWT+admin required
- GET  /admin/documents    : list documents (admin only)

Phase 2:
- GET    /admin/documents/{doc_id}                    : detail + logs
- PATCH  /admin/documents/{doc_id}/metadata          : edit metadata
- DELETE /admin/documents/{doc_id}                   : cascade delete
- POST   /admin/documents/{doc_id}/reparse           : trigger re-parse (stub)

Phase 3+:
- GET    /admin/review          : list AMBIGUOUS mapping cần confirm
- POST   /admin/review/{change_id}/confirm
"""
from __future__ import annotations

import json
from typing import List

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from app.core.config import log
from app.repositories.auth_guard import get_current_user, require_admin
from app.schemas.document import (
    AdminMeResponse,
    DeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentMetadata,
    DocumentRecord,
    DocumentType,
    MetadataUpdateRequest,
    MetadataUpdateResponse,
    ProcessingStatus,
    ProcessingLogEntry,
    ReparseResponse,
    UploadResponse,
)
from app.services import document_upload_service

router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================
# PUBLIC
# ============================================================
@router.get("/health")
def health():
    """Public health check (không cần JWT)."""
    return {"status": "ok", "service": "document-service"}


# ============================================================
# ME
# ============================================================
@router.get("/me", response_model=AdminMeResponse)
def admin_me(user: dict = Depends(get_current_user)):
    """Trả thông tin user đã đăng nhập (cần JWT, không yêu cầu admin)."""
    return AdminMeResponse(
        id=user["id"],
        email=user["email"],
        name=user.get("name"),
        role=user.get("role", "user"),
    )


# ============================================================
# UPLOAD
# ============================================================
@router.post(
    "/documents/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="Một hoặc nhiều file PDF/DOCX"),
    metadata_json: str = Form(
        ...,
        description="JSON string của DocumentMetadata (form-data không support nested object trực tiếp)",
    ),
    user: dict = Depends(require_admin),
):
    """Upload file(s) + metadata cho 1 Document.

    Flow:
        1. Upload files lên Cloud (sync, nhanh)
        2. Tạo Mongo record với status=PROCESSING
        3. Trả response NGAY (user có thể vào xem processing log)
        4. Background: chạy parse pipeline → import Neo4j + Pinecone

    Nếu pipeline fail, document được mark FAILED — user thấy qua UI.
    """
    # Parse metadata từ form-data
    try:
        meta_dict = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"metadata_json không phải JSON hợp lệ: {exc}",
        )

    try:
        metadata = DocumentMetadata.model_validate(meta_dict)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Metadata không hợp lệ: {exc}",
        )

    doc_id, uploaded = await document_upload_service.handle_upload(
        files=files,
        metadata=metadata,
        user_id=user["id"],
        background_tasks=background_tasks,
    )

    return UploadResponse(
        doc_id=doc_id,
        document_type=metadata.document_type,
        status=ProcessingStatus.PROCESSING,
        files=uploaded,
        message="Upload thành công. Pipeline đang xử lý — bạn có thể xem processing log.",
    )


# ============================================================
# LIST
# ============================================================
@router.get("/documents", response_model=DocumentListResponse)
def list_my_documents(
    limit: int = 50,
    user: dict = Depends(require_admin),
):
    """List documents admin hiện tại đã upload."""
    docs = document_upload_service.list_documents(user_id=user["id"], limit=limit)
    return DocumentListResponse(documents=docs, total=len(docs))


# ============================================================
# Phase 2 — Detail / Edit / Delete / Re-parse
# ============================================================
@router.get("/documents/{doc_id}", response_model=DocumentDetailResponse)
def get_document_detail(
    doc_id: str,
    user: dict = Depends(require_admin),
):
    """Chi tiết 1 document + processing logs."""
    doc = document_upload_service.get_document(doc_id)
    raw_logs = document_upload_service.get_processing_logs(doc_id)
    logs = [ProcessingLogEntry(**row) for row in raw_logs]
    return DocumentDetailResponse(document=doc, logs=logs)


@router.patch(
    "/documents/{doc_id}/metadata",
    response_model=MetadataUpdateResponse,
)
def patch_metadata(
    doc_id: str,
    patch: MetadataUpdateRequest,
    user: dict = Depends(require_admin),
):
    """Cập nhật metadata (chỉ các field được gửi).

    Không thay đổi files. Không thay đổi status processing (trừ khi field
    `status` trong metadata được gửi).
    """
    payload = patch.model_dump(exclude_unset=True)
    updated = document_upload_service.update_metadata(doc_id, payload)
    return MetadataUpdateResponse(
        doc_id=doc_id,
        document=updated,
        message="Metadata updated successfully",
    )


@router.delete("/documents/{doc_id}", response_model=DeleteResponse)
def delete_document_endpoint(
    doc_id: str,
    user: dict = Depends(require_admin),
):
    """Xoá document + cascade (Supabase files + local JSON + Mongo record)."""
    result = document_upload_service.delete_document(doc_id)
    return DeleteResponse(**result)


@router.post(
    "/documents/{doc_id}/reparse",
    response_model=ReparseResponse,
)
def reparse_document_endpoint(
    doc_id: str,
    user: dict = Depends(require_admin),
):
    """Trigger re-parse (Phase 2: stub)."""
    new_status, log_messages = document_upload_service.trigger_reparse(doc_id)
    log.info(
        "Re-parse (stub) for %s by admin=%s. messages=%s",
        doc_id,
        user.get("email"),
        log_messages,
    )
    return ReparseResponse(
        doc_id=doc_id,
        status=new_status,
    )
