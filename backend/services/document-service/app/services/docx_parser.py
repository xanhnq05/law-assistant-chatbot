"""DOCX/DOC parser: extract raw text + paragraph metadata from Word files.

- .docx  → python-docx
- .doc   → PyMuPDF (legacy binary Word → PDF-like text extraction)
- .pdf   → PyMuPDF

Supports multi-file stream: calling `extract_from_bytes()` multiple times returns
paragraphs in order, preserving document order for ORIGINAL multi-file docs.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator, List, Optional

import fitz  # PyMuPDF

log = logging.getLogger("document-service.docx_parser")

# ============================================================
# Paragraph dataclass
# ============================================================
@dataclass
class Paragraph:
    """Một đoạn văn bản thuần túy (không style info).

    Attributes
    ----------
    text : str
        Nội dung text, đã strip whitespace.
    source_filename : str
        Tên file nguồn (để debug multi-file).
    page_hint : int
        Số trang ước lượng (1-indexed). PyMuPDF bắt đầu từ 1.
        Chỉ chính xác với PDF; DOCX → 0.
    """

    text: str
    source_filename: str = ""
    page_hint: int = 0

    def is_empty(self) -> bool:
        return not self.text.strip()


# ============================================================
# Text extraction engines
# ============================================================
def _extract_from_docx_bytes(data: bytes, filename: str) -> Iterator[Paragraph]:
    """Extract text từ DOCX (OpenXML .docx) buffer.

    python-docx không đọc được .doc binary (legacy OLE).
    """
    try:
        import docx
    except ImportError:
        log.error("python-docx not installed — cannot parse .docx files")
        return

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:
        log.error("python-docx failed to open %s: %s", filename, exc)
        return

    for para in doc.paragraphs:
        text = para.text.strip()
        if text:
            yield Paragraph(text=text, source_filename=filename, page_hint=0)

    # Extract also table cells (văn bản pháp luật hiếm khi có bảng,
    # nhưng đề phòng trường hợp table chứa điều khoản)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    text = para.text.strip()
                    if text:
                        yield Paragraph(
                            text=text,
                            source_filename=filename,
                            page_hint=0,
                        )


def _extract_from_pdf_bytes(data: bytes, filename: str) -> Iterator[Paragraph]:
    """Extract text từ PDF buffer dùng PyMuPDF."""
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        log.error("PyMuPDF failed to open %s as PDF: %s", filename, exc)
        return

    for page_num, page in enumerate(doc, start=1):
        try:
            text = page.get_text("text").strip()
        except Exception as exc:
            log.warning("Failed to extract text from page %d of %s: %s", page_num, filename, exc)
            continue
        if text:
            yield Paragraph(text=text, source_filename=filename, page_hint=page_num)


def _extract_from_legacy_doc_bytes(data: bytes, filename: str) -> Iterator[Paragraph]:
    """Extract text từ legacy .doc (OLE binary).

    Strategy (in order):
    1. Try Windows COM Word.Application (best quality, requires pywin32 + Word installed)
    2. Try PyMuPDF (works for some .doc files converted internally)
    3. Best-effort OLE raw text fallback

    Yields Paragraph objects in reading order.
    """
    import os
    import sys

    # ---- 1. COM Word.Application (Windows only) ----
    if sys.platform == "win32":
        try:
            from app.services.doc_com_parser import extract_text_com
            texts = extract_text_com(data, filename)
            if texts:
                log.info(
                    "COM Word extraction: %d paragraphs from %s",
                    len(texts),
                    filename,
                )
                for text in texts:
                    yield Paragraph(text=text, source_filename=filename, page_hint=0)
                return  # success
        except Exception as exc:
            log.debug("COM Word extraction not available for %s: %s", filename, exc)

    # ---- 2. PyMuPDF (try OLE directly) ----
    try:
        doc = fitz.open(stream=data, filetype="doc")
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                yield Paragraph(text=text, source_filename=filename, page_hint=page_num)
        return
    except Exception:
        pass

    # ---- 3. Best-effort OLE raw text fallback ----
    yield from _extract_ole_text_fallback(data, filename)


def _extract_ole_text_fallback(data: bytes, filename: str) -> Iterator[Paragraph]:
    """Fallback OLE text extraction — chỉ lấy text blocks từ Word document stream.

    Đây là best-effort cho legacy .doc. Nếu fail hoàn toàn → log error.
    """
    try:
        # Tìm text blocks trong OLE Word document stream
        # Word dùng FC (file character) offset trong WordDocument stream
        # Đơn giản: tìm sequences của printable characters dài > 20
        import re

        # Lọc các byte printable ASCII + Vietnamese chars (UTF-8 multi-byte)
        # Bước 1: thử decode as UTF-16LE (common Windows encoding)
        try:
            text_utf16 = data.decode("utf-16-le", errors="ignore")
        except Exception:
            text_utf16 = ""

        blocks: List[str] = []
        current = []

        for i, ch in enumerate(text_utf16):
            code = ord(ch)
            # printable: space → ~  plus Vietnamese diacritics
            if 0x20 <= code <= 0x7E or (0xC0 <= code <= 0x24FF) or ch in "\n\r\t":
                current.append(ch)
            else:
                if len(current) >= 20:
                    block = "".join(current).strip()
                    if block:
                        blocks.append(block)
                current = []

        if current and len(current) >= 20:
            block = "".join(current).strip()
            if block:
                blocks.append(block)

        # Deduplicate + yield
        seen = set()
        for block in blocks:
            if block not in seen:
                seen.add(block)
                yield Paragraph(text=block, source_filename=filename, page_hint=0)

    except Exception as exc:
        log.error("OLE fallback extraction failed for %s: %s", filename, exc)


# ============================================================
# Main public API
# ============================================================
def extract_paragraphs(data: bytes, filename: str) -> List[Paragraph]:
    """Extract paragraphs từ file buffer.

    Auto-detects format từ extension:
    - .docx  → python-docx
    - .doc   → legacy OLE binary (.doc)
    - .pdf   → PyMuPDF

    Returns
    -------
    List[Paragraph]
        Danh sách paragraphs theo thứ tự xuất hiện trong file.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "docx":
        log.info("Extracting paragraphs from %s (DOCX)", filename)
        return list(_extract_from_docx_bytes(data, filename))

    if ext == "pdf":
        log.info("Extracting paragraphs from %s (PDF)", filename)
        return list(_extract_from_pdf_bytes(data, filename))

    if ext == "doc":
        log.info("Extracting paragraphs from %s (legacy DOC)", filename)
        return list(_extract_from_legacy_doc_bytes(data, filename))

    log.warning("Unknown file extension '%s' for %s — skipping", ext, filename)
    return []


def extract_paragraphs_from_files(
    file_data_list: List[tuple[bytes, str]]
) -> List[Paragraph]:
    """Extract paragraphs từ nhiều files, giữ nguyên thứ tự.

    Parameters
    ----------
    file_data_list : List[Tuple[bytes, filename]]
        Mỗi tuple là (file_bytes, original_filename).

    Returns
    -------
    List[Paragraph]
        Tất cả paragraphs từ tất cả files, theo thứ tự.
        `source_filename` giữ nguyên để debug.
    """
    all_paragraphs: List[Paragraph] = []
    for data, filename in file_data_list:
        paras = extract_paragraphs(data, filename)
        all_paragraphs.extend(paras)
        log.info("Extracted %d paragraphs from %s", len(paras), filename)
    return all_paragraphs
