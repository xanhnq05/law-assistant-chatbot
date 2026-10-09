"""
B2 - Query Cleaner (v2 — history-aware + retrieval policy decision).

Input:  raw question từ user (có thể có lỗi chính tả, filler,..)
        + optional conversation history (cho follow-up resolution).
Output: dict với:
  - cleaned_query, legal_domain, key_legal_terms, intent (cũ, back-compat)
  - resolved_query, history_dependent (MỚI)
  - expansion_hint, missing_facts (MỚI)
  - retrieval_policy (MỚI - contract chính thức xuống B4)

Chiến lược:
  - Dùng LLM (Groq) để tái cấu trúc + trích structured info.
  - Nếu LLM fail → fallback rule-based (đơn giản nhưng đầy đủ field).
  - Với follow-up (câu có tham chiếu + có history) → gọi LLM resolve trước,
    sau đó mới chạy SYSTEM_QUERY_CLEANER trên câu đã resolved.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.prompts.cleaner import (
    SYSTEM_FOLLOWUP_RESOLVER,
    SYSTEM_QUERY_CLEANER,
)
from app.rag.steps.policy import (
    build_retrieval_policy,
    detect_intent_heuristic,
    detect_missing_facts,
)


# ============================================================
# FILLER WORDS (Tiếng Việt)
# ============================================================
# Pattern: dùng lookbehind/lookahead thay vì \b (vì \b không hoạt động tốt với
# ký tự có dấu tiếng Việt như ạ, ờ, ể...).
# Token phải đứng riêng — có dấu ngăn cách (space/comma/period/?/!) ở 2 bên.
_FILLER_PATTERN = re.compile(
    r"(?:^|(?<=[^a-zA-ZÀ-ỹà-ỹ0-9_]))("
    r"cho mình hỏi|cho tôi hỏi|xin hỏi|cho hỏi|mình hỏi|"
    r"vậy ạ|vậy nhỉ|ạ|nhỉ|thế|nhé|xin được hỏi"
    r")(?:$|(?=[^a-zA-ZÀ-ỹà-ỹ0-9_]))",
    flags=re.IGNORECASE,
)

# Reference markers - câu có khả năng là follow-up
_REFERENCE_PATTERN = re.compile(
    r"\b(còn|vậy|thế|nó|họ|như vậy|đó|như thế|như trên|như cũ|vẫn)\b",
    flags=re.IGNORECASE,
)


def _rule_based_clean(question: str) -> str:
    """Fallback: chỉ remove filler + normalize whitespace."""
    cleaned = _FILLER_PATTERN.sub("", question)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or question.strip()


def _has_reference_marker(question: str) -> bool:
    """Check nhanh câu có dấu hiệu tham chiếu (heuristic)."""
    if not question:
        return False
    return bool(_REFERENCE_PATTERN.search(question))


def _normalize_history(
    history: list[dict[str, str]] | None,
) -> str:
    """Convert history list → 1 chuỗi compact cho LLM."""
    if not history:
        return ""
    pairs: list[str] = []
    # chỉ lấy 3 cặp cuối
    recent = history[-6:]  # 3 pairs * 2 msg
    pair_buf: list[dict[str, str]] = []
    for msg in recent:
        pair_buf.append(msg)
        if len(pair_buf) == 2:
            user_msg = pair_buf[0].get("content", "")
            asst_msg = pair_buf[1].get("content", "")
            pairs.append(
                f"  Người dùng: {user_msg[:300]}\n"
                f"  Trợ lý: {asst_msg[:300]}"
            )
            pair_buf = []
    return "\n".join(reversed(pairs))


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    """Best-effort parse JSON từ LLM output (handle ```json fence)."""
    content = content.strip()
    if content.startswith("```"):
        # Tách block ``` ... ``` và bỏ ngôn ngữ fence
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


# ============================================================
# STEP: RESOLVE FOLLOW-UP (MỚI)
# ============================================================
def _resolve_followup(
    llm,
    question: str,
    history: list[dict[str, str]] | None,
) -> dict[str, Any]:
    """
    B2 substep: resolve câu hỏi follow-up dựa trên history.

    Returns:
        {
            "resolved_query": str,
            "history_dependent": bool,
            "context_summary": str,
        }
    """
    fallback = {
        "resolved_query": _rule_based_clean(question),
        "history_dependent": False,
        "context_summary": "",
    }
    if llm is None or not history:
        return fallback

    try:
        history_str = _normalize_history(history)
        if not history_str:
            return fallback

        user_msg = (
            f"conversation_history:\n{history_str}\n\n"
            f"current_question: {question}\n\n"
            f"Trả về JSON."
        )
        raw = llm.invoke([
            SystemMessage(content=SYSTEM_FOLLOWUP_RESOLVER),
            HumanMessage(content=user_msg),
        ])
        parsed = _parse_llm_json(raw.content or "")
        if not parsed:
            return fallback

        resolved = str(parsed.get("resolved_query") or "").strip()
        if not resolved:
            return fallback

        return {
            "resolved_query": resolved,
            "history_dependent": bool(parsed.get("history_dependent", True)),
            "context_summary": str(parsed.get("context_summary") or ""),
        }
    except Exception:
        return fallback


# ============================================================
# STEP: MAIN QUERY CLEANER (back-compat + mở rộng)
# ============================================================
def step_clean_query(
    llm,
    question: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    B2 (v2): làm sạch + tái cấu trúc câu hỏi, có history-aware resolve và
    build retrieval policy cho B4.

    Args:
        llm:       LLM instance (Groq) — có thể None sẽ fallback rule-based.
        question:  raw user question.
        history:   optional conversation history (max 6 msg = 3 pairs).
                   Nếu có + câu có reference marker → sẽ LLM-resolve trước.

    Returns:
        dict với các field cũ (back-compat) + field mới:
          - cleaned_query, legal_domain, key_legal_terms, intent, original (cũ)
          - resolved_query, history_dependent (MỚI)
          - expansion_hint, missing_facts (MỚI)
          - retrieval_policy (MỚI - contract B2→B4)
    """
    # ===== Step 1: resolve follow-up nếu có reference + history =====
    resolution = _resolve_followup(llm, question, history)
    resolved_query = resolution["resolved_query"]
    history_dependent = resolution["history_dependent"]

    # Nếu không cần resolve, fallback cleaned_query = rule-based clean của câu gốc
    if not history_dependent and not resolved_query:
        resolved_query = _rule_based_clean(question)

    # ===== Step 2: gọi LLM với SYSTEM_QUERY_CLEANER trên câu đã resolved =====
    rule_fallback = {
        "cleaned_query": resolved_query,
        "legal_domain": "giao thông đường bộ",
        "key_legal_terms": [],
        "intent": detect_intent_heuristic(question),
        "expansion_hint": "default",
        "missing_facts": [],
    }

    if llm is None:
        cleaned = rule_fallback
    else:
        try:
            raw = llm.invoke([
                SystemMessage(content=SYSTEM_QUERY_CLEANER),
                HumanMessage(content=f"Câu hỏi của người dùng: {resolved_query}"),
            ])
            parsed = _parse_llm_json(raw.content or "")
            if not parsed:
                cleaned = rule_fallback
            else:
                cleaned = {
                    "cleaned_query": str(parsed.get("cleaned_query") or resolved_query).strip()
                    or resolved_query,
                    "legal_domain": str(parsed.get("legal_domain") or "giao thông đường bộ"),
                    "key_legal_terms": list(parsed.get("key_legal_terms") or []),
                    "intent": str(parsed.get("intent") or "general_info"),
                    "expansion_hint": str(parsed.get("expansion_hint") or "default"),
                    "missing_facts": list(parsed.get("missing_facts") or []),
                }
        except Exception:
            cleaned = rule_fallback

    # ===== Step 3: bổ sung heuristic nếu LLM không trả =====
    key_terms = cleaned["key_legal_terms"]
    intent = cleaned["intent"]
    if not key_terms:
        key_terms = [w for w in resolved_query.split() if len(w) >= 3][:5]
    if not intent or intent == "general_info":
        # Re-detect intent với heuristic mở rộng
        heuristic_intent = detect_intent_heuristic(question)
        if heuristic_intent != "general_info":
            intent = heuristic_intent

    # Detect missing_facts bằng heuristic (nếu LLM không trả)
    missing = cleaned.get("missing_facts") or []
    if not missing:
        missing = detect_missing_facts(cleaned["cleaned_query"], intent, key_terms)

    # ===== Step 4: build retrieval policy =====
    policy = build_retrieval_policy(
        intent=intent,
        missing_facts=missing,
        expansion_hint=cleaned.get("expansion_hint", "default"),
    )

    # Nếu câu đã được resolve mà ban đầu là reference → flag "neighbors" để
    # B4 expand để chắc chắn không thiếu context (an toàn cho follow-up).
    if history_dependent and policy["expansion"] == "siblings":
        policy["expansion"] = "neighbors"

    # ===== Step 5: trả về full dict =====
    return {
        # ----- back-compat fields (luôn có) -----
        "cleaned_query": cleaned["cleaned_query"],
        "legal_domain": cleaned["legal_domain"],
        "key_legal_terms": key_terms,
        "intent": intent,
        "original": question,
        # ----- new fields -----
        "resolved_query": resolved_query or cleaned["cleaned_query"],
        "history_dependent": history_dependent,
        "expansion_hint": cleaned.get("expansion_hint", "default"),
        "missing_facts": missing,
        "retrieval_policy": policy,
        # ----- debug/observability -----
        "context_summary": resolution.get("context_summary", ""),
    }
