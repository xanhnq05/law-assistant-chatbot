"""LegalStructureParser: state-machine parse Vietnamese legal document paragraphs.

Cấu trúc hierarchy:
    Document → Chapter (Chương I/II/...) → Section (Mục 1/2/...)
        → Article (Điều 1/2/...) → Clause (Khoản 1/2/...) → Point (a/b/c/đ/...)

Two modes:
- ORIGINAL  : full structure (Chapter → Section → Article → Clause → Point)
- AMENDMENT : flat articles only (each article = one change, target in title/body)

State machine transitions (ORIGINAL mode):
    INIT → CHAPTER → ARTICLE → (CLAUSE → POINT) → ARTICLE
                ↓        ↓
            SECTION   CHAPTER

Algorithm:
1. Iterate through paragraphs from docx_parser (already ordered by page)
2. Classify each paragraph: CHAPTER | SECTION | ARTICLE | CLAUSE | POINT | BODY
3. Build hierarchical JSON matching doc/document/schema.json

ID format:
- Chapter   : {doc_id}-CH-{roman}  e.g. D168-2024-ND-CP-CH-I
- Section   : {doc_id}-M-{number}  e.g. D168-2024-ND-CP-M-1
- Article   : {doc_id}-A-{number}  e.g. D168-2024-ND-CP-A-1
- Clause    : {doc_id}-K{number}    e.g. D168-2024-ND-CP-K1
- Point    : {doc_id}-P{letter}    e.g. D168-2024-ND-CP-Pa
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from app.services.docx_parser import Paragraph

log = logging.getLogger("document-service.legal_parser")

# ============================================================
# Patterns
# ============================================================
# CHƯƠNG I / CHƯƠNG II / ...
# Match exact line like "Chương I" or "CHƯƠNG II" (possibly followed by space)
# Be strict to avoid matching body text containing "chương" as a word.
CHAPTER_PATTERN = re.compile(
    r"^\s*CHƯƠNG\s+(I{1,3}|IV|V|VI{0,3})\s*$",  # Standalone header
    re.IGNORECASE,
)

# Mục 1 / Mục 2 / ...
SECTION_PATTERN = re.compile(
    r"^\s*Mục\s+(\d+|[IVX]+)\b", re.IGNORECASE
)

# Điều 1. Tiêu đề hoặc Điều 1: Tiêu đề
ARTICLE_PATTERN = re.compile(
    r"^\s*Điều\s+(\d+[A-Za-z]?)\s*[.:]\s*(.*)$"
)

# Khoản 1 / 1. (inline clause marker inside article text)
# Chuẩn: "1. Nội dung" hoặc "Khoản 1. Nội dung" hoặc "(1) Nội dung"
CLAUSE_PATTERNS = [
    re.compile(r"^\s*(?:Khoản\s+)?\(?\s*(\d+)\s*[.):]\s*(.*)$"),  # (1) or Khoản 1. or 1.
]

# Điểm: a) / b) / c) / đ) / e) ... (lowercase letter + Vietnamese diacritics letter)
# Only used in ORIGINAL mode. In AMENDMENT mode, points are quoted content
# that should stay inside the clause text (not extracted as separate points).
POINT_PATTERN = re.compile(r"^\s*([a-zđ])\s*[.):]\s*(.*)$")

# Sửa đổi / bổ sung / thay thế / xoá bỏ (amendment indicators in article body)
AMENDMENT_INDICATOR = re.compile(
    r"(?:sửa\s+đổi|bổ\s sung|thay\s+thế|xoá\s+bỏ|"
    r"bổ\s+sung\s+khoản|bổ\s+sung\s+điểm|sửa\s+đổi\s+khoản|sửa\s+đổi\s+điểm)\s+"
    r"(?:Điều|khoản|điểm)",
    re.IGNORECASE,
)

# Roman numeral → int (I=1, II=2, ..., XXXIV=34)
ROMAN_MAP = {
    "I": 1, "II": 2, "III": 3, "IV": 4,
    "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15, "XVI": 16,
    "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
    "XXI": 21, "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25,
    "XXVI": 26, "XXVII": 27, "XXVIII": 28, "XXIX": 29, "XXX": 30,
    "XXXI": 31, "XXXII": 32, "XXXIII": 33, "XXXIV": 34,
}


def _normalize_roman(roman: str) -> str:
    """Return uppercase Roman numeral."""
    return roman.strip().upper()


def _roman_to_str(roman: str) -> str:
    return _normalize_roman(roman)


# ============================================================
# Dataclasses
# ============================================================
@dataclass
class Point:
    id: str
    document_id: str
    clause_id: str
    number: str  # "a", "b", "c", "đ", "e"...
    text: str


@dataclass
class Clause:
    id: str
    document_id: str
    article_id: str
    number: str  # "1", "2", "3a", "10"...
    text: str  # raw text của khoản (không bao gồm points)
    points: List[Point] = field(default_factory=list)

    def full_text(self) -> str:
        pts = "\n".join(f"{p.number}) {p.text}" for p in self.points)
        return f"{self.text}\n{pts}".strip() if pts else self.text


@dataclass
class Article:
    id: str
    document_id: str
    chapter_id: str
    section_id: Optional[str]
    number: str  # "1", "2", "3a"...
    title: str
    text: str  # full text = clause texts concatenated
    clauses: List[Clause] = field(default_factory=list)

    def build_text(self) -> str:
        """Build `text` field = clause-level text + point text."""
        lines: List[str] = []
        for i, cl in enumerate(self.clauses, 1):
            lines.append(f"{cl.number}. {cl.full_text()}")
        return "\n".join(lines) if lines else self.text


@dataclass
class Section:
    id: str
    document_id: str
    chapter_id: str
    number: str
    title: str
    articles: List[Article] = field(default_factory=list)


@dataclass
class Chapter:
    id: str
    document_id: str
    number: str  # Roman: "I", "II", ...
    title: str
    sections: List[Section] = field(default_factory=list)
    articles: List[Article] = field(default_factory=list)  # articles directly in chapter


# ============================================================
# State Machine
# ============================================================
class ParseMode:
    ORIGINAL = "original"
    AMENDMENT = "amendment"


class State:
    INIT = "init"
    CHAPTER = "chapter"
    SECTION = "section"
    ARTICLE = "article"
    CLAUSE_BODY = "clause_body"  # inline clause inside article text


class LegalStructureParser:
    """State-machine parser for Vietnamese legal documents.

    Parameters
    ----------
    doc_id : str
        Document ID, e.g. "D168-2024-ND-CP"
    mode : str
        ORIGINAL or AMENDMENT
    source_filenames : List[str]
        For logging / multi-file tracking.
    """

    def __init__(
        self,
        doc_id: str,
        mode: str = ParseMode.ORIGINAL,
        source_filenames: Optional[List[str]] = None,
    ):
        self.doc_id = doc_id
        self.mode = mode
        self.source_filenames = source_filenames or []

        # --- State ---
        self.state = State.INIT
        self.current_chapter: Optional[Chapter] = None
        self.current_section: Optional[Section] = None
        self.current_article: Optional[Article] = None
        self.current_clause: Optional[Clause] = None
        self._pending_clause_text: str = ""  # text buffer for current inline clause

        # --- Output ---
        self.chapters: List[Chapter] = []

        # --- Counters ---
        self._article_counter: int = 0  # for AMENDMENT mode (sequential)

        # Stats
        self._stats = {"chapters": 0, "sections": 0, "articles": 0, "clauses": 0, "points": 0}

    # ============================================================
    # Public API
    # ============================================================
    def feed_paragraphs(self, paragraphs: List[Paragraph]) -> None:
        """Main entry: feed ordered paragraphs through state machine."""
        for para in paragraphs:
            self._process_paragraph(para)

        # Flush last article/clause
        self._flush_article()
        self._flush_chapter()

    def build_document_dict(self) -> Dict:
        """Build final JSON dict matching doc/document/schema.json."""
        doc_dict = {
            "schema_version": "1.1.0",
            "document": {
                "id": self.doc_id,
                "source_file": ", ".join(self.source_filenames),
            },
            "chapters": self._build_chapters_list(),
        }
        return doc_dict

    # ============================================================
    # Paragraph classification
    # ============================================================
    def _classify(self, text: str) -> Tuple[str, Dict]:
        """Classify a paragraph line. Returns (type, groups).

        Mode-dependent:
        - ORIGINAL: full structure (CHAPTER → SECTION → ARTICLE → CLAUSE → POINT)
        - AMENDMENT: flat articles only — points are quoted content kept in clause
        """
        text_stripped = text.strip()

        # Skip very short / empty lines
        if len(text_stripped) < 3:
            return "skip", {}

        # CHAPTER
        m = CHAPTER_PATTERN.match(text_stripped)
        if m:
            roman = (m.group(1) or "").strip()
            if roman:
                return "chapter", {"roman": roman}
            return "skip", {}

        # SECTION (Mục)
        m = SECTION_PATTERN.match(text_stripped)
        if m:
            return "section", {"number": m.group(1)}

        # ARTICLE
        m = ARTICLE_PATTERN.match(text_stripped)
        if m:
            art_num = m.group(1).strip()
            art_title = m.group(2).strip()
            return "article", {"number": art_num, "title": art_title}

        # CLAUSE (standalone: "Khoản X." or "(X)" at start of line)
        for pat in CLAUSE_PATTERNS:
            m = pat.match(text_stripped)
            if m:
                return "clause", {"number": m.group(1), "text": m.group(2).strip()}

        # POINT — only classify as separate point in ORIGINAL mode
        # In AMENDMENT mode, "i)" / "l)" etc are quoted content within clause
        if self.mode == ParseMode.ORIGINAL:
            m = POINT_PATTERN.match(text_stripped)
            if m:
                return "point", {"number": m.group(1), "text": m.group(2).strip()}

        # AMENDMENT: detect amendment patterns in text (title or body)
        if AMENDMENT_INDICATOR.search(text_stripped):
            return "amendment_body", {}

        return "body", {}

    # ============================================================
    # State machine transitions
    # ============================================================
    def _process_paragraph(self, para: Paragraph) -> None:
        ptype, groups = self._classify(para.text)
        text = para.text.strip()

        if ptype == "skip":
            # Empty or too short — skip
            return

        if ptype == "chapter":
            self._transition_chapter(groups["roman"], text)
            return

        if ptype == "section":
            self._transition_section(groups["number"], text)
            return

        if ptype == "article":
            self._transition_article(groups["number"], groups["title"], text)
            return

        if ptype == "clause":
            self._handle_clause(groups["number"], groups["text"])
            return

        if ptype == "point":
            self._handle_point(groups["number"], groups["text"])
            return

        # body / amendment_body — append to current article text
        self._append_to_article(text)
    def _transition_chapter(self, roman: str, full_text: str) -> None:
        """Flush previous chapter → start new chapter."""
        self._flush_article()
        self._flush_chapter()

        self.state = State.CHAPTER
        roman_str = _roman_to_str(roman)
        chapter_id = f"{self.doc_id}-CH-{roman_str}"
        title = full_text  # full text of chapter heading

        self.current_chapter = Chapter(
            id=chapter_id,
            document_id=self.doc_id,
            number=roman_str,
            title=title,
            sections=[],
            articles=[],
        )
        self._stats["chapters"] += 1
        log.debug("New chapter: %s", chapter_id)

    def _transition_section(self, number: str, full_text: str) -> None:
        """Start new section inside current chapter."""
        self._flush_article()

        if not self.current_chapter:
            # No chapter yet — create implicit chapter I
            self._transition_chapter("I", "CHƯƠNG I")

        self.state = State.SECTION
        sec_id = f"{self.doc_id}-M-{number}"
        sec = Section(
            id=sec_id,
            document_id=self.doc_id,
            chapter_id=self.current_chapter.id,
            number=number,
            title=full_text,
            articles=[],
        )
        self.current_section = sec
        self.current_chapter.sections.append(sec)
        self._stats["sections"] += 1
        log.debug("New section: %s", sec_id)

    def _transition_article(self, number: str, title: str, full_text: str) -> None:
        """Flush previous article → start new article."""
        # Bootstrap chapter if needed (AMENDMENT docs without explicit "Chương...")
        if not self.current_chapter:
            roman_str = "I"
            chapter_id = f"{self.doc_id}-CH-{roman_str}"
            self.current_chapter = Chapter(
                id=chapter_id,
                document_id=self.doc_id,
                number=roman_str,
                title="CHƯƠNG I (implicit)",
                sections=[],
                articles=[],
            )
            self._stats["chapters"] += 1

        self._flush_article()

        self.state = State.ARTICLE
        art_id = f"{self.doc_id}-A-{number}"
        chapter_id = self.current_chapter.id
        section_id = self.current_section.id if self.current_section else None

        art = Article(
            id=art_id,
            document_id=self.doc_id,
            chapter_id=chapter_id,
            section_id=section_id,
            number=number,
            title=title or full_text,  # title might be empty if title merged with number
            text="",
            clauses=[],
        )
        self.current_article = art
        self._pending_clause_text = ""
        self._stats["articles"] += 1
        log.debug("New article: %s", art_id)

    def _handle_clause(self, number: str, text: str) -> None:
        """Handle a new clause ( Khoản X. text )."""
        self._flush_clause()  # flush previous

        if not self.current_article:
            # Orphan clause — create implicit article
            self._article_counter += 1
            self._transition_article(str(self._article_counter), "", text)
            # Now set clause directly
            self._pending_clause_text = text
            return

        self.state = State.CLAUSE_BODY
        clause_id = f"{self.current_article.id}-K{number}"
        self.current_clause = Clause(
            id=clause_id,
            document_id=self.doc_id,
            article_id=self.current_article.id,
            number=number,
            text=text,
            points=[],
        )
        self._stats["clauses"] += 1
        self._pending_clause_text = ""
        log.debug("New clause: %s", clause_id)

    def _handle_point(self, letter: str, text: str) -> None:
        """Handle a point (a) text b) text ...)."""
        if not self.current_clause:
            # Orphan point — skip or create clause
            log.warning("Orphan point '%s)' without clause — skipping", letter)
            return

        point_id = f"{self.current_clause.id}-P{letter}"
        pt = Point(
            id=point_id,
            document_id=self.doc_id,
            clause_id=self.current_clause.id,
            number=letter,
            text=text,
        )
        self.current_clause.points.append(pt)
        self._stats["points"] += 1
        log.debug("New point: %s", point_id)

    def _append_to_article(self, text: str) -> None:
        """Append body text.

        - ORIGINAL mode: append to article.text (between clauses)
        - AMENDMENT mode:
            - If current_clause exists: append to clause.text (quoted content)
            - Else if current_article exists: create implicit clause "1" + set text
              (the clause will be appended to article.clauses by _flush_clause)
        """
        if self.mode == ParseMode.AMENDMENT:
            if self.current_clause is not None:
                # Append to current clause's text (quoted content)
                if self.current_clause.text:
                    self.current_clause.text += "\n" + text
                else:
                    self.current_clause.text = text
                return

            if self.current_article is not None:
                # No active clause — create an implicit clause "1" to hold this body.
                # Don't append to article.clauses here; _flush_clause will do that
                # when this article is flushed.
                implicit_id = f"{self.current_article.id}-K1"
                self.current_clause = Clause(
                    id=implicit_id,
                    document_id=self.doc_id,
                    article_id=self.current_article.id,
                    number="1",
                    text=text,
                    points=[],
                )
                self._stats["clauses"] += 1
                return

            return

        if not self.current_article:
            return
        # ORIGINAL mode: accumulate in article.text field
        if self.current_article.text:
            self.current_article.text += "\n" + text
        else:
            self.current_article.text = text

    # ============================================================
    # Flush helpers (push accumulated items to parent)
    # ============================================================
    def _flush_clause(self) -> None:
        """Push current clause into current article."""
        if self.current_clause and self.current_article:
            # If pending text exists, append it
            if self._pending_clause_text:
                self.current_clause.text = self.current_clause.text.rstrip() + "\n" + self._pending_clause_text
                self._pending_clause_text = ""
            self.current_article.clauses.append(self.current_clause)
            self.current_clause = None

    def _flush_article(self) -> None:
        """Push current article into chapter/section."""
        if not self.current_article:
            return

        # IMPORTANT: flush any remaining clause BEFORE building text
        # so build_text() can include the last clause's content.
        self._flush_clause()

        # Build final text from clauses
        self.current_article.text = self.current_article.build_text()

        # Add to section (if any) or chapter directly
        if self.current_section:
            self.current_section.articles.append(self.current_article)
        elif self.current_chapter:
            self.current_chapter.articles.append(self.current_article)
        else:
            # No chapter — create implicit chapter I (one-time bootstrap)
            log.warning("No chapter for article %s — creating implicit chapter I",
                       self.current_article.id)
            roman_str = "I"
            chapter_id = f"{self.doc_id}-CH-{roman_str}"
            self.current_chapter = Chapter(
                id=chapter_id,
                document_id=self.doc_id,
                number=roman_str,
                title="CHƯƠNG I",
                sections=[],
                articles=[],
            )
            self._stats["chapters"] += 1
            # Append directly to the new chapter
            self.current_chapter.articles.append(self.current_article)

        self.current_article = None
        self.current_clause = None
        self._pending_clause_text = ""

    def _flush_chapter(self) -> None:
        """Push current chapter into document."""
        if self.current_chapter:
            # Flush any remaining article
            self._flush_article()
            self.chapters.append(self.current_chapter)
            self.current_chapter = None

    # ============================================================
    # Build output JSON
    # ============================================================
    def _build_chapters_list(self) -> List[Dict]:
        """Build chapters array for schema."""
        result = []
        for ch in self.chapters:
            ch_dict = {
                "id": ch.id,
                "document_id": ch.document_id,
                "number": ch.number,
                "title": ch.title,
                "sections": [self._build_section(s) for s in ch.sections],
                "articles": [self._build_article(a) for a in ch.articles],
            }
            result.append(ch_dict)
        return result

    def _build_section(self, sec: Section) -> Dict:
        return {
            "id": sec.id,
            "document_id": sec.document_id,
            "chapter_id": sec.chapter_id,
            "number": sec.number,
            "title": sec.title,
            "articles": [self._build_article(a) for a in sec.articles],
        }

    def _build_article(self, art: Article) -> Dict:
        return {
            "id": art.id,
            "document_id": art.document_id,
            "chapter_id": art.chapter_id,
            "section_id": art.section_id,
            "number": art.number,
            "title": art.title,
            "text": art.text,
            "clauses": [self._build_clause(cl) for cl in art.clauses],
        }

    def _build_clause(self, cl: Clause) -> Dict:
        return {
            "id": cl.id,
            "document_id": cl.document_id,
            "article_id": cl.article_id,
            "number": cl.number,
            "text": cl.text,
            "points": [self._build_point(p) for p in cl.points],
        }

    def _build_point(self, pt: Point) -> Dict:
        return {
            "id": pt.id,
            "document_id": pt.document_id,
            "clause_id": pt.clause_id,
            "number": pt.number,
            "text": pt.text,
        }

    def get_stats(self) -> Dict:
        return dict(self._stats)


# ============================================================
# Convenience wrapper
# ============================================================
def parse_document(
    paragraphs: List[Paragraph],
    doc_id: str,
    mode: str = ParseMode.ORIGINAL,
    source_filenames: Optional[List[str]] = None,
) -> Dict:
    """One-shot parse: paragraphs → schema-compliant JSON dict."""
    # Normalize mode (accept both 'ORIGINAL' and 'original')
    if isinstance(mode, str):
        mode_lower = mode.lower()
        if mode_lower == "original":
            mode = ParseMode.ORIGINAL
        elif mode_lower == "amendment":
            mode = ParseMode.AMENDMENT

    # Large documents (e.g. 60+ articles with deep nesting) hit Python's default
    # recursion limit (1000) when flushing nested structures. Bump it.
    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old_limit, 50000))
    try:
        parser = LegalStructureParser(
            doc_id=doc_id,
            mode=mode,
            source_filenames=source_filenames,
        )
        parser.feed_paragraphs(paragraphs)
        return parser.build_document_dict()
    finally:
        sys.setrecursionlimit(old_limit)
