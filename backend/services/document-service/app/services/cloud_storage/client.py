"""Cloud Storage client — wrapper quanh Supabase Storage SDK.

Public class:
    CloudStorage(bucket_name)

Operations (paths RELATIVE từ bucket root):
    upload_bytes(path, data, content_type)               — idempotent overwrite
    upload_json(path, obj, *, indent=2)                 — convenience: serialize + upload
    download_bytes(path) -> bytes                        — raise StorageNotFoundError
    download_text(path) -> str                           — convenience: bytes -> str
    download_json(path) -> dict                          — convenience: bytes -> dict
    exists(path) -> bool                                 — HEAD probe
    delete(paths) -> list[str]                           — return paths actually deleted
    list_prefix(prefix, *, recursive=True) -> list[str]  — enumerate keys

All methods raise domain exceptions từ exceptions.py, KHÔNG leak supabase SDK errors.

DESIGN NOTES:
- KHÔNG cache client — Supabase Client đã là singleton (get_supabase_client).
- Lazy connect: bucket handle lấy on-demand (`storage.from_(bucket)` không IO).
- Upload KHÔNG tự snapshot version — caller phải dùng versioning.py
  trước khi overwrite nếu cần history.
- delete() là no-op cho path không tồn tại (idempotent) — trả về list paths đã xoá thật.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Final, Iterable

from supabase import Client

from app.db.supabase_client import get_supabase_client
from app.services.cloud_storage.exceptions import (
    StorageBackendError,
    StorageNotFoundError,
    StorageValidationError,
)
from app.services.cloud_storage.paths import validate_filename

log = logging.getLogger("document-service.cloud_storage")

# Supabase storage limit per upload: 5GB for standard, but we cap conservatively.
_DEFAULT_MAX_UPLOAD_BYTES: Final = 50 * 1024 * 1024  # 50 MB


def _validate_storage_path(path: str) -> None:
    """Validate 1 storage path (full path with /) — chống path traversal.

    Rules:
        - Không rỗng
        - Không chứa '..'
        - Không bắt đầu hoặc kết thúc bằng '/'
        - Mỗi path component phải an toàn (filename validator)
    """
    if not path or not isinstance(path, str):
        raise StorageValidationError(f"path phải là string non-empty, got: {path!r}")
    if ".." in path.split("/"):
        raise StorageValidationError(f"path chứa '..': {path!r}")
    if path.startswith("/") or path.endswith("/"):
        raise StorageValidationError(f"path không được bắt đầu/kết thúc bằng '/': {path!r}")
    # Validate each component
    for component in path.split("/"):
        if component:  # skip empty (consecutive slashes)
            validate_filename(component)


class CloudStorage:
    """Thin wrapper quanh Supabase Storage bucket.

    Usage:
        cs = CloudStorage("documents")
        cs.upload_bytes("D168-2024-ND-CP/original/law.pdf", pdf_bytes, "application/pdf")
        raw = cs.download_bytes("D168-2024-ND-CP/structured/law.json")
    """

    def __init__(self, bucket: str) -> None:
        if not bucket or not isinstance(bucket, str):
            raise StorageValidationError(f"bucket phải là string non-empty, got: {bucket!r}")
        self._bucket = bucket

    # ------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------
    @property
    def bucket(self) -> str:
        return self._bucket

    def _client(self) -> Client:
        """Lazy fetch of Supabase client (singleton)."""
        return get_supabase_client().client

    def _bucket_handle(self):
        """Storage bucket handle (no IO)."""
        return self._client().storage.from_(self._bucket)

    # ------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------
    def upload_bytes(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        max_bytes: int = _DEFAULT_MAX_UPLOAD_BYTES,
    ) -> str:
        """Upload bytes lên path (relative bucket root). Idempotent overwrite.

        Args:
            path: relative path trong bucket (vd: 'D168-2024-ND-CP/original/law.pdf')
            data: bytes để upload
            content_type: MIME type
            max_bytes: cap size (mặc định 50MB); raise ValidationError nếu vượt

        Returns:
            path (echo lại để chain)

        Raises:
            StorageValidationError: path invalid / size vượt cap
            StorageBackendError: Supabase SDK / network thất bại
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise StorageValidationError(
                f"data phải là bytes/bytearray/memoryview, got: {type(data).__name__}"
            )
        if len(data) == 0:
            raise StorageValidationError(f"data rỗng cho path: {path!r}")
        if len(data) > max_bytes:
            raise StorageValidationError(
                f"data vượt max_bytes={max_bytes} (got {len(data)}) cho path: {path!r}"
            )
        if not content_type:
            raise StorageValidationError("content_type không được rỗng")

        # Validate path safety (chống path traversal)
        _validate_storage_path(path)

        try:
            # Try upload (upsert=True to overwrite if exists)
            self._bucket_handle().upload(
                path=path,
                file=bytes(data),
                file_options={"content-type": content_type, "upsert": "true"},
            )
            log.info("Uploaded %d bytes → %s/%s", len(data), self._bucket, path)
            return path
        except Exception as exc:
            # supabase SDK raise StorageApiError hoặc Exception generic.
            # Gọi log với full traceback cho debug, raise domain error.
            log.exception("Supabase upload failed: %s/%s", self._bucket, path)
            raise StorageBackendError(
                f"Upload failed for {path!r} in bucket {self._bucket!r}: {exc}",
                context={"path": path, "bucket": self._bucket, "size": len(data)},
            ) from exc

    def upload_json(
        self,
        path: str,
        obj: Any,
        *,
        content_type: str = "application/json; charset=utf-8",
        indent: int | None = 2,
        ensure_ascii: bool = False,
    ) -> str:
        """Convenience: serialize obj → JSON → upload.

        Args:
            path: relative path (vd: 'D168-2024-ND-CP/structured/law.json')
            obj: JSON-serializable object
            indent: None = compact JSON; 2 = pretty (default 2)
            ensure_ascii: False = giữ UTF-8 (Tiếng Việt); True = escape ASCII

        Returns:
            path
        """
        try:
            payload = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent, sort_keys=False)
        except (TypeError, ValueError) as exc:
            raise StorageValidationError(
                f"Object không serializable thành JSON: {exc}",
                context={"path": path},
            ) from exc

        data = payload.encode("utf-8")
        return self.upload_bytes(path, data, content_type=content_type)

    # ------------------------------------------------------------
    # Download
    # ------------------------------------------------------------
    def download_bytes(self, path: str) -> bytes:
        """Download bytes từ path.

        Raises:
            StorageNotFoundError: path không tồn tại
            StorageBackendError: network / SDK error
        """
        _validate_storage_path(path)
        try:
            data = self._bucket_handle().download(path)
            # supabase-py v2 trả về bytes trực tiếp
            if isinstance(data, str):
                data = data.encode("utf-8")
            return bytes(data)
        except Exception as exc:
            # Distinguish "not found" vs "real error".
            # supabase SDK raise StorageApiError với status_code; check best-effort.
            status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
            if status == 404 or "not found" in str(exc).lower() or "404" in str(exc):
                raise StorageNotFoundError(
                    path, context={"bucket": self._bucket}
                ) from exc
            log.exception("Supabase download failed: %s/%s", self._bucket, path)
            raise StorageBackendError(
                f"Download failed for {path!r} in bucket {self._bucket!r}: {exc}",
                context={"path": path, "bucket": self._bucket},
            ) from exc

    def download_text(self, path: str, *, encoding: str = "utf-8") -> str:
        """Convenience: download → decode text."""
        return self.download_bytes(path).decode(encoding)

    def download_json(self, path: str) -> Any:
        """Convenience: download → parse JSON."""
        text = self.download_text(path)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise StorageValidationError(
                f"File {path!r} không phải JSON hợp lệ: {exc}",
                context={"path": path, "bucket": self._bucket},
            ) from exc

    # ------------------------------------------------------------
    # Probe
    # ------------------------------------------------------------
    def exists(self, path: str) -> bool:
        """Check path có tồn tại không (best-effort qua list-by-prefix).

        NOTE: Supabase Storage KHÔNG có HEAD operation cho public client.
        Ta dùng list-by-prefix và check exact match. Trade-off: 1 extra API call
        nhưng chính xác. Cho paths không tồn tại, list trả empty list.
        """
        _validate_storage_path(path)
        try:
            # list by exact prefix (folder containing path)
            folder = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
            items = self._bucket_handle().list(path=folder, options={"limit": 1000})
            for item in items:
                name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                if name == path:
                    return True
            return False
        except Exception:
            # exists() là best-effort — KHÔNG raise để caller có thể fallback gracefully
            log.warning("exists() probe failed for %s/%s", self._bucket, path, exc_info=True)
            return False

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    def delete(self, paths: str | Iterable[str]) -> list[str]:
        """Xoá 1 hoặc nhiều paths. Idempotent — paths không tồn tại bị skip silently.

        Args:
            paths: string hoặc iterable of strings

        Returns:
            List các paths đã xoá thật (có thể empty nếu không có gì tồn tại)
        """
        if isinstance(paths, str):
            paths = [paths]
        path_list = list(paths)
        for p in path_list:
            _validate_storage_path(p)
        if not path_list:
            return []

        try:
            self._bucket_handle().remove(path_list)
            log.info("Deleted %d paths from %s: %s", len(path_list), self._bucket, path_list)
            return path_list
        except Exception as exc:
            # Supabase raise nếu có path không tồn tại; log + retry-by-one để be idempotent
            log.warning(
                "Bulk delete failed (%s), retrying one-by-one: %s", exc, path_list
            )
            deleted: list[str] = []
            for p in path_list:
                try:
                    self._bucket_handle().remove([p])
                    deleted.append(p)
                except Exception as inner_exc:
                    # Skip 404, raise cho error khác
                    status = getattr(inner_exc, "status", None) or getattr(
                        inner_exc, "status_code", None
                    )
                    if status == 404 or "not found" in str(inner_exc).lower():
                        continue
                    log.exception("Failed to delete %s: %s", p, inner_exc)
                    raise StorageBackendError(
                        f"Delete failed for {p!r}: {inner_exc}",
                        context={"path": p, "bucket": self._bucket},
                    ) from inner_exc
            return deleted

    # ------------------------------------------------------------
    # List
    # ------------------------------------------------------------
    def list_prefix(self, prefix: str, *, limit: int = 1000) -> list[str]:
        """List tất cả paths bắt đầu bằng prefix.

        Args:
            prefix: vd 'D168-2024-ND-CP/' hoặc 'D168-2024-ND-CP/original/'
            limit: max items returned

        Returns:
            List các full paths (relative bucket root)
        """
        if not prefix:
            raise StorageValidationError("prefix không được rỗng")
        # Basic safety: không cho path traversal
        if ".." in prefix.split("/"):
            raise StorageValidationError(f"prefix chứa '..': {prefix!r}")

        try:
            options = {"limit": limit} if limit else {}
            items = self._bucket_handle().list(path=prefix, options=options if options else None)
            out: list[str] = []
            for item in items:
                name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
                if name:
                    out.append(name)
            return out
        except Exception as exc:
            log.exception("Supabase list failed for prefix %s/%s", self._bucket, prefix)
            raise StorageBackendError(
                f"List failed for prefix {prefix!r}: {exc}",
                context={"prefix": prefix, "bucket": self._bucket},
            ) from exc
