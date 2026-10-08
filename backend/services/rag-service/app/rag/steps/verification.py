"""
B7 - Symbolic Verification (HYBRID: rule-based + LLM-as-Judge) - Improved.

Mục tiêu: xác thực câu trả lời có:
  1. Trích dẫn rõ ràng (Điều X, Khoản Y, Điểm Z)
  2. Trích dẫn khớp với context_blocks (article/clause/point tồn tại)
  3. Nội dung grounded trên context (không bịa)
  4. Văn bản trích dẫn còn hiệu lực (không bị REPEALS/REPLACES)
  5. Trả lời đúng câu hỏi

Cải tiến so với bản cũ:
  P7: Multi-pattern citation regex (match cả format đảo ngược, viết tắt, có prefix)
  P8: Tăng cường context_grounded (check content evidence, không chỉ header)
  P9: Verify amendments (REPEALS/REPLACES compliance)
  P12: Few-shot examples trong LLM judge prompt
  P13: Friendly output messages cho user (human-readable warnings/reasons)
  P14: Detailed status breakdown trả cho frontend
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import VERIFICATION_PASS_THRESHOLD, VERIFIER_LLM_ENABLED, log
from app.core.models import VerificationResult, VerificationStatus
from app.rag.prompts.verifier import SYSTEM_VERIFIER
from app.rag.schemas.legal_context import LegalContext


# ============================================================
# P7: MULTI-PATTERN CITATION REGEX
# ============================================================
# Pattern 1: "Điều 6, Khoản 4, Điểm a" (chuẩn)
# Pattern 2: "Khoản 4 Điều 6" (đảo thứ tự)
# Pattern 3: "Điều 6.4" (viết tắt với dấu chấm)
# Pattern 4: "Điều 6 Khoản 4(a)" (có ngoặc đơn)
# Pattern 5: "Nghị định 168, Điều 6" (có prefix văn bản)

_CITATION_PATTERNS = [
    # Pattern 1: Điều X, Khoản Y, Điểm Z (chuẩn nhất)
    re.compile(
        r"[Đđ]iều\s+(\d+\w*)"
        r"(?:\s*,?\s*[Kk]hoản\s+(\d+\w*))?"
        r"(?:\s*,?\s*[Đđ]iểm\s+(\w+))?"
    ),
    # Pattern 2: Khoản Y Điều X (đảo thứ tự)
    re.compile(
        r"[Kk]hoản\s+(\d+\w*)\s+(?:của\s+)?[Đđ]iều\s+(\d+\w*)"
    ),
    # Pattern 3: Điều X.Khoản Y hoặc Điều X.Y (viết tắt)
    re.compile(
        r"[Đđ]iều\s+(\d+\w*)\s*\.\s*(\d+\w*)"
    ),
    # Pattern 4: Điều X Khoản Y (Điểm Z) - có ngoặc đơn cho điểm
    re.compile(
        r"[Đđ]iều\s+(\d+\w*)\s*,?\s*[Kk]hoản\s+(\d+\w*)\s*\(\s*[Đđ]iểm\s*(\w+)\s*\)"
    ),
]


def _extract_citations(text: str) -> list[dict[str, str]]:
    """Trích xuất tất cả citation từ text → list {article, clause, point}.

    Multi-pattern để match nhiều format citation tiếng Việt.
    """
    if not text:
        return []

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for pattern_idx, pattern in enumerate(_CITATION_PATTERNS):
        for m in pattern.finditer(text):
            groups = list(m.groups())
            if not groups or not groups[0]:
                continue

            # Xác định article/clause/point dựa trên pattern index
            # Pattern 0: Điều X, Khoản Y, Điểm Z (chuẩn)
            # Pattern 1: Khoản X Điều Y (đảo thứ tự - PHẢI detect)
            # Pattern 2: Điều X.Khoản Y (viết tắt)
            # Pattern 3: Điều X Khoản Y (Điểm Z) - có ngoặc

            if pattern_idx == 1:
                # Pattern 2 (đảo thứ tự): groups = (khoản, điều)
                clause, article = groups[0], groups[1] if len(groups) > 1 else ""
                point = ""
            else:
                # Pattern 1, 3, 4: groups = (điều, khoản?, điểm?)
                article = groups[0]
                clause = groups[1] if len(groups) > 1 and groups[1] else ""
                point = groups[2] if len(groups) > 2 and groups[2] else ""

            key = (article, clause, point)
            if key in seen or not article:
                continue
            seen.add(key)
            out.append({
                "article": article,
                "clause": clause,
                "point": point,
            })

    return out


def _context_has_citation(
    context_blocks: list[dict[str, Any]],
    citation: dict[str, str],
) -> bool:
    """Kiểm tra 1 citation có xuất hiện trong context_blocks không.

    Match theo article_number + clause_number + point_number (nếu có).
    """
    art = str(citation.get("article", "")).strip()
    if not art:
        return False

    for b in context_blocks:
        if str(b.get("article_number", "")).strip() != art:
            continue

        # Nếu có clause mà context không có → fail
        clause = str(citation.get("clause", "")).strip()
        ctx_clause = str(b.get("clause_number", "")).strip()
        if clause and ctx_clause and clause != ctx_clause:
            continue

        # Nếu có point mà context không có → fail
        point = str(citation.get("point", "")).strip()
        ctx_point = str(b.get("point_number", "")).strip()
        if point and ctx_point and point != ctx_point:
            continue

        return True

    return False


def _extract_doc_prefix(text: str) -> str | None:
    """Trích xuất prefix văn bản từ text (vd: 'Nghị định 168/2024/NĐ-CP').

    Hiện tại dùng cho debug/logging. Có thể mở rộng để detect thêm trong tương lai.
    """
    if not text:
        return None
    m = re.search(
        r"(?:Nghị định|Luật|Pháp lệnh|Quyết định|Thông tư)\s+([\d/\w\-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        return f"{m.group(0).split()[0]} {m.group(1)}"
    return None


def _check_amendments_compliance(
    answer: str,
    context_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check LLM có trích dẫn văn bản đã bị REPEALS/REPLACES không.

    Returns:
        {
            "is_compliant": bool,
            "warnings": list[str],  # human-readable
            "affected_targets": list[str],  # vd: ['Nghị định 123']
        }
    """
    warnings: list[str] = []
    affected: list[str] = []
    answer_lower = answer.lower()

    for b in context_blocks:
        amendments = b.get("related_amendments") or []
        for amend in amendments:
            amend_type = (amend.get("type") or "").upper()
            if amend_type not in ("REPEALS", "REPLACES"):
                continue

            target_label = amend.get("target_label") or ""
            target_number = amend.get("target_number") or ""
            target_doc_type = amend.get("target_document_type") or ""

            # Xác định tên văn bản bị thay thế (full identifier)
            target_full = ""
            if target_doc_type and target_number:
                target_full = f"{target_doc_type} {target_number}".lower()

            # Check answer có đề cập văn bản bị REPEALS không
            mentioned = False
            if target_full and target_full in answer_lower:
                mentioned = True
            elif target_number and f"số {target_number}" in answer_lower:
                mentioned = True
            elif target_number and target_number in answer_lower:
                # Chỉ check nếu match đủ số hiệu (không bị false positive)
                # VD: "168" match trong "Nghị định 168" nhưng cũng match trong "168 giờ"
                # Heuristic: phải có prefix (Nghị định/Luật/...) trước số
                pattern = rf"(?:nghị định|luật|pháp lệnh)\s+{target_number}\b"
                if re.search(pattern, answer_lower, re.IGNORECASE):
                    mentioned = True

            if mentioned:
                # Check xem answer có acknowledge văn bản bị thay thế không
                has_ack = any(
                    phrase in answer_lower
                    for phrase in [
                        "thay thế", "hết hiệu lực", "không còn hiệu lực",
                        "bị thay thế", "đã được thay thế", "được thay thế bởi",
                        "replaced", "repealed",
                    ]
                )
                if not has_ack:
                    affected.append(target_label or target_number)
                    warnings.append(
                        f"Câu trả lời trích dẫn {target_label or target_number} "
                        f"(đã bị {amend_type}) nhưng không ghi nhận văn bản đã hết hiệu lực."
                    )

    return {
        "is_compliant": len(warnings) == 0,
        "warnings": warnings,
        "affected_targets": affected,
    }


# ============================================================
# RULE-BASED SCORING
# ============================================================

def _rule_based_score(
    answer: str,
    context_blocks: list[dict[str, Any]],
    amendments_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chạy các rule symbolic để đánh giá answer.

    Returns dict:
      - has_citation: bool
      - citation_count: int
      - valid_citation_count: int (match với context)
      - cites_valid_doc: bool
      - context_grounded: bool (approximation via content match)
      - amendments_compliant: bool
      - score: float (0-1)
      - issues: list[str] (human-readable)
    """
    issues: list[str] = []

    if not answer or not answer.strip():
        return {
            "has_citation": False,
            "citation_count": 0,
            "valid_citation_count": 0,
            "cites_valid_doc": False,
            "context_grounded": False,
            "amendments_compliant": True,
            "score": 0.0,
            "issues": ["empty_answer"],
        }

    citations = _extract_citations(answer)
    has_citation = bool(citations)

    if not has_citation:
        issues.append("Không tìm thấy trích dẫn Điều/Khoản trong câu trả lời.")

    cites_valid_doc = False
    valid_count = 0
    if has_citation:
        valid_count = sum(
            1 for c in citations if _context_has_citation(context_blocks, c)
        )
        cites_valid_doc = valid_count > 0
        if not cites_valid_doc:
            issues.append(
                f"Tìm thấy {len(citations)} trích dẫn nhưng không khớp với context nào."
            )

    # P8: Enhanced context_grounded check
    # Cần >= 2 tín hiệu: article_number + (article_title HOẶC content body)
    # → tránh false positive chỉ vì "Điều 6" xuất hiện
    context_grounded = False
    answer_lower = answer.lower()
    grounded_reasons: list[str] = []

    for b in context_blocks:
        ctx_text = (b.get("context_block") or "").lower()
        if not ctx_text:
            continue

        signals = 0  # Đếm tín hiệu matching

        # Signal 1: Article number có xuất hiện trong answer không
        art_num = str(b.get("article_number", "")).strip()
        if art_num and f"điều {art_num}" in answer_lower:
            signals += 1
            grounded_reasons.append(f"article:{art_num}")

        # Signal 2: Article title có xuất hiện trong answer không (≥ 10 chars)
        art_title = str(b.get("article_title", "")).strip().lower()
        if art_title and len(art_title) >= 10 and art_title in answer_lower:
            signals += 1
            grounded_reasons.append(f"article_title")

        # Signal 3: Một đoạn text từ context xuất hiện trong answer
        # Check độ dài body (sau khi strip header) mới đúng
        body_start = ctx_text.find("\n")
        body = ctx_text[body_start:] if body_start > 0 else ctx_text
        body = body.lstrip("\n ")
        if len(body) > 30:
            for substr_len in (80, 50, 30):
                if len(body) > substr_len and body[:substr_len] in answer_lower:
                    signals += 1
                    grounded_reasons.append(f"content_match:{substr_len}")
                    break

        # Grounded nếu có ≥ 2 signals (article_number + title/content)
        # Điều này tránh false positive chỉ vì "Điều 6" xuất hiện
        if signals >= 2:
            context_grounded = True
            break

    if not context_grounded and context_blocks:
        issues.append(
            "Không phát hiện nội dung câu trả lời khớp rõ ràng với context."
        )

    # ============================================================
    # P9: Amendments compliance check
    # ============================================================
    if amendments_check is None:
        amendments_check = _check_amendments_compliance(answer, context_blocks)

    if not amendments_check["is_compliant"]:
        issues.extend(amendments_check["warnings"])

    # ============================================================
    # Tính điểm tổng (0 - 1) - weighted scoring
    # ============================================================
    score = 0.0
    if has_citation:
        score += 0.30
    if cites_valid_doc:
        score += 0.25
    if context_grounded:
        score += 0.30
    if amendments_check["is_compliant"]:
        score += 0.15

    # Penalty cho câu fallback
    if "không tìm thấy" in answer_lower or "không đủ thông tin" in answer_lower:
        score = min(score, 0.4)
        issues.append("Câu trả lời fallback - không có context phù hợp.")

    return {
        "has_citation": has_citation,
        "citation_count": len(citations),
        "valid_citation_count": valid_count,
        "cites_valid_doc": cites_valid_doc,
        "context_grounded": context_grounded,
        "amendments_compliant": amendments_check["is_compliant"],
        "score": round(score, 3),
        "issues": issues,
        "grounded_reasons": grounded_reasons,
    }


# ============================================================
# LLM-AS-JUDGE
# ============================================================
def _parse_llm_json(content: str) -> dict[str, Any] | None:
    """Parse JSON từ LLM output (handle markdown fence + trailing commas)."""
    if not content:
        return None
    content = content.strip()

    # Strip markdown fence
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
            if content.startswith("json"):
                content = content[4:]
            elif content.startswith("JSON"):
                content = content[4:]

    content = content.strip()

    # Remove trailing commas trước } hoặc ]
    content = re.sub(r",\s*([}\]])", r"\1", content)

    try:
        return json.loads(content)
    except Exception:
        pass

    # Fallback: tìm JSON object trong text
    m = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass

    return None


def _llm_judge(
    verifier_llm,
    question: str,
    answer: str,
    context_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Gọi LLM verifier (model nhỏ) để chấm điểm answer có grounded không."""
    # Rút gọn context để tiết kiệm token
    ctx_lines = []
    for i, b in enumerate(context_blocks[:5], start=1):
        ctx_lines.append(
            f"[{i}] {b.get('citation','')}: {b.get('context_block','')[:400]}"
        )
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
# FRIENDLY OUTPUT MESSAGES
# ============================================================
_STATUS_MESSAGES = {
    VerificationStatus.PASS: {
        "label": "Đạt yêu cầu",
        "emoji": "✅",
        "description": "Câu trả lời có trích dẫn rõ ràng và khớp với điều luật.",
    },
    VerificationStatus.WARN: {
        "label": "Có cảnh báo",
        "emoji": "⚠️",
        "description": "Câu trả lời đạt một phần nhưng cần xem xét thêm.",
    },
    VerificationStatus.FAIL: {
        "label": "Không đạt",
        "emoji": "❌",
        "description": "Câu trả lời thiếu trích dẫn hoặc không khớp với context.",
    },
}


def _build_status_message(status: VerificationStatus, issues: list[str]) -> str:
    """Tạo message thân thiện cho user dựa trên status + issues."""
    meta = _STATUS_MESSAGES.get(
        status,
        _STATUS_MESSAGES[VerificationStatus.WARN],
    )
    msg = f"{meta['emoji']} {meta['label']}: {meta['description']}"
    if issues:
        msg += "\n\nChi tiết:\n" + "\n".join(f"  • {i}" for i in issues)
    return msg


# ============================================================
# MAIN STEP
# ============================================================
def step_verify_answer(
    verifier_llm,
    question: str,
    answer: str,
    context_blocks: list[dict[str, Any]] | None = None,
    *,
    legal_context: LegalContext | None = None,
    use_llm_judge: bool | None = None,
) -> VerificationResult:
    """
    B7: Symbolic Verification (hybrid rule + LLM-as-Judge) - cải thiện.

    Args:
        verifier_llm:   LLM để chấm (engine.get_verifier_llm()).
        question:       câu hỏi user.
        answer:         câu trả lời từ B6.
        context_blocks: list các dict từ B4 (có citation + context_block).
                        DEPRECATED: dùng `legal_context` nếu có.
        legal_context:  B5 LegalContext (ưu tiên hơn context_blocks nếu được truyền).
                        Cho phép B7 verify claim ↔ citation ↔ evidence ↔ source
                        với traceability chặt hơn.
        use_llm_judge:  nếu None → lấy từ config VERIFIER_LLM_ENABLED.

    Returns:
        VerificationResult (Pydantic) với status, confidence, issues chi tiết.
    """
    # Chuẩn hoá input: ưu tiên legal_context nếu có
    if legal_context is not None:
        context_blocks = [_evidence_to_block(e) for e in legal_context.evidence]
    elif context_blocks is None:
        context_blocks = []

    # 1) Amendments check (P9) - chạy sớm để có data cho rule score
    amendments_check = _check_amendments_compliance(answer, context_blocks)

    # 2) Rule-based (luôn chạy)
    rule = _rule_based_score(answer, context_blocks, amendments_check)
    rule_score = rule["score"]
    issues = list(rule["issues"])

    # 3) LLM-as-Judge (optional)
    should_use_llm = (
        use_llm_judge if use_llm_judge is not None else VERIFIER_LLM_ENABLED
    )
    llm_used = False
    llm_reason: str | None = None
    llm_conf = 0.0
    llm_issues: list[str] = []
    if should_use_llm and verifier_llm is not None:
        judge = _llm_judge(verifier_llm, question, answer, context_blocks)
        llm_used = True
        llm_reason = judge.get("reason") or None
        llm_conf = float(judge.get("confidence", 0.0))
        if judge.get("issues"):
            llm_issues = list(judge["issues"])
            issues.extend([f"[LLM Judge] {i}" for i in llm_issues])

    # 4) Combine score (rule 60% + LLM 40% nếu dùng)
    if llm_used:
        final_score = round(0.6 * rule_score + 0.4 * llm_conf, 3)
    else:
        final_score = rule_score

    # 5) Quyết định status với điều kiện chặt hơn
    # FAIL nếu: thiếu citation HOẶC citation invalid HOẶC không grounded
    if (
        not rule["has_citation"]
        or not rule["cites_valid_doc"]
        or not rule["context_grounded"]
    ):
        status = VerificationStatus.FAIL
    elif (
        final_score >= VERIFICATION_PASS_THRESHOLD
        and rule["amendments_compliant"]
    ):
        status = VerificationStatus.PASS
    elif final_score >= VERIFICATION_PASS_THRESHOLD * 0.5:
        status = VerificationStatus.WARN
    else:
        status = VerificationStatus.FAIL

    # 6) Build friendly message (P13)
    status_message = _build_status_message(status, issues)

    log.info(
        "[B7] verify → status=%s score=%.2f citations=%d/%d grounded=%s amend_ok=%s",
        status.value,
        final_score,
        rule["valid_citation_count"],
        rule["citation_count"],
        rule["context_grounded"],
        rule["amendments_compliant"],
    )

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


# ============================================================
# B5 INTEGRATION: EvidenceItem → context_block dict (back-compat)
# ============================================================
def _evidence_to_block(ev) -> dict[str, Any]:
    """Convert B5 EvidenceItem → dict shape tương thích với rule-based code cũ.

    EvidenceItem đã có field `metadata` chứa nguyên B4 raw block — ta merge
    thêm các field ở top-level (article_number, clause_number, citation) để
    rule-based code cũ (_rule_based_score, _context_has_citation) chạy được
    mà không cần refactor.
    """
    block = dict(ev.metadata or {})
    sid = ev.stable_id
    if sid.article_id and not block.get("article_id"):
        block["article_id"] = sid.article_id
    if sid.clause_id and not block.get("clause_id"):
        block["clause_id"] = sid.clause_id
    if sid.document_id and not block.get("law_document_id"):
        block["law_document_id"] = sid.document_id
    # evidence_id để B7 có thể report lại cho user
    block["evidence_id"] = ev.evidence_id
    return block
