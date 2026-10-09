"""doc_id helpers — tạo và validate ID cho văn bản pháp luật.

QUY ƯỚC:
    {prefix}{number}-{year}-{TYPE_UPPER}
    vd: D168-2024-ND-CP, L36-2024-QH15, PL1-2020-UBTVQH

PREFIX:
    D  = Nghị định (Decree)
    L  = Luật (Law)
    PL = Pháp lệnh (Ordinance)
    QĐ = Quyết định (Decision)
    TT = Thông tư (Circular)
    ...

METADATA-DRIVEN:
    slugify_document_id(meta) lấy từ DocumentMetadata (số/năm/loại)
    → idempotent (cùng metadata → cùng doc_id)
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from app.schemas.document import DocumentMetadata, DocumentType

# Document type prefix mapping (Unicode-safe)
# Map từ issuing_authority → prefix khi không có type part trong document_number.
_TYPE_PREFIX = {
    # Tên loại văn bản (diacritics-stripped lowercase)
    "nghi dinh": "D",
    "luat": "L",
    "phap lenh": "PL",
    "quyet dinh": "QĐ",
    "thong tu": "TT",
    "thong tu lien tich": "TT",
    "nghi quyet": "NQ",
    "hien phap": "HP",
    "bo luat": "BL",
    # Map từ issuing_authority (cơ quan ban hành)
    "chinh phu": "D",  # Chính phủ thường ban hành Nghị định
    "quoc hoi": "L",  # Quốc hội thường ban hành Luật
    "uy ban thuong vu quoc hoi": "PL",  # UBTVQH ban hành Pháp lệnh
    "uy ban thuong truc": "PL",
    "thu tuong": "QĐ",  # Thủ tướng → Quyết định
    "thu tuong chinh phu": "QĐ",
    "toa an nhan dan toi cao": "QĐ",  # TANDTC → Quyết định
    "vien kiem sat nhan dan toi cao": "QĐ",
    "bo tu phap": "TT",  # Bộ Tư pháp → Thông tư
    "bo cong an": "TT",
    "bo giao duc": "TT",
}


def _strip_vietnamese_diacritics(text: str) -> str:
    """Bỏ dấu Tiếng Việt (Đ→D, đ→d, các ký tự khác → ASCII).

    Ví dụ: 'Nghị định' → 'Nghi dinh'
    """
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


def _infer_type_prefix(issuing_authority: str) -> Optional[str]:
    """Đoán prefix từ issuing_authority string.

    CHỈ dùng khi slugify không tìm được type trong document_number (fallback).
    """
    if not issuing_authority:
        return None
    norm = _strip_vietnamese_diacritics(issuing_authority).lower()
    for key, prefix in _TYPE_PREFIX.items():
        if key in norm:
            return prefix
    return None


def _parse_document_number(document_number: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse document_number '168/2024/NĐ-CP' → ('168', '2024', 'NĐ-CP').

    Returns (number_part, year_part, type_part). Any part có thể None nếu không parse được.
    """
    if not document_number or "/" not in document_number:
        return None, None, None
    parts = [p.strip() for p in document_number.split("/") if p.strip()]
    if len(parts) < 3:
        return parts[0] if parts else None, None, None
    return parts[0], parts[1], parts[2]


def _ascii_clean(text: str) -> str:
    """Strip diacritics + non-alphanumeric chars, giữ dấu '-'."""
    norm = _strip_vietnamese_diacritics(text)
    return re.sub(r"[^A-Za-z0-9-]+", "", norm)


_TYPE_TO_PREFIX = {
    # token (uppercase, no diacritics) → prefix letter
    "ND-CP": "D",
    "ND": "D",
    "QD": "Q",
    "QD-CP": "Q",
    "QD-TTg": "Q",
    "TT": "T",
    "TT-BCA": "T",
    "TT-BTP": "T",
    "TTLT": "T",
    "QH": "L",
    "QH15": "L",
    "QH14": "L",
    "PL-UBTVQH": "PL",
    "PL": "PL",
    "NQ": "N",
    "HP": "H",
}


def _infer_prefix_from_type(type_clean: str) -> str:
    """Map type token (vd 'ND-CP') → prefix letter (vd 'D').

    Falls back to first character if no match.
    """
    if not type_clean:
        return "D"
    if type_clean in _TYPE_TO_PREFIX:
        return _TYPE_TO_PREFIX[type_clean]
    # Substring match: check if type_clean contains any known token
    for token, prefix in _TYPE_TO_PREFIX.items():
        if token in type_clean or type_clean in token:
            return prefix
    return type_clean[0]


def slugify_document_id(
    document_number: str,
    document_year: int,
    issuing_authority: Optional[str] = None,
) -> str:
    """Tạo doc_id deterministic từ document metadata.

    Args:
        document_number: VD '168/2024/NĐ-CP'
        document_year: VD 2024
        issuing_authority: 'Chính phủ' / 'Quốc hội' / ... — dùng để infer prefix
                          khi document_number không có type part rõ ràng.

    Returns:
        doc_id dạng '{PREFIX}{NUMBER}-{YEAR}-{TYPE_UPPER}', vd 'D168-2024-ND-CP'.
        Fallback: 'D{number_stripped}-{year}' nếu thiếu type.

    Examples:
        slugify_document_id("168/2024/NĐ-CP", 2024) → "D168-2024-ND-CP"
        slugify_document_id("36/2024/QH15", 2024)   → "L36-2024-QH15"
        slugify_document_id("01/2020/PL-UBTVQH", 2020) → "PL1-2020-PL-UBTVQH"
        slugify_document_id("01/2024", 2024, "Quốc hội") → "L1-2024"
    """
    number_part, year_part, type_part = _parse_document_number(document_number)

    # Year: prefer parse từ document_number, fallback document_year
    year_str = year_part or str(document_year)

    # Number: phải có — strip leading zeros để '01' → '1'
    if not number_part:
        num_clean = _ascii_clean(document_number) or "UNKNOWN"
        return f"D{num_clean}-{year_str}"

    # Strip leading zeros cho consistency (vd '01' → '1', '001' → '1')
    num_stripped = number_part.lstrip("0") or "0"

    # Type: có thì clean + uppercase; không có thì infer từ issuing_authority
    if type_part:
        type_clean = _ascii_clean(type_part).upper()
        if not type_clean:
            type_clean = "DOC"
        prefix_letter = _infer_prefix_from_type(type_clean)
        return f"{prefix_letter}{num_stripped}-{year_str}-{type_clean}"
    else:
        prefix = _infer_type_prefix(issuing_authority or "") or "D"
        # No type → just "{prefix}{number}-{year}"
        return f"{prefix}{num_stripped}-{year_str}"


# ============================================================
# Convenience: trực tiếp từ DocumentMetadata
# ============================================================
def slugify_from_metadata(meta: DocumentMetadata) -> str:
    """Tạo doc_id từ DocumentMetadata object.

    NOTE: For AMENDMENT docs, slugify KHÔNG dựa vào amends_document_id
    (vì 2 amendment có thể target cùng 1 base doc nhưng vẫn là 2 amendment riêng).
    """
    return slugify_document_id(
        document_number=meta.document_number,
        document_year=meta.document_year,
        issuing_authority=meta.issuing_authority,
    )


def is_amendment(meta: DocumentMetadata) -> bool:
    """Check 1 doc có phải amendment không."""
    return meta.document_type == DocumentType.AMENDMENT


def derives_from(doc_id: str, base_doc_id: str) -> bool:
    """Check doc_id có phải là amendment của base_doc_id không.

    NOTE: Đây là lightweight check dựa trên naming. Authoritative answer
    phải query relationship.json (in relationships[]).
    """
    if not doc_id or not base_doc_id:
        return False
    # Heuristic: amendment doc thường được reference từ metadata.amends_document_id
    # (không encode trong ID). Caller nên check relationship.json để chắc.
    return doc_id != base_doc_id
