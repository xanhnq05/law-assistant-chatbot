"""DocumentRepository — Cloud Storage repository cho document + relationships.

Responsibility:
    - Đọc/ghi structured JSON lên Cloud Storage (qua CloudStorage)
    - Quản lý relationships in+out cho 1 law
    - Auto-versioning khi update
    - KHÔNG quản lý Mongo (xem mongo_repository.py)
    - KHÔNG quản lý files PDF/DOCX gốc (xem original_file_repository.py)

USAGE:
    repo = DocumentRepository(CloudStorage("documents"))
    law = repo.load_law("D168-2024-ND-CP")
    rels = repo.load_relationships("D168-2024-ND-CP")
    repo.save_law("D168-2024-ND-CP", parsed_dict, snapshot=True)
    repo.delete_law_folder("D168-2024-ND-CP")  # cascade
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.cloud_storage.client import CloudStorage
from app.services.cloud_storage.exceptions import StorageNotFoundError
from app.services.cloud_storage.paths import (
    LAW_JSON_NAME,
    RELATIONSHIPS_JSON_NAME,
    list_paths_under_law,
    original_dir,
    structured_law_path,
    structured_relationships_path,
    validate_law_id,
    versions_dir,
)
from app.services.cloud_storage.versioning import (
    list_versions,
    snapshot_if_exists,
)

log = logging.getLogger("document-service.cloud_storage.repo")


# ============================================================
# Schema contracts
# ============================================================
class RelationshipRecord(dict):
    """1 relationship row.

    Schema:
        {
          "source": {"document_id": "...", "article_id": "...", "clause_id": "...", "point_id": "..."},
          "target": {"document_id": "...", "article_id": "...", "clause_id": "...", "point_id": "..."},
          "type": "AMENDS" | "ADDS" | "REPLACES" | "REPEALS",
          "description": "...",
          "confidence": 0.0-1.0,
          "detected_at": "2026-09-27T13:45:00Z"
        }
    """
    pass


RELATIONSHIP_TYPES = {"AMENDS", "ADDS", "REPLACES", "REPEALS"}


# ============================================================
# Repository
# ============================================================
class DocumentRepository:
    """CRUD operations cho 1 law trên Cloud Storage.

    Quản lý:
        - structured/law.json
        - structured/relationships.json
    KHÔNG quản lý:
        - original/*  (PDF/DOCX gốc — dùng OriginalFileRepository)
        - versions/*  (auto-handled bởi snapshot_if_exists)
    """

    def __init__(self, cs: CloudStorage) -> None:
        self._cs = cs

    # ------------------------------------------------------------
    # law.json
    # ------------------------------------------------------------
    def load_law(self, law_id: str) -> dict[str, Any]:
        """Load structured/law.json. Raise StorageNotFoundError nếu không có."""
        validate_law_id(law_id)
        return self._cs.download_json(structured_law_path(law_id))

    def law_exists(self, law_id: str) -> bool:
        validate_law_id(law_id)
        return self._cs.exists(structured_law_path(law_id))

    def save_law(
        self,
        law_id: str,
        law_dict: dict[str, Any],
        *,
        snapshot: bool = True,
    ) -> str:
        """Save structured/law.json. Auto-snapshot version cũ nếu tồn tại.

        Args:
            law_id
            law_dict: JSON-serializable dict
            snapshot: True = snapshot phiên bản hiện tại trước khi ghi đè (default)

        Returns:
            version_label vừa snapshot, hoặc "" nếu snapshot=False hoặc không có gì để snapshot.
        """
        validate_law_id(law_id)
        version_label = ""
        if snapshot:
            version_label = snapshot_if_exists(
                cs=self._cs,
                law_id=law_id,
                filenames=[LAW_JSON_NAME],
            ) or ""

        self._cs.upload_json(
            structured_law_path(law_id),
            law_dict,
            content_type="application/json; charset=utf-8",
        )
        log.info("Saved law.json for %s (snapshot=%s)", law_id, version_label or "none")
        return version_label

    # ------------------------------------------------------------
    # relationships.json
    # ------------------------------------------------------------
    def load_relationships(self, law_id: str) -> dict[str, Any]:
        """Load structured/relationships.json.

        Returns:
            Dict dạng:
                {
                  "law_id": "D168-2024-ND-CP",
                  "updated_at": "2026-09-27T13:45:00Z",
                  "incoming":  [...],  # relationships mà văn bản khác trỏ vào law_id này
                  "outgoing":  [...]   # relationships mà law_id này trỏ đi văn bản khác
                }

            Nếu file không tồn tại → trả default empty (KHÔNG raise).
        """
        validate_law_id(law_id)
        try:
            return self._cs.download_json(structured_relationships_path(law_id))
        except StorageNotFoundError:
            log.debug("relationships.json not found for %s — returning empty", law_id)
            return self._empty_relationships(law_id)

    def relationships_exist(self, law_id: str) -> bool:
        validate_law_id(law_id)
        return self._cs.exists(structured_relationships_path(law_id))

    def save_relationships(
        self,
        law_id: str,
        relationships_doc: dict[str, Any],
        *,
        snapshot: bool = True,
    ) -> str:
        """Save structured/relationships.json. Auto-snapshot nếu tồn tại.

        Caller chịu trách nhiệm về format (incoming/outgoing arrays).
        Hàm này sẽ:
            1. Validate incoming/outgoing arrays
            2. Inject updated_at
            3. Snapshot (nếu snapshot=True)
            4. Upload
        """
        validate_law_id(law_id)
        # Validate structure
        if not isinstance(relationships_doc, dict):
            raise ValueError("relationships_doc phải là dict")
        for key in ("incoming", "outgoing"):
            if key not in relationships_doc:
                relationships_doc[key] = []
            elif not isinstance(relationships_doc[key], list):
                raise ValueError(f"relationships_doc.{key} phải là list")
        # Inject metadata
        relationships_doc["law_id"] = law_id
        relationships_doc["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Snapshot
        version_label = ""
        if snapshot:
            version_label = snapshot_if_exists(
                cs=self._cs,
                law_id=law_id,
                filenames=[RELATIONSHIPS_JSON_NAME],
            ) or ""

        self._cs.upload_json(
            structured_relationships_path(law_id),
            relationships_doc,
            content_type="application/json; charset=utf-8",
        )
        log.info("Saved relationships.json for %s (snapshot=%s)", law_id, version_label or "none")
        return version_label

    def upsert_relationship(
        self,
        law_id: str,
        *,
        direction: str,  # "incoming" | "outgoing"
        relationship: RelationshipRecord,
    ) -> None:
        """Add or update 1 relationship entry (matched by source/target/type).

        NOTE: KHÔNG snapshot (đây là granular update, không phải full overwrite).
        Nếu caller muốn snapshot mỗi lần upsert → gọi save_relationships(...) thay thế.
        """
        if direction not in ("incoming", "outgoing"):
            raise ValueError(f"direction phải là 'incoming' hoặc 'outgoing', got: {direction!r}")
        self._validate_relationship(relationship)

        doc = self.load_relationships(law_id)
        target_list = doc[direction]

        # Dedup: existing có cùng (source, target, type) → replace
        existing_idx = None
        for i, existing in enumerate(target_list):
            if (
                existing.get("source") == relationship.get("source")
                and existing.get("target") == relationship.get("target")
                and existing.get("type") == relationship.get("type")
            ):
                existing_idx = i
                break

        if existing_idx is not None:
            target_list[existing_idx] = dict(relationship)
        else:
            target_list.append(dict(relationship))

        self.save_relationships(law_id, doc, snapshot=False)

    def remove_relationship(
        self,
        law_id: str,
        *,
        direction: str,
        source_doc: str,
        target_doc: str,
        rel_type: str,
    ) -> bool:
        """Remove 1 relationship entry. Returns True nếu xoá được, False nếu không tìm thấy."""
        if direction not in ("incoming", "outgoing"):
            raise ValueError(f"direction phải là 'incoming' hoặc 'outgoing', got: {direction!r}")
        doc = self.load_relationships(law_id)
        target_list = doc.get(direction, [])

        before = len(target_list)
        doc[direction] = [
            r for r in target_list
            if not (
                r.get("source", {}).get("document_id") == source_doc
                and r.get("target", {}).get("document_id") == target_doc
                and r.get("type") == rel_type
            )
        ]
        if len(doc[direction]) == before:
            return False

        self.save_relationships(law_id, doc, snapshot=False)
        return True

    def merge_relationships_for_law(
        self,
        law_id: str,
        *,
        outgoing: Optional[list[RelationshipRecord]] = None,
    ) -> None:
        """Merge outgoing relationships cho law_id (caller đã detect từ amendment body).

        Side effects:
            - Append incoming entries vào relationships.json của target docs
              (vì relationship 2 chiều — 'outgoing' của A là 'incoming' của B)
            - Append outgoing entries vào relationships.json của law_id
        """
        validate_law_id(law_id)
        outgoing_rels = outgoing or []
        for r in outgoing_rels:
            self._validate_relationship(r)

        # Update outgoing for self
        if outgoing_rels:
            doc = self.load_relationships(law_id)
            doc["outgoing"].extend([dict(r) for r in outgoing_rels])
            self.save_relationships(law_id, doc, snapshot=False)

        # Propagate to target docs (as incoming)
        target_docs = set()
        for r in outgoing_rels:
            target = r.get("target", {})
            target_law = target.get("document_id")
            if target_law and target_law != law_id:
                target_docs.add(target_law)

        for target_law in target_docs:
            # Build mirrored relationship (swap source/target)
            mirrored = []
            for r in outgoing_rels:
                if r.get("target", {}).get("document_id") == target_law:
                    swapped = {
                        "source": r.get("target"),
                        "target": r.get("source"),
                        "type": r.get("type"),
                        "description": r.get("description"),
                        "confidence": r.get("confidence"),
                        "detected_at": r.get("detected_at"),
                    }
                    mirrored.append(swapped)
            if mirrored:
                doc = self.load_relationships(target_law)
                # Append incoming (dedup by source/target/type)
                existing_keys = {
                    (
                        r.get("source", {}).get("document_id"),
                        r.get("target", {}).get("document_id"),
                        r.get("type"),
                    )
                    for r in doc.get("incoming", [])
                }
                for m in mirrored:
                    key = (
                        m["source"].get("document_id"),
                        m["target"].get("document_id"),
                        m["type"],
                    )
                    if key not in existing_keys:
                        doc["incoming"].append(m)
                self.save_relationships(target_law, doc, snapshot=False)

    # ------------------------------------------------------------
    # Cascade delete
    # ------------------------------------------------------------
    def delete_law_folder(self, law_id: str) -> dict[str, int]:
        """Xoá TOÀN BỘ folder {law_id}/ trên Cloud Storage.

        Bao gồm:
            - original/* (PDF/DOCX gốc)
            - structured/* (law.json, relationships.json)
            - versions/* (history)

        Returns:
            Dict {'deleted': int, 'prefixes': int} — số paths đã xoá.
        """
        validate_law_id(law_id)
        deleted_total = 0
        deleted_paths: list[str] = []

        # List all 3 root prefixes rồi xoá
        for prefix in list_paths_under_law(law_id):
            try:
                paths = self._cs.list_prefix(prefix, limit=1000)
            except Exception:
                log.warning("list_prefix failed for %s", prefix, exc_info=True)
                continue
            for p in paths:
                try:
                    self._cs.delete(p)
                    deleted_paths.append(p)
                    deleted_total += 1
                except Exception:
                    log.warning("delete failed for %s", p, exc_info=True)

        log.info("Cascade delete %s/: %d files deleted", law_id, deleted_total)
        return {"deleted": deleted_total, "paths": deleted_paths}

    # ------------------------------------------------------------
    # List / versions
    # ------------------------------------------------------------
    def list_versions(self, law_id: str) -> list[dict]:
        """Proxy tới versioning.list_versions."""
        return list_versions(self._cs, law_id)

    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    @staticmethod
    def _empty_relationships(law_id: str) -> dict[str, Any]:
        return {
            "law_id": law_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "incoming": [],
            "outgoing": [],
        }

    @staticmethod
    def _validate_relationship(r: Any) -> None:
        if not isinstance(r, dict):
            raise ValueError("relationship phải là dict")
        if r.get("type") not in RELATIONSHIP_TYPES:
            raise ValueError(f"relationship.type phải là 1 trong {RELATIONSHIP_TYPES}, got: {r.get('type')!r}")
        for endpoint in ("source", "target"):
            if endpoint not in r:
                raise ValueError(f"relationship.{endpoint} là required")
            ep = r[endpoint]
            if not isinstance(ep, dict):
                raise ValueError(f"relationship.{endpoint} phải là dict")
            if not ep.get("document_id"):
                raise ValueError(f"relationship.{endpoint}.document_id là required")
