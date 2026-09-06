"""
B2 - Query Cleaner.

Input:  raw question từ user (có thể có lỗi chính tả, filler,..)
Output: dict với cleaned_query, legal_domain, key_legal_terms, intent.

Chiến lược:
  - Dùng LLM (Groq) để tái cấu trúc + trích structured info.
  - Nếu LLM fail (timeout, parse error) → fallback rule-based đơn giản.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.rag.prompts.cleaner import SYSTEM_QUERY_CLEANER


# ============================================================
# FILLER WORDS (Tiếng Việt)
# ============================================================
_FILLER_PATTERN = re.compile(
    r"\b(cho mình hỏi|cho tôi hỏi|xin hỏi|cho hỏi|mình hỏi|"
    r"vậy ạ|vậy nhỉ|ạ|nhỉ|thế|nhé|xin được hỏi)\b",
    flags=re.IGNORECASE,
)


def _rule_based_clean(question: str) -> str:
    """Fallback: chỉ remove filler + normalize whitespace."""
    cleaned = _FILLER_PATTERN.sub("", question)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or question.strip()


def _detect_intent_heuristic(question: str) -> str:
    """Heuristic intent detection khi LLM không khả dụng."""
    q = question.lower()
    if any(kw in q for kw in ["phạt bao nhiêu", "mức phạt", "tiền phạt", "xử phạt"]):
        return "penalty_lookup"
    if any(kw in q for kw in ["quy tắc", "được phép", "không được", "có được"]):
        return "rule_lookup"
    if any(kw in q for kw in ["thủ tục", "đăng ký", "thi", "cấp", "đổi"]):
        return "procedure_lookup"
    return "general_info"


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


def step_clean_query(llm, question: str) -> dict[str, Any]:
    """
    B2: làm sạch + tái cấu trúc câu hỏi.

    Returns:
        {
            "cleaned_query": str,
            "legal_domain": str,
            "key_legal_terms": list[str],
            "intent": str,
            "original": str,
        }
    """
    fallback = {
        "cleaned_query": _rule_based_clean(question),
        "legal_domain": "giao thông đường bộ",
        "key_legal_terms": [],
        "intent": _detect_intent_heuristic(question),
        "original": question,
    }

    if llm is None:
        return fallback

    try:
        raw = llm.invoke([
            SystemMessage(content=SYSTEM_QUERY_CLEANER),
            HumanMessage(content=f"Câu hỏi của người dùng: {question}"),
        ])
        parsed = _parse_llm_json(raw.content)
        if not parsed:
            return fallback

        cleaned_query = parsed.get("cleaned_query") or fallback["cleaned_query"]
        return {
            "cleaned_query": str(cleaned_query).strip() or question.strip(),
            "legal_domain": str(parsed.get("legal_domain") or "giao thông đường bộ"),
            "key_legal_terms": list(parsed.get("key_legal_terms") or []),
            "intent": str(parsed.get("intent") or "general_info"),
            "original": question,
        }
    except Exception:
        return fallback
