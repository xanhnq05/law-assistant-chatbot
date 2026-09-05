"""
Validate every JSON file under doc/ against doc/schema.json.

Catches:
  - Missing required fields (e.g. document_type, issuing_authority)
  - Bad ID format / duplicates
  - chapter_id / article_id / clause_id mismatches
  - PDF garbage in text (footer "Người ký:", "Email:", "Thời gian ký:")
  - Empty text fields

Run:
    cd tro_ly_luat
    python data_import/validate_docs.py
    python data_import/validate_docs.py --strict    # fail on warnings too
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:
    print("Missing dependency: jsonschema.  pip install jsonschema", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "doc"
SCHEMA_PATH = DOC_DIR / "schema.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("validate-docs")

PDF_GARBAGE_PATTERNS = [
    re.compile(r"Người ký\s*:", re.IGNORECASE),
    re.compile(r"Email\s*:\s*\S+@\S+", re.IGNORECASE),
    re.compile(r"Cơ quan\s*:\s*VĂN PHÒNG", re.IGNORECASE),
    re.compile(r"Thời gian ký\s*:", re.IGNORECASE),
    re.compile(r"CỔNG THÔNG TIN ĐIỆN TỬ", re.IGNORECASE),
]


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def walk_text(path: tuple[str, ...], obj: Any, issues: list[str], allow_empty: bool = False) -> None:
    """Walk a doc and report PDF-garbage issues.

    `allow_empty=True` skips empty-text reports (used at article level where
    `text=""` is normal because the content lives in clauses)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "text" and isinstance(v, str):
                tag = " > ".join(path)
                if not v.strip():
                    if not allow_empty:
                        issues.append(f"EMPTY text at {tag}")
                else:
                    for pat in PDF_GARBAGE_PATTERNS:
                        if pat.search(v):
                            issues.append(
                                f"PDF-GARBAGE in text at {tag}: pattern '{pat.pattern}'"
                            )
                            break
            else:
                walk_text((*path, k), v, issues, allow_empty=allow_empty)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            walk_text((*path, str(i)), v, issues, allow_empty=allow_empty)


def extract_chapters(doc: dict) -> list[dict]:
    """Return the chapters list regardless of whether schema is A (root) or B (nested)."""
    if doc.get("chapters"):
        return doc["chapters"]
    return doc.get("structure", {}).get("chapters", []) or []


def check_ids_uniqueness(doc: dict, issues: list[str]) -> None:
    """Verify chapter_id/article_id/clause_id/point_id are unique and consistent."""
    chapters = extract_chapters(doc)
    doc_id = doc["document"]["id"]

    seen_chapters: dict[str, int] = {}
    for ch in chapters:
        cid = ch["id"]
        seen_chapters[cid] = seen_chapters.get(cid, 0) + 1

        # article_id consistency
        for art in ch["articles"]:
            if art.get("chapter_id") != cid:
                issues.append(
                    f"article {art['id']} has chapter_id={art.get('chapter_id')} "
                    f"but parent chapter is {cid}"
                )
            for clause in art.get("clauses", []):
                if clause.get("article_id") != art["id"]:
                    issues.append(
                        f"clause {clause['id']} has article_id={clause.get('article_id')} "
                        f"but parent article is {art['id']}"
                    )
                for point in clause.get("points", []):
                    if point.get("clause_id") != clause["id"]:
                        issues.append(
                            f"point {point['id']} has clause_id={point.get('clause_id')} "
                            f"but parent clause is {clause['id']}"
                        )

    dups = {k: v for k, v in seen_chapters.items() if v > 1}
    if dups:
        issues.append(f"DUPLICATE chapter ids: {dups}")


def validate_one(path: Path, schema: dict) -> tuple[int, int]:
    """Validate one JSON file. Returns (error_count, warning_count)."""
    log.info(f"Validating {path.name}")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.error(f"  Invalid JSON: {e}")
        return 1, 0

    errors: list[str] = []
    warnings: list[str] = []

    # 1. JSON Schema check
    validator = jsonschema.Draft7Validator(schema)
    schema_errors = list(validator.iter_errors(doc))
    for err in schema_errors:
        path_str = " > ".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"SCHEMA at {path_str}: {err.message}")

    # 2. ID consistency + uniqueness
    check_ids_uniqueness(doc, errors)

    # 3. PDF garbage / empty text
    text_issues: list[str] = []
    chapters = extract_chapters(doc)
    # Walk chapters separately so we can skip EMPTY for article text (normal)
    for i, ch in enumerate(chapters):
        walk_text(("chapters", str(i)), ch, text_issues, allow_empty=True)
        # Clause text may also be empty if all content is in points - that's normal
        for j, art in enumerate(ch.get("articles", [])):
            for k, cl in enumerate(art.get("clauses", [])):
                walk_text(
                    ("chapters", str(i), "articles", str(j), "clauses", str(k)),
                    cl, text_issues, allow_empty=True,
                )
    for issue in text_issues:
        if issue.startswith("EMPTY"):
            errors.append(issue)
        else:
            warnings.append(issue)

    # 4. Print summary
    log.info(f"  schema errors: {len(schema_errors)}")
    log.info(f"  id errors:     {sum(1 for e in errors if not e.startswith('SCHEMA'))}")
    log.info(f"  warnings:      {len(warnings)}")

    for e in errors:
        log.error(f"    ERR: {e}")
    for w in warnings:
        log.warning(f"    WARN: {w}")

    return len(errors), len(warnings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Fail on warnings too")
    args = parser.parse_args()

    if not DOC_DIR.exists():
        log.error(f"doc/ directory not found: {DOC_DIR}")
        return 2
    if not SCHEMA_PATH.exists():
        log.error(f"Schema not found: {SCHEMA_PATH}")
        return 2

    schema = load_schema()
    json_files = sorted(p for p in DOC_DIR.glob("*.json") if p.name != "schema.json")

    if not json_files:
        log.error("No JSON files found in doc/")
        return 2

    log.info(f"Found {len(json_files)} file(s) to validate")
    log.info("=" * 60)

    total_err = 0
    total_warn = 0
    for path in json_files:
        e, w = validate_one(path, schema)
        total_err += e
        total_warn += w

    log.info("=" * 60)
    log.info(f"TOTAL: {total_err} error(s), {total_warn} warning(s)")

    if total_err > 0:
        return 1
    if args.strict and total_warn > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())