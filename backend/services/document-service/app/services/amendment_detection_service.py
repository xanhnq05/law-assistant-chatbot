"""Amendment detection service.

For AMENDMENT documents, each article describes a change to a target document.
This service analyzes each article's body to extract structured relationships.

Two strategies:
1. From article TITLE — parse "Sửa đổi, bổ sung ... khoản X Điều Y"
   → base target_ref = "A{Y}.K{X}"

2. From article BODY — parse "1. Sửa đổi, bổ sung điểm i ..."
   → clause-level target_ref built from title base + clause's own point/clause

Output matches doc/relationship/relationship-schema.json.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("document-service.amendment_detection")

# ============================================================
# Patterns for target extraction
# ============================================================
ARTICLE_REF = re.compile(r"Điều\s+(\d+[a-z]?)", re.IGNORECASE)
CLAUSE_REF = re.compile(r"khoản\s+(\d+[a-z]?)", re.IGNORECASE)
# Point: "điểm X" followed by separator (chữ đứng riêng, không phải "của")
# Use lookahead to ensure next char is space + non-letter or end
POINT_REF = re.compile(r"điểm\s+([a-zđe])(?=\s|$|[,.\:\;\)])", re.IGNORECASE)


# Operation verbs → relationship type
# Order matters — "sửa đổi" before "bổ sung" because most nghị định uses both.
# But to pick the primary verb, we count occurrences.
OPERATION_VERBS = [
    ("sửa đổi", "AMENDS"),
    ("bổ sung", "ADDS"),
    ("thay thế", "REPLACES"),
    ("thay bằng", "REPLACES"),
    ("bãi bỏ", "REPEALS"),
    ("xoá bỏ", "REPEALS"),
    ("xoá", "REPEALS"),
    ("bỏ", "REPEALS"),
]


@dataclass
class DetectedRelationship:
    source_ref: str
    target_ref: str
    type: str
    description: Optional[str] = None


# ============================================================
# Detection helpers
# ============================================================
def _detect_operation(text: str) -> Optional[str]:
    """Detect primary operation type from text.

    Strategy: pick the verb with highest occurrence. Tie-breaker by order
    in OPERATION_VERBS.
    """
    text_lower = text.lower()
    counts: List[tuple] = []  # (count, priority, op_type)
    for priority, (verb, op_type) in enumerate(OPERATION_VERBS):
        count = text_lower.count(verb)
        if count > 0:
            counts.append((count, priority, op_type))

    if not counts:
        return None

    # Sort: higher count first, then lower priority number (= higher precedence)
    counts.sort(key=lambda x: (-x[0], x[1]))
    return counts[0][2]


def _extract_article_clause_point(text: str) -> Optional[Dict[str, str]]:
    """Extract target article/clause/point refs from amendment text.

    Examples:
        "Điều 3"                     → {"article": "3"}
        "khoản 3 Điều 6"             → {"article": "6", "clause": "3"}
        "điểm i khoản 3 Điều 6"      → {"article": "6", "clause": "3", "point": "i"}

    Returns dict with keys "article", "clause", "point" (whichever found).
    """
    art_m = ARTICLE_REF.search(text)
    if not art_m:
        return None

    result: Dict[str, str] = {"article": art_m.group(1)}

    # Look for clause BEFORE the article
    before_art = text[: art_m.start()]
    cl_m = CLAUSE_REF.search(before_art)
    if cl_m:
        result["clause"] = cl_m.group(1)
        # Look for point before clause
        before_cl = before_art[: cl_m.start()]
        pt_m = POINT_REF.search(before_cl)
        if pt_m:
            result["point"] = pt_m.group(1)
    else:
        # Maybe just point + article (no clause)
        pt_m = POINT_REF.search(before_art)
        if pt_m:
            result["point"] = pt_m.group(1)

    return result


def _build_ref(parts: Dict[str, str]) -> str:
    """Build target_ref string from parts dict."""
    out = [f"A{parts['article']}"]
    if "clause" in parts:
        out.append(f"K{parts['clause']}")
    if "point" in parts:
        out.append(f"P{parts['point']}")
    return ".".join(out)


def _detect_from_article(
    *,
    article: Dict,
    document_id: str,
    target_doc_id: str,
) -> List[DetectedRelationship]:
    """Detect relationships from one article."""
    results: List[DetectedRelationship] = []

    art_num = article.get("number", "")
    art_title = article.get("title", "")
    art_text = article.get("text", "")
    art_id = article.get("id", "")

    # Determine operation from title (primary source of truth)
    op_type = _detect_operation(art_title) or _detect_operation(art_text)
    if op_type is None:
        log.debug("Art %s: no operation verb found", art_num)
        return results

    # Extract base ref from title (most reliable)
    title_ref = _extract_article_clause_point(art_title)

    clauses = article.get("clauses", [])

    if clauses:
        # ---- Per-clause relationship ----
        for cl in clauses:
            cl_num = cl.get("number", "")
            cl_id = cl.get("id", "")
            cl_text = cl.get("text", "")

            # Try clause text first; fall back to title base
            cl_ref = _extract_article_clause_point(cl_text)
            if cl_ref is None:
                cl_ref = title_ref
            elif title_ref and "article" in title_ref:
                # Merge: use clause's own point, but article/clause from title
                if "point" not in cl_ref and "point" in title_ref:
                    cl_ref = {**title_ref, **cl_ref}
                # Always trust clause's article if it has one
                cl_ref = {**title_ref, **cl_ref}

            if cl_ref is None:
                continue

            target_ref = _build_ref(cl_ref)
            description = cl_text[:200] if cl_text else None
            results.append(
                DetectedRelationship(
                    source_ref=cl_id,
                    target_ref=target_ref,
                    type=op_type,
                    description=description,
                )
            )
    else:
        # ---- Single relationship for entire article ----
        if title_ref is None:
            return results

        target_ref = _build_ref(title_ref)
        description = art_title[:200] if art_title else None
        results.append(
            DetectedRelationship(
                source_ref=art_id,
                target_ref=target_ref,
                type=op_type,
                description=description,
            )
        )

    return results


# ============================================================
# Main entry
# ============================================================
def detect_relationships(
    *,
    parsed_doc: Dict,
    target_doc_id: str,
    source_doc_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build relationships từ 1 parsed AMENDMENT document.

    Returns:
        List các relationship dicts (RelationshipRecord format) — outgoing direction
        cho source_doc_id. Caller chịu trách nhiệm propagate đến target_doc_id.

        Mỗi item:
            {
              "source": {"document_id": str, "article_id"?: str, "clause_id"?: str},
              "target": {"document_id": str, "article_id"?: str, "clause_id"?: str},
              "type": "AMENDS" | "ADDS" | "REPLACES" | "REPEALS",
              "description": str,
              "confidence": 0.0-1.0,
              "detected_at": ISO8601
            }
    """
    from datetime import datetime, timezone

    actual_source = source_doc_id or parsed_doc.get("document", {}).get("id", "")

    all_relationships: List[DetectedRelationship] = []

    for ch in parsed_doc.get("chapters", []):
        for art in ch.get("articles", []):
            rels = _detect_from_article(
                article=art,
                document_id=actual_source,
                target_doc_id=target_doc_id,
            )
            all_relationships.extend(rels)
        for sec in ch.get("sections", []):
            for art in sec.get("articles", []):
                rels = _detect_from_article(
                    article=art,
                    document_id=actual_source,
                    target_doc_id=target_doc_id,
                )
                all_relationships.extend(rels)

    log.info(
        "Detected %d relationships from %s → %s",
        len(all_relationships),
        actual_source,
        target_doc_id,
    )

    detected_at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "source": _parse_source_ref(r.source_ref, actual_source),
            "target": _parse_target_ref(r.target_ref, target_doc_id),
            "type": r.type,
            "description": r.description,
            "confidence": 0.85,  # default — heuristic-based detector
            "detected_at": detected_at,
        }
        for r in all_relationships
    ]


def _parse_source_ref(ref: str, document_id: str) -> Dict[str, str]:
    """Parse source_ref string → {document_id, article_id?, clause_id?, point_id?}.

    Accept multiple formats:
      - Full ID: 'D236-2026-ND-CP-CI-A1', 'D236-...-K5', 'D236-...-A-1-K2-Pi'
      - Short ref: 'A3', 'A3.K2', 'A3.K2.Pa'

    Returns dict with keys 'document_id', optionally 'article_id'/'clause_id'/'point_id'
    (point_id only for full IDs since short 'P' refs are ambiguous).
    """
    out: Dict[str, str] = {"document_id": document_id}
    if not ref:
        return out

    # Try full ID format first (starts with document_id)
    if ref.startswith(document_id):
        # Strip document_id prefix
        rest = ref[len(document_id):].lstrip("-")
        # rest is like 'A-1', 'A-1-K2', 'K5', etc.
        parts = [p for p in rest.split("-") if p]
        # Walk through to identify labels
        i = 0
        cur_art = None
        cur_cl = None
        while i < len(parts):
            p = parts[i]
            if p == "A" and i + 1 < len(parts):
                cur_art = parts[i + 1]
                out["article_id"] = cur_art
                i += 2
            elif p.startswith("K") and len(p) > 1:
                cur_cl = p[1:]
                out["clause_id"] = cur_cl
                i += 1
            elif p.startswith("P") and len(p) > 1:
                out["point_id"] = p[1:]
                i += 1
            else:
                i += 1
        return out

    # Fall back to short ref format 'A3.K2.Pa'
    parts = ref.split(".")
    for p in parts:
        if p.startswith("A") and len(p) > 1 and p[1:].isdigit():
            out["article_id"] = p[1:]
        elif p.startswith("K") and len(p) > 1 and p[1:].isdigit():
            out["clause_id"] = p[1:]
    return out


def _parse_target_ref(ref: str, document_id: str) -> Dict[str, str]:
    """Parse target_ref string → target endpoint.

    target_ref format: 'A{n}.K{m}.P{x}' — Article-Clause-Point
    KHÔNG có prefix document_id (vì target là document khác).
    """
    out: Dict[str, str] = {"document_id": document_id}
    if not ref:
        return out
    parts = ref.split(".")
    for p in parts:
        if p.startswith("A") and len(p) > 1:
            out["article_id"] = p[1:]  # just '3' for 'A3'
        elif p.startswith("K") and len(p) > 1:
            out["clause_id"] = p[1:]
        elif p.startswith("P") and len(p) > 1:
            out["point_id"] = p[1:]
    return out


# ============================================================
# Validation
# ============================================================
def validate_relationship_json(rel_json: Dict) -> None:
    """Validate against relationship-schema.json. Raise ValueError on failure."""
    import jsonschema

    schema_path = (
        Path(__file__).resolve().parents[4] / "schema" / "relationship-schema.json"
    )
    if not schema_path.exists():
        log.warning("Schema not found: %s", schema_path)
        return

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    try:
        jsonschema.validate(instance=rel_json, schema=schema)
        log.info("Relationship JSON validated OK")
    except jsonschema.ValidationError as exc:
        log.error("Relationship validation FAILED: %s", exc.message)
        raise ValueError(
            f"Relationship validation failed at {list(exc.path)}: {exc.message}"
        ) from exc
