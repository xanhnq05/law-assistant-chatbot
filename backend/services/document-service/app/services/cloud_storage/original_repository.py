"""OriginalFileRepository — quản lý PDF/DOCX gốc trên Cloud Storage.

Layer tách biệt DocumentRepository (chỉ lo structured JSON):
    - Upload PDF/DOCX
    - List files của 1 law
    - Delete files (khi delete_document)
    - Get download URL

PATH LAYOUT:
    {law_id}/original/{filename}
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.services.cloud_storage.client import CloudStorage
from app.services.cloud_storage.exceptions import StorageNotFoundError, StorageValidationError
from app.services.cloud_storage.paths import (
    original_dir,
    original_path,
    validate_filename,
    validate_law_id,
)

log = logging.getLogger("document-service.cloud_storage.original_repo")

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    "application/msword",  # DOC
    "application/CDFV2",
    "application/x-msword",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class OriginalFileRepository:
    """Repository cho file PDF/DOCX gốc của văn bản pháp luật."""

    def __init__(self, cs: CloudStorage) -> None:
        self._cs = cs

    # ------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------
    def upload_original(
        self,
        law_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Upload 1 PDF/DOCX file.

        Args:
            law_id
            filename: original filename (sẽ được ASCII-sanitize cho path)
            content: bytes
            content_type: MIME

        Returns:
            {supabase_path, safe_filename, size_bytes, content_type}

        Raises:
            StorageValidationError: extension/content không hợp lệ, size vượt cap
            StorageBackendError: upload fail
        """
        validate_law_id(law_id)
        validate_filename(filename)

        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise StorageValidationError(
                f"Chỉ chấp nhận extension {sorted(ALLOWED_EXTENSIONS)}, got: {ext}"
            )
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            log.warning("Suspicious content_type=%s for filename=%s", content_type, filename)

        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise StorageValidationError(f"content phải là bytes, got: {type(content).__name__}")
        size = len(content)
        if size == 0:
            raise StorageValidationError(f"File {filename!r} rỗng")
        if size > MAX_FILE_SIZE_BYTES:
            raise StorageValidationError(
                f"File {filename!r} vượt quá {MAX_FILE_SIZE_BYTES // (1024*1024)} MB"
            )

        safe_name = self._safe_filename(filename)
        path = original_path(law_id, safe_name)
        self._cs.upload_bytes(path, content, content_type=content_type or "application/octet-stream")

        return {
            "supabase_path": path,
            "safe_filename": safe_name,
            "size_bytes": size,
            "content_type": content_type or "application/octet-stream",
        }

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    def download(self, law_id: str, filename: str) -> bytes:
        """Download 1 file PDF/DOCX."""
        validate_law_id(law_id)
        return self._cs.download_bytes(original_path(law_id, filename))

    def get_public_url(self, law_id: str, filename: str) -> Optional[str]:
        """Get public URL (nếu bucket là public). Trả None nếu bucket private."""
        validate_law_id(law_id)
        path = original_path(law_id, filename)
        try:
            return self._cs._bucket_handle().get_public_url(path)
        except Exception:
            return None

    def list_originals(self, law_id: str) -> list[str]:
        """List filenames trong original/ của law_id.

        Returns:
            List các filename (relative original/).
            VD: ['law.pdf', 'law.docx']
        """
        validate_law_id(law_id)
        prefix = original_dir(law_id)
        try:
            paths = self._cs.list_prefix(prefix, limit=1000)
        except Exception:
            log.warning("list_prefix failed for %s", prefix, exc_info=True)
            return []

        # Strip prefix để chỉ trả filename
        filenames = []
        for p in paths:
            if p.startswith(prefix):
                filenames.append(p[len(prefix):])
            else:
                filenames.append(p)
        return filenames

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    def delete_original(self, law_id: str, filename: str) -> bool:
        """Xoá 1 file PDF/DOCX. Returns True nếu xoá được."""
        validate_law_id(law_id)
        validate_filename(filename)
        path = original_path(law_id, filename)
        deleted = self._cs.delete(path)
        return path in deleted

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    @staticmethod
    def _safe_filename(filename: str) -> str:
        """ASCII-safe filename cho Supabase path (giữ extension)."""
        # Tách extension
        if "." in filename:
            base, ext = filename.rsplit(".", 1)
            ext = "." + ext
        else:
            base, ext = filename, ""

        safe_base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_")
        if not safe_base:
            safe_base = "unnamed"
        return safe_base + ext
