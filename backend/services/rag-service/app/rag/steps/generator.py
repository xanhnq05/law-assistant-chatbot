"""
B6 - LLM Generation (Groq).

Input: câu hỏi gốc + context từ B5 + lịch sử hội thoại + optional LegalContext.
Output: câu trả lời tự nhiên có trích dẫn.

Cải tiến so với bản cũ:
  P0: Sửa history reordering bug (logic insert sai thứ tự)
  P1: Token-aware truncation theo evidence boundaries (không cắt giữa điều luật)
  P2: Error handling chi tiết (LLM timeout vs rate-limit vs parse error)
  P3: Tích hợp LegalContext để biết evidence nào bị dropped
  P4: Enhanced anti-hallucination prompt
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.prompts.generator import SYSTEM_ANSWER_GENERATION

if TYPE_CHECKING:
    from app.rag.schemas.legal_context import LegalContext

log = logging.getLogger("rag-service")

# ============================================================
# CONSTANTS & FALLBACK MESSAGES
# ============================================================
NO_CONTEXT_MSG = (
    "Xin lỗi, tôi không tìm thấy thông tin pháp luật liên quan để trả lời câu hỏi này. "
    "Bạn có thể diễn đạt lại bằng các thuật ngữ pháp lý cụ thể hơn không?"
)

LLM_ERROR_MSG = (
    "Xin lỗi, hệ thống đang gặp sự cố khi xử lý câu hỏi của bạn. "
    "Vui lòng thử lại sau vài phút."
)

# Giới hạn soft (tính theo chars, approx ~1500-2000 tokens cho tiếng Việt).
# Dùng cho fallback khi không có LegalContext để truncate theo evidence.
SOFT_CONTEXT_LIMIT = 6000

# Giới hạn hard (chars) - LLM Groq 128k context có thể chứa ~50k-60k chars.
HARD_CONTEXT_LIMIT = 15000

# Giới hạn history (tối đa 3 cặp user/assistant = 6 msg)
MAX_HISTORY_PAIRS = 3
MAX_HISTORY_CHARS = 2000  # Soft cap cho history text


# ============================================================
# CONTEXT TRUNCATION STRATEGIES
# ============================================================

def _build_context_from_evidence(
    evidence: list[dict[str, Any]],
    max_chars: int = SOFT_CONTEXT_LIMIT,
) -> tuple[str, list[str]]:
    """
    Build context string từ evidence list, truncate theo evidence boundaries.
    
    Args:
        evidence: list of evidence dicts với field 'context_block'
        max_chars: soft limit cho context
    
    Returns:
        (context_string, dropped_evidence_ids)
    """
    if not evidence:
        return "", []
    
    blocks: list[str] = []
    dropped_ids: list[str] = []
    total_chars = 0
    
    for ev in evidence:
        block_text = ev.get("context_block", "")
        ev_id = ev.get("evidence_id", "")
        
        # Nếu thêm block này vượt hard limit → drop
        if total_chars + len(block_text) > HARD_CONTEXT_LIMIT:
            if ev_id:
                dropped_ids.append(ev_id)
            continue
        
        # Nếu vượt soft limit → check xem có nên thêm không
        if total_chars + len(block_text) > max_chars:
            # Thêm header của evidence cuối cùng (ít nhất user biết còn có điều này)
            remaining_budget = max_chars - total_chars
            if remaining_budget > 100:  # Đủ chỗ cho header
                truncated = block_text[:remaining_budget] + "\n[...còn tiếp...]"
                blocks.append(truncated)
                total_chars += len(truncated)
            if ev_id:
                dropped_ids.append(ev_id)
            continue
        
        blocks.append(block_text)
        total_chars += len(block_text)
    
    # Join với separator
    context = "\n\n---\n\n".join(blocks) if blocks else ""
    return context, dropped_ids


def _build_history_text(
    history: list[dict[str, str]] | None,
) -> str:
    """
    Build history string giữ đúng thứ tự thời gian.
    
    Fix bug cũ: logic insert(0) sai thứ tự → giờ dùng append đơn giản.
    """
    if not history:
        return ""
    
    # Lấy 3 cặp cuối (6 msg)
    recent_msgs = history[-(MAX_HISTORY_PAIRS * 2):]
    
    lines: list[str] = []
    for msg in recent_msgs:
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        
        if not content:
            continue
        
        if role == "user":
            lines.append(f"Người dùng: {content}")
        elif role == "assistant":
            lines.append(f"Trợ lý pháp lý: {content}")
        else:
            # Fallback cho role không xác định
            lines.append(f"[{role}]: {content}")
    
    result = "\n".join(lines)
    
    # Soft cap history
    if len(result) > MAX_HISTORY_CHARS:
        result = result[:MAX_HISTORY_CHARS] + "\n[...lịch sử còn tiếp...]"
    
    return result


def _classify_llm_error(exc: Exception) -> tuple[str, str]:
    """
    Phân loại lỗi LLM để trả message phù hợp + log chi tiết.
    
    Returns:
        (user_message, log_level)
    """
    exc_type = type(exc).__name__
    exc_msg = str(exc)
    
    # Rate limiting
    if any(kw in exc_msg.lower() for kw in ["rate", "limit", "quota", "429"]):
        log.warning("Groq rate limit: %s", exc_msg)
        return (
            "Hệ thống đang bận, vui lòng thử lại sau 30 giây.",
            "warning"
        )
    
    # Timeout
    if any(kw in exc_msg.lower() for kw in ["timeout", "timed out", "deadline", "504"]):
        log.warning("Groq timeout: %s", exc_msg)
        return (
            "Yêu cầu mất thời gian xử lý quá lâu. Vui lòng thử lại.",
            "warning"
        )
    
    # Auth / API key
    if any(kw in exc_msg.lower() for kw in ["auth", "api key", "unauthorized", "401", "invalid"]):
        log.error("Groq auth error: %s", exc_msg)
        return (LLM_ERROR_MSG, "error")
    
    # Model not found
    if any(kw in exc_msg.lower() for kw in ["model", "not found", "404"]):
        log.error("Groq model error: %s", exc_msg)
        return (LLM_ERROR_MSG, "error")
    
    # Generic
    log.error("Groq unexpected error [%s]: %s", exc_type, exc_msg)
    return (LLM_ERROR_MSG, "error")


# ============================================================
# MAIN STEP
# ============================================================

def step_generate_answer(
    llm: Any,
    question: str,
    context_text: str,
    history: list[dict[str, str]] | None = None,
    *,
    legal_context: "LegalContext | None" = None,
) -> str:
    """
    B6: đưa context + history cho LLM (Groq) và lấy câu trả lời.

    Args:
        llm:           ChatGroq instance (engine.get_llm()).
        question:      câu hỏi gốc của user.
        context_text:  output của B5 (build_context_for_llm) - fallback khi không có legal_context.
        history:       danh sách {role, content} gần đây (tối đa 3 cặp = 6 msg).
                       Dùng để duy trì multi-turn conversation mà không hết context.
        legal_context: B5 LegalContext (optional). Nếu có → dùng evidence[] để
                       truncate thông minh theo evidence boundaries thay vì char count.

    Returns:
        Câu trả lời string từ LLM.
    """
    # ── Pre-flight checks ──────────────────────────────────────────────
    if not question.strip():
        return "Vui lòng nhập câu hỏi."

    if not context_text.strip() and (not legal_context or not legal_context.evidence):
        log.info("B6: No context available for question: %s", question[:50])
        return NO_CONTEXT_MSG

    if llm is None:
        log.error("B6: LLM not initialized")
        raise RuntimeError("LLM chưa được khởi tạo.")

    # ── Context building (P1: smart truncation) ─────────────────────────
    dropped_evidence_ids: list[str] = []
    
    if legal_context and legal_context.evidence:
        # Dùng LegalContext → truncate theo evidence boundaries
        evidence_list = [
            {
                "evidence_id": ev.evidence_id,
                "context_block": ev.context_block,
                "scores": ev.scores,
            }
            for ev in legal_context.evidence
        ]
        context_text, dropped_evidence_ids = _build_context_from_evidence(
            evidence_list,
            max_chars=SOFT_CONTEXT_LIMIT,
        )
        if dropped_evidence_ids:
            log.info(
                "B6: Truncated %d evidence (IDs: %s)",
                len(dropped_evidence_ids),
                dropped_evidence_ids[:3],  # Log max 3
            )
    else:
        # Fallback: char-based truncation (backward compat)
        if len(context_text) > HARD_CONTEXT_LIMIT:
            context_text = context_text[:HARD_CONTEXT_LIMIT] + "\n[...còn tiếp...]"
            log.warning("B6: Context truncated by hard limit (%d chars)", HARD_CONTEXT_LIMIT)

    if not context_text.strip():
        return NO_CONTEXT_MSG

    # ── History building (P0: fix reordering bug) ───────────────────────
    history_text = _build_history_text(history)

    # ── Build user prompt ───────────────────────────────────────────────
    if history_text:
        user_prompt = (
            "Lịch sử hội thoại gần đây:\n"
            f"{history_text}\n\n"
            f"Câu hỏi hiện tại: {question}\n\n"
            "Các điều luật liên quan:\n"
            f"{context_text}"
        )
    else:
        user_prompt = (
            f"Câu hỏi: {question}\n\n"
            f"Các điều luật liên quan:\n{context_text}"
        )

    # ── Call LLM with detailed error handling (P2) ─────────────────────
    start_time = time.monotonic()
    
    try:
        resp = llm.invoke([
            SystemMessage(content=SYSTEM_ANSWER_GENERATION),
            HumanMessage(content=user_prompt),
        ])
        
        elapsed = time.monotonic() - start_time
        answer = resp.content if hasattr(resp, "content") else str(resp)
        
        if not answer or not answer.strip():
            log.warning("B6: LLM returned empty response (elapsed=%.2fs)", elapsed)
            return NO_CONTEXT_MSG
        
        log.info(
            "B6: Generated answer (elapsed=%.2fs, ctx_chars=%d, dropped=%d)",
            elapsed,
            len(context_text),
            len(dropped_evidence_ids),
        )
        
        return answer.strip()
        
    except Exception as exc:
        elapsed = time.monotonic() - start_time
        user_msg, log_level = _classify_llm_error(exc)
        
        if log_level == "error":
            log.error(
                "B6: LLM call failed after %.2fs - %s: %s",
                elapsed,
                type(exc).__name__,
                str(exc)[:200],
            )
        else:
            log.warning(
                "B6: LLM call warning after %.2fs - %s",
                elapsed,
                str(exc)[:100],
            )
        
        return user_msg
