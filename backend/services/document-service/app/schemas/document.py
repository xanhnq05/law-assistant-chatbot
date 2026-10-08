"""Pydantic schemas cho document upload + processing (Phase 1).

Phase 1: chỉ metadata + status tracking.
Phase 2+ sẽ bổ sung RelationshipChange, ValidationResult, ProcessingLog đầy đủ.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from typing_extensions import Self

from pydantic import BaseModel, Field, model_validator


class DocumentType(str, Enum):
    """Loại văn bản."""

    ORIGINAL = "ORIGINAL"
    AMENDMENT = "AMENDMENT"


class ProcessingStatus(str, Enum):
    """Trạng thái xử lý document."""

    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    READY = "READY"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


# Effective status (lowercase, vi-VN) — dùng cho metadata.status
EFFECTIVE_STATUS_ACTIVE = "active"           # Còn hiệu lực
EFFECTIVE_STATUS_PARTIAL = "partial_expired" # Hết hiệu lực một phần
EFFECTIVE_STATUS_EXPIRED = "expired"         # Hết hiệu lực toàn bộ
EFFECTIVE_STATUS_VALUES = frozenset({
    EFFECTIVE_STATUS_ACTIVE,
    EFFECTIVE_STATUS_PARTIAL,
    EFFECTIVE_STATUS_EXPIRED,
})


class UploadedFileInfo(BaseModel):
    """Metadata 1 file upload lên Supabase."""

    filename: str
    supabase_path: str
    size_bytes: int
    content_type: str
    public_url: Optional[str] = None


class DocumentMetadata(BaseModel):
    """Metadata cơ bản của văn bản pháp luật.

    Validation rules (NEW):
        - `status` chỉ chấp nhận 3 giá trị: active, partial_expired, expired
        - `date_enacted` <= hôm nay (không ở tương lai)
        - `date_effective` >= `date_enacted`
    """

    title: str
    document_type: DocumentType
    document_number: str = Field(..., description="VD: 168/2024/NĐ-CP")
    document_year: int
    status: str = Field(
        default=EFFECTIVE_STATUS_ACTIVE,
        description="active | partial_expired | expired (chỉ 3 giá trị)",
    )
    date_enacted: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_effective: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    issuing_authority: str
    source: Optional[str] = None
    version: Optional[str] = None
    # AMENDMENT only
    amends_document_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_dates_and_status(self) -> Self:
        # 1) status phải thuộc tập cho phép
        if self.status not in EFFECTIVE_STATUS_VALUES:
            raise ValueError(
                f"`status` phải là một trong: {sorted(EFFECTIVE_STATUS_VALUES)}. "
                f"Got: {self.status!r}"
            )

        # 2) Parse dates
        try:
            d_enacted = date.fromisoformat(self.date_enacted)
        except ValueError as exc:
            raise ValueError(f"`date_enacted` không hợp lệ: {exc}") from exc
        try:
            d_effective = date.fromisoformat(self.date_effective)
        except ValueError as exc:
            raise ValueError(f"`date_effective` không hợp lệ: {exc}") from exc

        # 3) date_enacted <= today
        today = date.today()
        if d_enacted > today:
            raise ValueError(
                f"`date_enacted` ({self.date_enacted}) không được nằm trong tương lai (today={today.isoformat()})."
            )

        # 4) date_effective >= date_enacted
        if d_effective < d_enacted:
            raise ValueError(
                f"`date_effective` ({self.date_effective}) không được sớm hơn `date_enacted` ({self.date_enacted})."
            )

        return self


class DocumentRecord(BaseModel):
    """Document record lưu trong Mongo `documents` collection."""

    doc_id: str
    law_id: Optional[str] = Field(
        default=None,
        description="Cloud Storage law_id (vd: D168-2024-ND-CP). Mặc định = doc_id.",
    )
    user_id: str
    document_type: DocumentType
    status: ProcessingStatus
    metadata: DocumentMetadata
    files: List[UploadedFileInfo] = []
    # Cloud paths (Phase 2+) — dạng 'cloud:{bucket}:{relative_path}'
    structured_law_path: Optional[str] = Field(
        default=None,
        description="Cloud path cho structured/law.json (vd: 'cloud:documents:D168-2024-ND-CP/structured/law.json').",
    )
    structured_relationships_path: Optional[str] = Field(
        default=None,
        description="Cloud path cho structured/relationships.json.",
    )
    # LEGACY: intermediate_json_path giữ cho backward compat với records cũ
    intermediate_json_path: Optional[str] = Field(
        default=None,
        description="LEGACY: local path. KHÔNG dùng cho records mới — dùng structured_law_path.",
    )
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    """Response từ POST /admin/documents/upload."""

    doc_id: str
    document_type: DocumentType
    status: ProcessingStatus
    files: List[UploadedFileInfo]
    message: str = "Upload thành công. Đang xử lý."


class AdminMeResponse(BaseModel):
    """Response từ GET /admin/me."""

    id: str
    email: str
    name: Optional[str] = None
    role: str


class DocumentListResponse(BaseModel):
    """Response từ GET /admin/documents."""

    documents: List[DocumentRecord]
    total: int


# ============================================================
# Phase 2 — Detail / Edit / Delete / Re-parse
# ============================================================
class ProcessingLogEntry(BaseModel):
    """Một dòng log trong pipeline."""

    stage: str
    status: str  # "started" | "success" | "error" | "warning"
    message: str
    timestamp: datetime


class DocumentDetailResponse(BaseModel):
    """Response từ GET /admin/documents/{doc_id}.

    Trả về record đầy đủ + danh sách processing logs (nếu có).
    """

    document: DocumentRecord
    logs: List[ProcessingLogEntry] = []


class MetadataUpdateRequest(BaseModel):
    """Body cho PATCH /admin/documents/{doc_id}/metadata.

    Tất cả field optional — chỉ field nào gửi lên mới update.
    """

    title: Optional[str] = None
    document_number: Optional[str] = None
    document_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    status: Optional[str] = Field(
        default=None,
        description="active | partial_expired | expired (chỉ 3 giá trị)",
    )
    date_enacted: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_effective: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    issuing_authority: Optional[str] = None
    source: Optional[str] = None
    version: Optional[str] = None
    amends_document_id: Optional[str] = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        # status phải thuộc tập cho phép (nếu gửi)
        if self.status is not None and self.status not in EFFECTIVE_STATUS_VALUES:
            raise ValueError(
                f"`status` phải là một trong: {sorted(EFFECTIVE_STATUS_VALUES)}. "
                f"Got: {self.status!r}"
            )

        # Nếu gửi cả 2 date, check effective >= enacted
        if self.date_enacted and self.date_effective:
            try:
                d_enacted = date.fromisoformat(self.date_enacted)
                d_effective = date.fromisoformat(self.date_effective)
            except ValueError as exc:
                raise ValueError(f"Ngày không hợp lệ: {exc}") from exc
            if d_effective < d_enacted:
                raise ValueError(
                    f"`date_effective` ({self.date_effective}) không được sớm hơn `date_enacted` ({self.date_enacted})."
                )

        # date_enacted không được ở tương lai
        if self.date_enacted:
            d_enacted = date.fromisoformat(self.date_enacted)
            today = date.today()
            if d_enacted > today:
                raise ValueError(
                    f"`date_enacted` ({self.date_enacted}) không được nằm trong tương lai (today={today.isoformat()})."
                )

        return self


class MetadataUpdateResponse(BaseModel):
    """Response từ PATCH metadata."""

    doc_id: str
    document: DocumentRecord
    message: str = "Metadata updated successfully"


class DeleteResponse(BaseModel):
    """Response từ DELETE document."""

    doc_id: str
    law_id: Optional[str] = None
    deleted_files_count: int = 0
    message: str = "Document deleted"


class ReparseResponse(BaseModel):
    """Response từ POST reparse."""

    doc_id: str
    status: ProcessingStatus
    message: str = (
        "Re-parse triggered. Pipeline running synchronously (Phase 2). "
        "Status will be READY on success or FAILED on error."
    )
