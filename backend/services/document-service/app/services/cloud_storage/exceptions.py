"""Custom exceptions cho Cloud Storage layer.

Mục đích:
- Tách biệt error types để caller xử lý đúng (retry vs propagate vs 4xx).
- Tương thích với FastAPI HTTPException cho routes.
- KHÔNG leak Supabase SDK exceptions ra ngoài (gói lại thành domain errors).

Ladder:
    StorageError (base)
    ├── StorageNotFoundError    (404 — file không tồn tại)
    ├── StorageConflictError    (409 — version mismatch / idempotency violation)
    ├── StorageValidationError  (400 — invalid path / payload)
    └── StorageBackendError     (5xx — Supabase SDK / network thất bại)
"""
from __future__ import annotations

from typing import Any, Optional


class StorageError(Exception):
    """Base exception cho Cloud Storage layer."""

    def __init__(self, message: str, *, context: Optional[dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}


class StorageNotFoundError(StorageError):
    """File/folder không tồn tại trên Cloud Storage."""

    def __init__(self, path: str, *, context: Optional[dict[str, Any]] = None) -> None:
        super().__init__(f"Storage path not found: {path}", context=context)
        self.path = path


class StorageConflictError(StorageError):
    """Conflict (idempotency, version mismatch, etc.)."""


class StorageValidationError(StorageError):
    """Input không hợp lệ (path, payload size, format)."""


class StorageBackendError(StorageError):
    """Supabase SDK hoặc network thất bại — caller nên retry."""
