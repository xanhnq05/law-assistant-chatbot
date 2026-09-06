"""
B7 - Symbolic Verification (HYBRID: rule-based + LLM-as-Judge).

Mục tiêu: xác thực câu trả lời có:
  1. Trích dẫn rõ ràng (Điều X, Khoản Y)
  2. Trích dẫn khớp với context_blocks
  3. Trả lời đúng câu hỏi
  4. Không bịa thông tin ngoài context

Chiến lược hybrid (rule-based + LLM-as-Judge):
  - Rule-based (luôn chạy, nhanh, deterministic):
      * Detect citation pattern trong answer (Điều X, Khoản Y)
      * Match citation với context_blocks
      * Score rule = 0-1 dựa trên các rule trên
  - LLM-as-Judge (optional, chạy nếu rule score không đủ cao):
      * Cho LLM (verifier_llm, model nhỏ + nhanh) đánh giá grounded/correct/addressed
      * Trả về confidence + issues
  - Cuối cùng: combine 2 score → status (PASS / WARN / FAIL)

Đây chính là bước 7 trong kiến trúc image 2 (Hybrid RAG system).
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import VERIFICATION_PASS_THRESHOLD, VERIFIER_LLM_ENABLED, log
from app.core.models import VerificationResult, VerificationStatus
from app.rag.prompts.verifier import SYSTEM_VERIFIER


# ============================================================
# RULE-BASED DETECTORS
# ============================================================
# Pattern cho citation: "Điều 6", "Điều 6 Khoản 4", "Điều 6, Khoản 4, Điểm a"
_CITATION_PATTERN = re.compile(
    r"Điều\s+(\d+\w*)"
    r"(?:\s*,?\s*Khoản\s+(\d+\w*))?"
    r"(?:\s*,?\s*Điểm\s+(\w+))?",
    flags=re.IGNORECASE,
)


def _extract_citations(text: str) -> list[dict[str, str]]:
    """Trích xuất tất cả citation từ text → list {article, clause, point}."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for m in _CITATION_PATTERN.finditer(text):
        art, clause, point = m.groups()
        key = (art or "", clause or "", point or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "article": art or "",
            "clause": clause or "",
            "point": point or "",
        })
    return out


def _context_has_citation(context_blocks: list[dict[str, Any]], citation: dict[str, str]) -> bool:
    """Kiểm tra 1 citation có xuất hiện trong context_blocks không."""
    art = citation.get("article", "")
    if not art:
        return False
    for b in context_blocks:
        # So khớp article_number từ context block
        if str(b.get("article_number", "")).strip() == art:
            # Nếu có clause mà context không có → fail
            clause = citation.get("clause", "")
            if clause and str(b.get("clause_number", "")).strip() != clause:
                continue
            return True
    return False


def _rule_based_score(answer: str, context_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Chạy các rule symbolic để đánh giá answer.

    Returns dict:
      - has_citation: bool
      - citation_count: int
      - cites_valid_doc: bool
      - context_grounded: bool (approximation)
      - score: float (0-1)
      - issues: list[str]
    """
    issues: list[str] = []
    if not answer or not answer.strip():
        return {
            "has_citation": False,
            "citation_count": 0,
            "cites_valid_doc": False,
            "context_grounded": False,
            "score": 0.0,
            "issues": ["empty_answer"],
        }

    citations = _extract_citations(answer)
    has_citation = bool(citations)
    if not has_citation:
        issues.append("no_citation_detected")

    cites_valid_doc = False
    if has_citation:
        valid_count = sum(1 for c in citations if _context_has_citation(context_blocks, c))
        cites_valid_doc = valid_count > 0
        if not cites_valid_doc:
            issues.append("citation_not_in_context")
    else:
        valid_count = 0

    # Heuristic grounded: nếu answer có chứa text trùng với context
    # (substring ≥ 30 chars) thì có dấu hiệu grounded.
    context_grounded = False
    answer_lower = answer.lower()
    for b in context_blocks:
        ctx_text = (b.get("context_block") or "").lower()
        if not ctx_text:
            continue
        # Check 1 clause/article title có xuất hiện trong answer không
        art_num = str(b.get("article_number", "")).strip()
        if art_num and f"điều {art_num}" in answer_lower:
            context_grounded = True
            break
        # Hoặc check 1 đoạn text khớp
        if len(ctx_text) > 50 and ctx_text[:80] in answer_lower:
            context_grounded = True
            break

    # ============================================================
    # Tính điểm tổng (0 - 1)
    # ============================================================
    score = 0.0
    if has_citation:
        score += 0.4
    if cites_valid_doc:
        score += 0.3
    if context_grounded:
        score += 0.3
    # Penalty nếu có câu "tôi không tìm thấy"
    if "không tìm thấy" in answer_lower or "không đủ thông tin" in answer_lower:
        score = min(score, 0.4)
        issues.append("fallback_no_context")

    return {
        "has_citation": has_citation,
        "citation_count": len(citations),
        "cites_valid_doc": cites_valid_doc,
        "context_grounded": context_grounded,
        "score": round(score, 3),
        "issues": issues,
    }


# ============================================================
# LLM-AS-JUDGE
# ============================================================
def _parse_llm_json(content: str) -> dict[str, Any] | None:
    content = content.strip()
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
            if content.startswith("json"):
                content = content[4:]
    content = content.strip()
    try:
        return json.loads(content)
    except Exception:
        return None


def _llm_judge(verifier_llm, question: str, answer: str, context_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Gọi LLM verifier (model nhỏ) để chấm điểm answer có grounded không."""
    # Rút gọn context để tiết kiệm token
    ctx_lines = []
    for i, b in enumerate(context_blocks[:5], start=1):
        ctx_lines.append(f"[{i}] {b.get('citation','')}: {b.get('context_block','')[:400]}")
    ctx_text = "\n".join(ctx_lines)

    user_prompt = (
        f"question: {question}\n\n"
        f"answer: {answer[:1500]}\n\n"
        f"context_blocks:\n{ctx_text}"
    )

    try:
        raw = verifier_llm.invoke([
            {"role": "system", "content": SYSTEM_VERIFIER},
            {"role": "user", "content": user_prompt},
        ])
        # Handle cả dict response hoặc object với .content
        content = ""
        if isinstance(raw, dict):
            content = raw.get("content", "")
        else:
            content = getattr(raw, "content", "") or ""
        parsed = _parse_llm_json(content)
        if parsed:
            return {
                "is_grounded": bool(parsed.get("is_grounded", False)),
                "has_citation": bool(parsed.get("has_citation", False)),
                "citation_correct": bool(parsed.get("citation_correct", False)),
                "addresses_question": bool(parsed.get("addresses_question", False)),
                "confidence": float(parsed.get("confidence", 0.0)),
                "issues": list(parsed.get("issues") or []),
                "reason": str(parsed.get("reason") or ""),
            }
    except Exception as exc:
        log.warning("LLM verifier failed: %s", exc)

    return {
        "is_grounded": False,
        "has_citation": False,
        "citation_correct": False,
        "addresses_question": False,
        "confidence": 0.0,
        "issues": ["llm_judge_failed"],
        "reason": "",
    }


# ============================================================
# MAIN STEP
# ============================================================
def step_verify_answer(
    verifier_llm,
    question: str,
    answer: str,
    context_blocks: list[dict[str, Any]],
    *,
    use_llm_judge: bool | None = None,
) -> VerificationResult:
    """
    B7: Symbolic Verification (hybrid rule + LLM-as-Judge).

    Args:
        verifier_llm:  LLM để chấm (engine.get_verifier_llm()).
        question:      câu hỏi user.
        answer:        câu trả lời từ B6.
        context_blocks: list các dict từ B4 (có citation + context_block).
        use_llm_judge: nếu None → lấy từ config VERIFIER_LLM_ENABLED.

    Returns:
        VerificationResult (Pydantic).
    """
    # 1) Rule-based (luôn chạy)
    rule = _rule_based_score(answer, context_blocks)
    rule_score = rule["score"]
    issues = list(rule["issues"])

    # 2) LLM-as-Judge (optional)
    should_use_llm = (
        use_llm_judge if use_llm_judge is not None else VERIFIER_LLM_ENABLED
    )
    llm_used = False
    llm_reason: str | None = None
    llm_conf = 0.0
    if should_use_llm and verifier_llm is not None:
        judge = _llm_judge(verifier_llm, question, answer, context_blocks)
        llm_used = True
        llm_reason = judge.get("reason") or None
        llm_conf = float(judge.get("confidence", 0.0))
        if judge.get("issues"):
            issues.extend([f"llm:{i}" for i in judge["issues"]])

    # 3) Combine score
    # Trọng số: rule 60%, LLM 40% (nếu LLM có dùng)
    if llm_used:
        final_score = round(0.6 * rule_score + 0.4 * llm_conf, 3)
    else:
        final_score = rule_score

    # 4) Quyết định status
    if final_score >= VERIFICATION_PASS_THRESHOLD and rule["has_citation"] and rule["cites_valid_doc"]:
        status = VerificationStatus.PASS
    elif final_score >= VERIFICATION_PASS_THRESHOLD * 0.5:
        status = VerificationStatus.WARN
    else:
        status = VerificationStatus.FAIL

    return VerificationResult(
        status=status,
        confidence=final_score,
        has_citation=rule["has_citation"],
        citation_count=rule["citation_count"],
        cites_valid_doc=rule["cites_valid_doc"],
        context_grounded=rule["context_grounded"],
        issues=issues,
        llm_judge_used=llm_used,
        llm_judge_reason=llm_reason,
    )
