"""Versioning — auto snapshot structured files trước khi ghi đè.

USAGE:
    snapshot_if_exists(
        cs=CloudStorage("documents"),
        law_id="D168-2024-ND-CP",
        filenames=["law.json", "relationships.json"],
    )
    # → Snapshot v{N}-{ts}/law.json, v{N}-{ts}/relationships.json nếu file hiện tại tồn tại

    # Sau đó caller tự upload đè structured/law.json + structured/relationships.json

STRATEGY:
    - Snapshot KEYED bằng timestamp (UTC ISO8601) → tránh trùng version khi edit
      liên tiếp trong cùng 1 giây
    - Snapshot NUMBERED (v1, v2, ...) → sort/display trong admin UI
    - Snapshot CHỈ tạo khi file hiện tại tồn tại (lần đầu upload KHÔNG tạo snapshot)
    - Per-file: snapshot riêng từng file để 1 edit chỉ snapshot 1 file (tiết kiệm)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.services.cloud_storage.client import CloudStorage
from app.services.cloud_storage.exceptions import StorageNotFoundError
from app.services.cloud_storage.paths import (
    LAW_JSON_NAME,
    RELATIONSHIPS_JSON_NAME,
    list_paths_under_law,
    make_version_label,
    structured_law_path,
    structured_relationships_path,
    validate_law_id,
    version_path,
    versions_dir,
)

log = logging.getLogger("document-service.cloud_storage.versioning")


def _next_version_number(
    cs: CloudStorage,
    law_id: str,
    *,
    at: datetime,
) -> int:
    """Tính version number kế tiếp (1, 2, 3, ...) dựa trên versions/ đã tồn tại.

    Args:
        cs: CloudStorage instance
        law_id: law_id
        at: timestamp để dùng cho sorting (mặc định now)

    Returns:
        next version number N (1 nếu chưa có version nào)
    """
    try:
        existing = cs.list_prefix(versions_dir(law_id), limit=1000)
    except Exception:
        # Nếu list_prefix fail, fallback về 1 (best-effort)
        log.warning("Cannot list versions/ for %s, defaulting to v1", law_id, exc_info=True)
        return 1

    # Extract version numbers từ path dạng 'D168/versions/v3-2026.../law.json'
    # → parent folder name 'v3-2026...'
    max_n = 0
    for path in existing:
        # path = "{law_id}/versions/vN-.../filename"
        parts = path.split("/")
        if len(parts) < 4:
            continue
        version_label = parts[2]
        if not version_label.startswith("v"):
            continue
        # Extract N from "vN-..."
        try:
            n_str = version_label[1:].split("-", 1)[0]
            n = int(n_str)
            if n > max_n:
                max_n = n
        except (ValueError, IndexError):
            continue

    return max_n + 1


def snapshot_if_exists(
    *,
    cs: CloudStorage,
    law_id: str,
    filenames: list[str],
    version_label: Optional[str] = None,
    at: Optional[datetime] = None,
) -> Optional[str]:
    """Snapshot structured files vào versions/ TRƯỚC khi ghi đè.

    Args:
        cs: CloudStorage instance (bucket đã chọn)
        law_id: law_id cần snapshot
        filenames: list filenames trong structured/ cần snapshot
                  (vd ['law.json'], hoặc ['law.json', 'relationships.json'])
        version_label: dùng label cụ thể (vd 'v3-2026-09-27T13-45-00Z').
                       Nếu None → auto-generate 'v{N}-{timestamp}'
        at: timestamp cho label (default now UTC)

    Returns:
        version_label đã dùng, hoặc None nếu KHÔNG có file nào tồn tại để snapshot.

    Examples:
        >>> snapshot_if_exists(cs, "D168-2024-ND-CP", ["law.json"])
        "v1-2026-09-27T13-45-00Z"  # hoặc None nếu file chưa tồn tại
    """
    validate_law_id(law_id)
    if not filenames:
        return None

    ts = at or datetime.now(timezone.utc)

    # Tìm files thực sự tồn tại
    to_snapshot: list[str] = []
    for fname in filenames:
        # Compute current structured path
        if fname == LAW_JSON_NAME:
            current_path = structured_law_path(law_id)
        elif fname == RELATIONSHIPS_JSON_NAME:
            current_path = structured_relationships_path(law_id)
        else:
            raise ValueError(
                f"filename không hợp lệ: {fname!r}. "
                f"Chỉ chấp nhận: {LAW_JSON_NAME!r}, {RELATIONSHIPS_JSON_NAME!r}"
            )

        # Probe exists() trước khi download (tránh log error 404)
        if cs.exists(current_path):
            to_snapshot.append(fname)
        else:
            log.debug("Skip snapshot %s/%s — not found", law_id, current_path)

    if not to_snapshot:
        log.info("No existing files to snapshot for %s", law_id)
        return None

    # Generate version label nếu chưa có
    if version_label is None:
        next_n = _next_version_number(cs, law_id, at=ts)
        version_label = make_version_label(next_n, at=ts)

    # Snapshot từng file
    for fname in to_snapshot:
        if fname == LAW_JSON_NAME:
            current_path = structured_law_path(law_id)
        else:
            current_path = structured_relationships_path(law_id)

        try:
            data = cs.download_bytes(current_path)
        except StorageNotFoundError:
            log.warning("Race: %s disappeared between exists() and download", current_path)
            continue

        # Upload vào versions/
        target = version_path(law_id, version_label, fname)
        cs.upload_bytes(
            target,
            data,
            content_type="application/json; charset=utf-8",
        )
        log.info("Snapshotted %s → %s/%s", current_path, law_id, target)

    return version_label


def list_versions(cs: CloudStorage, law_id: str) -> list[dict]:
    """List tất cả versions cho 1 law_id.

    Returns:
        List of {label, files: [...], created_at}
        Sort by version number desc (mới nhất trước).
    """
    validate_law_id(law_id)
    try:
        paths = cs.list_prefix(versions_dir(law_id), limit=1000)
    except Exception:
        log.warning("Cannot list versions for %s", law_id, exc_info=True)
        return []

    # Group by version label
    by_label: dict[str, list[str]] = {}
    for p in paths:
        parts = p.split("/")
        if len(parts) < 4:
            continue
        label = parts[2]
        filename = parts[3]
        by_label.setdefault(label, []).append(filename)

    # Sort by version number desc
    def _version_num(label: str) -> int:
        try:
            return int(label.split("-", 1)[0].lstrip("v"))
        except (ValueError, IndexError):
            return 0

    out = []
    for label in sorted(by_label.keys(), key=_version_num, reverse=True):
        out.append(
            {
                "label": label,
                "files": sorted(by_label[label]),
            }
        )
    return out


__all__ = [
    "snapshot_if_exists",
    "list_versions",
]
