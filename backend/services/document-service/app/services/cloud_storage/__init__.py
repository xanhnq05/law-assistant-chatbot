"""Cloud Storage package — abstraction layer cho Supabase Storage.

Public API:
    CloudStorage           — thin wrapper quanh supabase-py storage
    paths                  — path helpers (bucket_root, original_path, ...)
    exceptions             — domain errors (StorageError, StorageNotFoundError, ...)

Design:
    - Tất cả paths RELATIVE từ bucket root (vd: "D168-2024-ND-CP/structured/law.json")
    - KHÔNG bao giờ include bucket name trong path string (tránh double-prefix bugs)
    - Methods trả domain exceptions, KHÔNG leak supabase SDK exceptions
    - Idempotent: upload_path() với cùng content sẽ overwrite — caller phải tự snapshot
      qua versioning.py nếu muốn history
"""
from app.services.cloud_storage.client import CloudStorage
from app.services.cloud_storage.doc_id import (
    derives_from,
    is_amendment,
    slugify_document_id,
    slugify_from_metadata,
)
from app.services.cloud_storage.exceptions import (
    StorageBackendError,
    StorageConflictError,
    StorageError,
    StorageNotFoundError,
    StorageValidationError,
)
from app.services.cloud_storage.original_repository import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    OriginalFileRepository,
)
from app.services.cloud_storage.paths import (
    BUCKET_DOCUMENTS_DEFAULT,
    BUCKET_JSON_DEFAULT,
    LAW_JSON_NAME,
    ORIGINAL_DIR,
    RELATIONSHIPS_JSON_NAME,
    STRUCTURED_DIR,
    VERSIONS_DIR,
    bucket_root,
    list_paths_under_law,
    make_version_label,
    original_dir,
    original_path,
    parse_law_id_from_path,
    structured_dir,
    structured_law_path,
    structured_relationships_path,
    validate_filename,
    validate_law_id,
    version_path,
    versions_dir,
)
from app.services.cloud_storage.repository import (
    RELATIONSHIP_TYPES,
    DocumentRepository,
    RelationshipRecord,
)
from app.services.cloud_storage.versioning import (
    list_versions,
    snapshot_if_exists,
)

__all__ = [
    # Client
    "CloudStorage",
    # Errors
    "StorageError",
    "StorageNotFoundError",
    "StorageConflictError",
    "StorageValidationError",
    "StorageBackendError",
    # Path helpers
    "BUCKET_DOCUMENTS_DEFAULT",
    "BUCKET_JSON_DEFAULT",
    "LAW_JSON_NAME",
    "ORIGINAL_DIR",
    "RELATIONSHIPS_JSON_NAME",
    "STRUCTURED_DIR",
    "VERSIONS_DIR",
    "bucket_root",
    "list_paths_under_law",
    "make_version_label",
    "original_dir",
    "original_path",
    "parse_law_id_from_path",
    "structured_dir",
    "structured_law_path",
    "structured_relationships_path",
    "validate_filename",
    "validate_law_id",
    "version_path",
    "versions_dir",
    # doc_id helpers
    "slugify_document_id",
    "slugify_from_metadata",
    "is_amendment",
    "derives_from",
    # versioning
    "snapshot_if_exists",
    "list_versions",
    # repositories
    "DocumentRepository",
    "OriginalFileRepository",
    "RelationshipRecord",
    "RELATIONSHIP_TYPES",
    # file constants
    "ALLOWED_CONTENT_TYPES",
    "ALLOWED_EXTENSIONS",
    "MAX_FILE_SIZE_BYTES",
]
