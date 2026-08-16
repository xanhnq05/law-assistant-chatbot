"""
Merge split legal document JSON files into one canonical document.

Strategy (chosen by user): keep_split
  - File 1 (`36-2024-qh15.json`) contains: Chapter I (A01..A09) + Chapter II part-1 (A10..A23)
  - File 2 (`36-2024-qh15_tiep.json`) contains: Chapter II part-2 (A24..A33) + Chapter III..IX
  - Same `document.id` (L36-2024-QH15) and same `chapter.id` (CII) appear in both files
    because the source PDF was split across two issues of the Official Gazette.

To avoid ID collision we rename the split chapters:
  - In file 1:  CII  -> CII-A   (carries articles 10..23)
  - In file 2:  CII  -> CII-B   (carries articles 24..33)

We then merge into a single `36-2024-qh15.json` with chapters ordered I, II-A, II-B, III..IX
so that Neo4j/Pinecone ingestion has exactly one Document node and one canonical chapter list.

Run:
    cd tro_ly_luat
    python data_import/merge_law36.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("merge-law36")

ROOT = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "doc"

# Source files (kept for traceability; not deleted automatically)
FILE_PART_1 = DOC_DIR / "36-2024-qh15.json"          # contains: Chương I + Chương II (Đ10-23)
FILE_PART_2 = DOC_DIR / "36-2024-qh15_tiep.json"     # contains: Chương II (Đ24-33) + III..IX

# Output: single canonical file (will overwrite the current part-1 file with merged content)
OUTPUT = DOC_DIR / "36-2024-qh15.json"

# Backup of the original split files (so you can revert if anything goes wrong)
BACKUP_DIR = DOC_DIR / ".backup_split"

CHAPTER_RENAME = {
    # part -> renames applied in that part before merging
    FILE_PART_1: {"L36-2024-QH15-CII": "L36-2024-QH15-CII-A"},
    FILE_PART_2: {"L36-2024-QH15-CII": "L36-2024-QH15-CII-B"},
}


def rename_chapter_ids(doc: dict, mapping: dict[str, str]) -> int:
    """Rename chapter.id and all dependent ids inside a doc according to mapping.
    Returns number of chapters renamed."""
    renamed = 0
    for ch in doc["chapters"]:
        old_id = ch["id"]
        if old_id in mapping:
            new_id = mapping[old_id]
            new_suffix = new_id[len("L36-2024-QH15-"):]   # e.g. "CII-A"
            # rename chapter.id + chapter_id references on every article
            ch["id"] = new_id
            for art in ch["articles"]:
                art["chapter_id"] = new_id
                art["id"] = art["id"].replace(old_id, new_id)
                for clause in art.get("clauses", []):
                    clause["article_id"] = clause["article_id"].replace(old_id, new_id)
                    clause["id"] = clause["id"].replace(old_id, new_id)
                    for point in clause.get("points", []):
                        point["clause_id"] = point["clause_id"].replace(old_id, new_id)
                        point["id"] = point["id"].replace(old_id, new_id)
            renamed += 1
            log.info(f"  Renamed chapter {old_id} -> {new_id}")
    return renamed


def merge_documents() -> dict:
    """Load both parts, rename IDs, merge into a single document."""
    log.info(f"Loading {FILE_PART_1.name}")
    part1 = json.loads(FILE_PART_1.read_text(encoding="utf-8"))
    log.info(f"Loading {FILE_PART_2.name}")
    part2 = json.loads(FILE_PART_2.read_text(encoding="utf-8"))

    # Sanity: same document.id
    if part1["document"]["id"] != part2["document"]["id"]:
        raise ValueError(
            f"document.id mismatch: {part1['document']['id']} vs {part2['document']['id']}"
        )

    # Rename split chapters so IDs do not collide
    log.info("Renaming split chapters:")
    rename_chapter_ids(part1, CHAPTER_RENAME[FILE_PART_1])
    rename_chapter_ids(part2, CHAPTER_RENAME[FILE_PART_2])

    # Merge document metadata: take part1 as base, keep `part` from part2 as note
    merged_doc = dict(part1["document"])
    merged_doc.pop("part", None)
    part_note = part2["document"].get("part")
    if part_note:
        merged_doc["part_note"] = part_note

    # Merge chapters in correct order: I, II-A, II-B, III, IV, V, VI, VII, VIII, IX
    chapters = part1["chapters"] + part2["chapters"]

    roman_order = ["I", "II-A", "II-B", "III", "IV", "V", "VI", "VII", "VIII", "IX"]
    chapters.sort(key=lambda c: roman_order.index(c["number"]) if c["number"] in roman_order else 999)

    return {
        "document": merged_doc,
        "chapters": chapters,
        "schema_version": "1.0.0",
    }


def add_metadata(doc: dict) -> None:
    """Add required fields that were missing in the original files."""
    md = doc["document"]
    md.setdefault("document_type", "Luật")
    md.setdefault("issuing_authority", "Quốc hội")
    md.setdefault("source_version", "v1")
    md.setdefault("status", "active")


def main() -> None:
    log.info("Merging Luật 36/2024/QH15 split files...")
    merged = merge_documents()
    add_metadata(merged)

    # Back up originals first
    BACKUP_DIR.mkdir(exist_ok=True)
    for f in [FILE_PART_1, FILE_PART_2]:
        backup = BACKUP_DIR / f.name
        backup.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        log.info(f"Backed up {f.name} -> .backup_split/{f.name}")

    # Write merged output
    OUTPUT.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Wrote merged file: {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")

    # Delete the now-redundant part-2 file
    if FILE_PART_2.exists():
        FILE_PART_2.unlink()
        log.info(f"Deleted redundant file: {FILE_PART_2.name}")

    # Summary
    log.info("=" * 60)
    log.info(f"Merged chapters ({len(merged['chapters'])}):")
    for ch in merged["chapters"]:
        n_art = len(ch["articles"])
        n_cl = sum(len(a.get("clauses", [])) for a in ch["articles"])
        n_pt = sum(
            len(c.get("points", []))
            for a in ch["articles"]
            for c in a.get("clauses", [])
        )
        log.info(
            f"  {ch['number']:>6} | {ch['id']:<35} | "
            f"{n_art:>2} điều, {n_cl:>3} khoản, {n_pt:>3} điểm | "
            f"{ch['title']}"
        )


if __name__ == "__main__":
    main()