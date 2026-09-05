"""
Clean PDF-garbage text from legal document JSON files.

PDFs of Vietnamese legal documents often contain footer metadata that bleeds
into clause/point text when the source is extracted automatically. Patterns
to remove include:
  - "Người ký: <name>"
  - "Email: <email>"
  - "Cơ quan: <authority>"
  - "Thời gian ký: <timestamp>"
  - "CỔNG THÔNG TIN ĐIỆN TỬ ..."

This script:
  1. Walks every text field under chapters[].
  2. Removes trailing garbage after the first occurrence of these markers.
  3. Validates the cleaned JSON against schema.json (must remain valid).
  4. Writes the cleaned JSON back to the same file (with backup).

Run:
    cd tro_ly_luat
    python data_import/clean_pdf_text.py
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "doc"
SCHEMA_PATH = DOC_DIR / "schema.json"
BACKUP_DIR = DOC_DIR / ".backup_pdf_clean"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("clean-pdf")

# Regex order matters: more specific first
GARBAGE_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "gov_footer",
        re.compile(
            r"\s*Người ký\s*:[^\n]*?(?:Thời gian ký\s*:[^\n]*)?",
            re.IGNORECASE,
        ),
    ),
    ("email_only", re.compile(r"\s*Email\s*:\s*\S+@\S+", re.IGNORECASE)),
    ("agency_only", re.compile(r"\s*Cơ quan\s*:\s*VĂN PHÒNG[^\n]*", re.IGNORECASE)),
    (
        "portal_mention",
        re.compile(r"\s*CỔNG THÔNG TIN ĐIỆN TỬ[^\n]*", re.IGNORECASE),
    ),
    (
        "timestamp",
        re.compile(
            r"\s*Thời gian ký\s*:\s*\d{1,2}\.\d{1,2}\.\d{4}[^\n]*",
            re.IGNORECASE,
        ),
    ),
]


def clean_text(text: str) -> tuple[str, list[str]]:
    """Strip PDF-garbage from text. Returns (cleaned_text, applied_patterns)."""
    if not text:
        return text, []

    applied: list[str] = []
    for name, pat in GARBAGE_PATTERNS:
        new_text = pat.sub("", text)
        if new_text != text:
            applied.append(name)
            text = new_text

    # Collapse multiple spaces that may have been left behind
    text = re.sub(r" {2,}", " ", text).strip()
    # Drop trailing semicolons / commas left behind
    text = re.sub(r"[\s;,]+$", "", text)

    return text, applied


def walk_and_clean(obj: Any, parent_path: tuple = ()) -> list[str]:
    """Walk doc; clean every .text field. Returns list of cleaned paths."""
    cleaned_paths: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str):
                new_text, applied = clean_text(v)
                if applied:
                    tag = " > ".join(parent_path + (k,))
                    log.info(f"  cleaned [{','.join(applied)}] at {tag}")
                    obj[k] = new_text
                    cleaned_paths.append(tag)
            else:
                cleaned_paths.extend(walk_and_clean(v, parent_path + (k,)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            cleaned_paths.extend(walk_and_clean(v, parent_path + (str(i),)))
    return cleaned_paths


def process_file(path: Path) -> tuple[int, int]:
    """Clean one JSON file. Returns (original_size, cleaned_size)."""
    log.info(f"Processing {path.name}")
    original = path.read_text(encoding="utf-8")
    doc = json.loads(original)
    cleaned = walk_and_clean(doc)

    if not cleaned:
        log.info("  no changes needed")
        return len(original), len(original)

    # Backup
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = BACKUP_DIR / path.name
    if not backup.exists():
        shutil.copy2(path, backup)
        log.info(f"  backup -> .backup_pdf_clean/{path.name}")

    # Write back
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"  cleaned {len(cleaned)} text field(s)")
    return len(original), path.stat().st_size


def main() -> int:
    if not DOC_DIR.exists():
        log.error(f"doc/ directory not found: {DOC_DIR}")
        return 2

    json_files = sorted(p for p in DOC_DIR.glob("*.json") if p.name != "schema.json")
    if not json_files:
        log.error("No JSON files found in doc/")
        return 2

    log.info(f"Cleaning {len(json_files)} file(s)...")
    total_before = total_after = 0
    for path in json_files:
        before, after = process_file(path)
        total_before += before
        total_after += after

    saved = total_before - total_after
    log.info("=" * 60)
    log.info(f"Total: {total_before:,} -> {total_after:,} bytes ({saved:+,})")

    # Validate after cleaning
    log.info("Running validation after cleaning...")
    import subprocess
    result = subprocess.run(
        ["python", str(ROOT / "data_import" / "validate_docs.py")],
        cwd=ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())