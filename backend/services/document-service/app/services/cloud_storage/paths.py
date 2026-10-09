"""Path helpers cho Cloud Storage layout.

LAYOUT (per-doc, in+out relationships):
    {bucket}/
    └── {law_id}/                         # vd: D168-2024-ND-CP
        ├── original/
        │   └── {filename}                # PDF/DOCX gốc
        │
        ├── structured/
        │   ├── law.json                  # JSON chuẩn hoá từ parser
        │   └── relationships.json        # Quan hệ in+out của văn bản này
        │
        └── versions/
            └── v{n}-{ISO8601}/
                ├── law.json
                └── relationships.json

EXAMPLES:
    law_id = "D168-2024-ND-CP"
    bucket = "documents"
        → bucket_root("documents", "D168-2024-ND-CP")                = "D168-2024-ND-CP/"
        → original_path("documents", "D168-2024-ND-CP", "law.pdf")   = "D168-2024-ND-CP/original/law.pdf"
        → structured_law_path("documents", "D168-2024-ND-CP")       = "D168-2024-ND-CP/structured/law.json"
        → structured_relationships_path("documents", "D168-2024-ND-CP") = "D168-2024-ND-CP/structured/relationships.json"

ALL paths are RELATIVE to bucket root — không bao gồm tên bucket.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Final

from app.services.cloud_storage.exceptions import StorageValidationError

# ============================================================
# Constants
# ============================================================
ORIGINAL_DIR: Final = "original"
STRUCTURED_DIR: Final = "structured"
VERSIONS_DIR: Final = "versions"

LAW_JSON_NAME: Final = "law.json"
RELATIONSHIPS_JSON_NAME: Final = "relationships.json"

# ============================================================
# Law ID validation
# ============================================================
# Allow format: {prefix}{number}-{year}-{type}
#   vd: D168-2024-ND-CP, L36-2024-QH15, PL1-2020-UBTVQH
_LAW_ID_PATTERN = re.compile(r"^[A-Z]{1,3}\d+[A-Z]?\d*-\d{4}-[A-Z0-9-]+$")
# Fallback cho legacy / stub: D168-2024 (chỉ number + year)
_LAW_ID_LEGACY = re.compile(r"^[A-Z]{1,3}\d+[A-Z]?\d*-\d{4}$")

# ============================================================
# Validators
# ============================================================
def validate_law_id(law_id: str) -> None:
    """Validate law_id format. Raise StorageValidationError nếu sai.

    Chấp nhận:
        - D168-2024-ND-CP   (full)
        - D168-2024        (legacy / stub)
    """
    if not law_id or not isinstance(law_id, str):
        raise StorageValidationError(f"law_id phải là string non-empty, got: {law_id!r}")

    if _LAW_ID_PATTERN.match(law_id) or _LAW_ID_LEGACY.match(law_id):
        return

    raise StorageValidationError(
        f"law_id không hợp lệ: {law_id!r}. "
        "Format: {prefix}{number}-{year}-{type} (vd: D168-2024-ND-CP) hoặc legacy D168-2024"
    )


def validate_filename(filename: str) -> None:
    """Validate filename cho path safety.

    Reject:
        - empty
        - path separators (/, \\)
        - leading/trailing dots
        - control characters
    """
    if not filename or not isinstance(filename, str):
        raise StorageValidationError(f"filename phải là string non-empty, got: {filename!r}")

    if "/" in filename or "\\" in filename:
        raise StorageValidationError(
            f"filename không được chứa path separator: {filename!r}"
        )

    if filename.startswith(".") or filename.endswith("."):
        raise StorageValidationError(
            f"filename không được bắt đầu/kết thúc bằng dấu chấm: {filename!r}"
        )

    if any(ord(c) < 32 for c in filename):
        raise StorageValidationError(
            f"filename chứa control characters: {filename!r}"
        )


# ============================================================
# Path builders — tất cả relative từ bucket root
# ============================================================
def bucket_root(law_id: str) -> str:
    """Root folder của 1 law trong bucket: '{law_id}/'"""
    validate_law_id(law_id)
    return f"{law_id}/"


def original_dir(law_id: str) -> str:
    """Folder chứa file gốc: '{law_id}/original/'"""
    validate_law_id(law_id)
    return f"{law_id}/{ORIGINAL_DIR}/"


def original_path(law_id: str, filename: str) -> str:
    """Full path cho file gốc: '{law_id}/original/{filename}'"""
    validate_law_id(law_id)
    validate_filename(filename)
    return f"{law_id}/{ORIGINAL_DIR}/{filename}"


def structured_dir(law_id: str) -> str:
    """Folder chứa JSON đã parse: '{law_id}/structured/'"""
    validate_law_id(law_id)
    return f"{law_id}/{STRUCTURED_DIR}/"


def structured_law_path(law_id: str) -> str:
    """Path cho file law.json: '{law_id}/structured/law.json'"""
    validate_law_id(law_id)
    return f"{law_id}/{STRUCTURED_DIR}/{LAW_JSON_NAME}"


def structured_relationships_path(law_id: str) -> str:
    """Path cho file relationships.json: '{law_id}/structured/relationships.json'"""
    validate_law_id(law_id)
    return f"{law_id}/{STRUCTURED_DIR}/{RELATIONSHIPS_JSON_NAME}"


def versions_dir(law_id: str) -> str:
    """Folder chứa version snapshots: '{law_id}/versions/'"""
    validate_law_id(law_id)
    return f"{law_id}/{VERSIONS_DIR}/"


def version_path(law_id: str, version_label: str, filename: str) -> str:
    """Path cho 1 version snapshot.

    Args:
        version_label: vd 'v1-2026-09-27T13:45:00Z'
        filename: 'law.json' hoặc 'relationships.json'

    Returns: '{law_id}/versions/{version_label}/{filename}'
    """
    validate_law_id(law_id)
    if not version_label or "/" in version_label or "\\" in version_label:
        raise StorageValidationError(f"version_label không hợp lệ: {version_label!r}")
    validate_filename(filename)
    return f"{law_id}/{VERSIONS_DIR}/{version_label}/{filename}"


def make_version_label(n: int, *, at: datetime | None = None) -> str:
    """Build version label dạng 'v{N}-{ISO8601}'.

    Args:
        n: version number (1, 2, 3, ...)
        at: timestamp (default now UTC)
    """
    if n < 1:
        raise StorageValidationError(f"version number phải >= 1, got {n}")
    ts = (at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"v{n}-{ts}"


# ============================================================
# Path parsers — cho delete / list operations
# ============================================================
def parse_law_id_from_path(path: str) -> str | None:
    """Extract law_id từ 1 path. Trả None nếu path không thuộc layout này.

    VD: 'D168-2024-ND-CP/structured/law.json' → 'D168-2024-ND-CP'
        'D168-2024-ND-CP/original/law.pdf'      → 'D168-2024-ND-CP'
        'random/file.txt'                        → None
    """
    if not path:
        return None
    parts = path.split("/", 1)
    if len(parts) < 1:
        return None
    head = parts[0]
    try:
        validate_law_id(head)
        return head
    except StorageValidationError:
        return None


def list_paths_under_law(law_id: str) -> list[str]:
    """Trả list các 'standard' paths của 1 law (original root + structured root + versions root).

    NOTE: KHÔNG đệ quy — dùng để enumerate 'folders' khi list Supabase Storage.
    Supabase Storage không có folder concept, dùng prefix match.
    """
    validate_law_id(law_id)
    return [
        original_dir(law_id).rstrip("/"),
        structured_dir(law_id).rstrip("/"),
        versions_dir(law_id).rstrip("/"),
    ]


# ============================================================
# Preset bucket names (cho consistency với config)
# ============================================================
BUCKET_DOCUMENTS_DEFAULT: Final = "documents"
BUCKET_JSON_DEFAULT: Final = "json"

# NOTE: Project hiện dùng 1 bucket 'documents' cho cả PDF/DOCX + JSON.
# BUCKET_JSON_DEFAULT giữ để tương thích nếu sau này tách.
