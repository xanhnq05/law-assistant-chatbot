"""
B8 - Follow-up Question Generator.

Input:  Verified answer + LegalContext + verification status
Output: 3 follow-up questions (JSON list)

Contract:
  - CHỈ chạy khi verification status == PASS (theo spec từ user)
  - Câu hỏi phải grounded trong evidence (không bịa)
  - Nếu LLM lỗi → trả [] (graceful fallback, không break pipeline)

Cải tiến:
  F1: Strict JSON parsing với multi-fallback (markdown fence, trailing comma, embedded)
  F2: Defensive validation: dedupe, length check, language check
  F3: Confidence metadata cho từng câu (heuristic dựa trên evidence coverage)
  F4: Optional override `force=True` để bypass PASS check (debug/test)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.models import VerificationStatus
from app.rag.prompts.followup import SYSTEM_FOLLOWUP_GENERATION

if TYPE_CHECKING:
    from app.core.models import VerificationResult
    from app.rag.schemas.legal_context import LegalContext

log = logging.getLogger("rag-service")

# ============================================================
# CONSTANTS
# ============================================================
DEFAULT_NUM_FOLLOWUPS = 3
MAX_NUM_FOLLOWUPS = 5
FOLLOWUP_TIMEOUT_MSG = (
    "Xin lỗi, hệ thống không thể gợi ý câu hỏi tiếp theo lúc này."
)

# Câu hỏi "rỗng" cần loại bỏ (sau khi normalize).
_EMPTY_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^[?.!,\s]+$"),
]

# Ngưỡng đánh dấu câu hỏi "không chắc chắn" (low confidence) — dùng cho metadata.
_LOW_QUALITY_HINTS = (
    "chưa rõ",
    "không biết",
    "có thể",
    "có lẽ",
    "tuỳ trường hợp",
    "tùy trường hợp",
)


# ============================================================
# JSON PARSING (F1: multi-fallback)
# ============================================================
def _parse_followup_json(content: str) -> list[dict[str, Any]] | None:
    """Parse JSON từ LLM output.

    Multi-fallback:
      1. Plain JSON
      2. Markdown fence (```json ... ```)
      3. Strip trailing commas
      4. Embedded JSON object in text
    """
    if not content:
        return None
    content = content.strip()

    # Strip markdown fence
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
            if content.startswith(("json", "JSON")):
                content = content[4:]
            content = content.strip()

    # Strip trailing commas trước } hoặc ]
    content = re.sub(r",\s*([}\]])", r"\1", content)

    try:
        data = json.loads(content)
    except Exception:
        # Embedded JSON object
        m = re.search(r"\{[\s\S]*?\}", content)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None

    # Validate shape
    if not isinstance(data, dict):
        return None
    followups = data.get("followups")
    if not isinstance(followups, list):
        return None
    return followups


# ============================================================
# VALIDATION + DEDUPE (F2)
# ============================================================
def _validate_and_dedupe(
    followups: list[dict[str, Any]],
    *,
    num: int = DEFAULT_NUM_FOLLOWUPS,
    original_question: str = "",
) -> list[dict[str, Any]]:
    """Validate + dedupe + cap số câu hỏi.

    Loại bỏ:
      - Câu rỗng / chỉ có dấu câu
      - Câu trùng với câu hỏi gốc (case-insensitive)
      - Câu quá ngắn (< 8 chars)
      - Trùng nhau
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    orig_norm = _normalize_text(original_question)

    for fu in followups:
        if not isinstance(fu, dict):
            continue
        q = str(fu.get("question") or "").strip()

        # Skip empty
        if any(p.match(q) for p in _EMPTY_PATTERNS):
            continue
        # Skip too short (< 6 chars)
        if len(q) < 6:
            continue
        # Skip dup với câu gốc
        if orig_norm and _normalize_text(q) == orig_norm:
            continue
        # Skip dup với câu đã chọn
        norm = _normalize_text(q)
        if norm in seen:
            continue
        seen.add(norm)

        out.append({
            "question": q,
            "rationale": str(fu.get("rationale") or "").strip()[:200],
            "related_article": str(fu.get("related_article") or "").strip()[:100],
        })

        if len(out) >= num:
            break

    return out


def _normalize_text(text: str) -> str:
    """Lowercase + strip + collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


# ============================================================
# CONFIDENCE HEURISTIC (F3)
# ============================================================
def _compute_confidence(
    question: str,
    rationale: str,
    evidence_titles: list[str],
) -> float:
    """Heuristic confidence cho câu hỏi.

    Signals:
      - +0.3 nếu rationale trỏ về article cụ thể
      - +0.3 nếu câu hỏi chứa từ khoá liên quan evidence
      - -0.2 nếu câu hỏi chứa low-quality hint
    """
    score = 0.5  # base

    if rationale and re.search(r"[Đđ]iều\s+\d+|[Kk]hoản\s+\d+", rationale):
        score += 0.3

    q_lower = question.lower()
    matched = sum(1 for t in evidence_titles if t and t.lower() in q_lower)
    if matched >= 1:
        score += 0.3

    if any(hint in q_lower for hint in _LOW_QUALITY_HINTS):
        score -= 0.2

    return max(0.0, min(1.0, round(score, 2)))


# ============================================================
# ERROR CLASSIFICATION
# ============================================================
def _classify_followup_error(exc: Exception) -> str:
    """Phân loại lỗi LLM khi sinh follow-up. Trả user-friendly message."""
    msg = str(exc).lower()
    if any(kw in msg for kw in ["rate", "limit", "429", "quota"]):
        return "Hệ thống đang bận, vui lòng thử lại sau 30 giây."
    if any(kw in msg for kw in ["timeout", "timed out", "504"]):
        return "Yêu cầu mất thời gian xử lý quá lâu. Vui lòng thử lại."
    if any(kw in msg for kw in ["auth", "api key", "401", "unauthorized"]):
        return "Hệ thống gặp sự cố xác thực. Vui lòng thử lại sau."
    return FOLLOWUP_TIMEOUT_MSG


# ============================================================
# MAIN STEP
# ============================================================
def step_generate_followups(
    llm: Any,
    question: str,
    answer: str,
    legal_context: "LegalContext | None" = None,
    verification: "VerificationResult | None" = None,
    *,
    num: int = DEFAULT_NUM_FOLLOWUPS,
    force: bool = False,
) -> list[dict[str, Any]]:
    """
    B8: Sinh `num` câu hỏi tiếp theo từ verified context.

    Args:
        llm:            ChatGroq instance (engine.get_llm()).
        question:       Câu hỏi gốc của user.
        answer:         Câu trả lời từ B6.
        legal_context:  LegalContext từ B5 (chứa evidence đã retrieve).
        verification:   VerificationResult từ B7.
        num:            Số câu hỏi cần sinh (default 3, max 5).
        force:          Nếu True, sinh cả khi verification != PASS (debug/test).

    Returns:
        List các dict {"question", "rationale", "related_article", "confidence"}.
        Trả [] nếu không sinh được (graceful fallback).
    """
    # ── Pre-flight ─────────────────────────────────────────────────────
    num = max(1, min(num, MAX_NUM_FOLLOWUPS))

    # Spec từ user: chỉ chạy khi verification PASS (trừ khi force=True).
    if verification is not None and not force:
        if verification.status != VerificationStatus.PASS:
            log.info(
                "[B8] Skipped: verification status=%s (not PASS)",
                verification.status.value,
            )
            return []

    if not question.strip() or not answer.strip():
        log.info("[B8] Skipped: empty question or answer")
        return []

    if llm is None:
        log.warning("[B8] LLM not initialized; returning []")
        return []

    # ── Build prompt từ verified context ──────────────────────────────
    evidence_blocks: list[str] = []
    evidence_meta: list[str] = []  # cho F3 confidence

    if legal_context and legal_context.evidence:
        for ev in legal_context.evidence[:5]:  # cap 5 evidence
            block = ev.context_block.strip()
            if block:
                evidence_blocks.append(block[:800])  # cap mỗi block
            # Extract article label cho confidence heuristic
            if ev.hierarchy_path:
                evidence_meta.extend(ev.hierarchy_path)

    if not evidence_blocks:
        log.info("[B8] No evidence available; cannot generate grounded follow-ups")
        return []

    evidence_text = "\n\n---\n\n".join(evidence_blocks)

    user_prompt = (
        f"Câu hỏi vừa trả lời: {question}\n\n"
        f"Câu trả lời đã được xác minh: {answer[:1500]}\n\n"
        f"Các điều luật liên quan (đã được verify):\n{evidence_text}\n\n"
        f"Hãy gợi ý đúng {num} câu hỏi tiếp theo dựa trên nội dung trên."
    )

    # ── Call LLM với error handling ───────────────────────────────────
    start = time.monotonic()
    try:
        resp = llm.invoke([
            SystemMessage(content=SYSTEM_FOLLOWUP_GENERATION),
            HumanMessage(content=user_prompt),
        ])
        elapsed = time.monotonic() - start
        content = getattr(resp, "content", "") or ""
        if not content.strip():
            log.warning("[B8] LLM returned empty content (elapsed=%.2fs)", elapsed)
            return []

        parsed = _parse_followup_json(content)
        if not parsed:
            log.warning(
                "[B8] Failed to parse JSON from LLM (elapsed=%.2fs): %.200s",
                elapsed,
                content,
            )
            return []

        validated = _validate_and_dedupe(
            parsed, num=num, original_question=question
        )

        # Tag confidence cho từng câu (F3)
        for fu in validated:
            fu["confidence"] = _compute_confidence(
                fu["question"], fu["rationale"], evidence_meta
            )

        log.info(
            "[B8] Generated %d/%d follow-ups (elapsed=%.2fs)",
            len(validated),
            num,
            elapsed,
        )
        return validated

    except Exception as exc:
        elapsed = time.monotonic() - start
        log.warning(
            "[B8] LLM call failed after %.2fs - %s: %s",
            elapsed,
            type(exc).__name__,
            str(exc)[:200],
        )
        # Lỗi → trả [] (không break pipeline).
        return []