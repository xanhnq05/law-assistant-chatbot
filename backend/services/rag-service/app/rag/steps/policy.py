"""
B2 - Retrieval Policy Decision.

Quyết định CHÍNH SÁCH truy xuất cho B4 dựa trên:
  - intent (penalty / rule / procedure / list_chapters / ...)
  - missing_facts (gợi ý từ B2 rằng user câu hỏi đang thiếu dữ kiện)
  - expansion_hint (broad / focused / list_view)

Theo PDF "tổng hợp sửa đổi các bước":
  - Rule mặc định:
      UP: 1 cấp; DOWN: 1 cấp; HORIZONTAL: mở rộng Khoản cùng Điều
  - Query cấu trúc/danh sách có thể override:
      Hỏi các chương → Document → Chapter
      Hỏi các điều trong chương → Chapter → Article
      Hỏi các khoản trong điều → Article → Clause
  - Không deep traversal mặc định

Đây là **default policy, không phải luật cứng**: B4 có thể override nếu có tín hiệu mạnh hơn.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

log = logging.getLogger("rag-service")


# ============================================================
# TYPE ALIASES (cũng dùng cho test/docstring)
# ============================================================
Intent = Literal[
    "penalty_lookup",
    "rule_lookup",
    "procedure_lookup",
    "general_info",
    "list_chapters",
    "list_articles",
    "list_clauses",
    "missing_fact_query",
]
Intensity = Literal["default", "deep", "list"]
Expansion = Literal["none", "siblings", "parent", "neighbors"]


# ============================================================
# INTENT DETECTION (heuristic fallback - mở rộng so với bản cũ)
# ============================================================
_HEURISTIC_INTENT_PATTERNS: list[tuple[Intent, tuple[str, ...]]] = [
    # List intents (ưu tiên cao — match phrase có "những ... nào")
    (
        "list_clauses",
        (
            "có những khoản nào", "gồm những khoản", "liệt kê các khoản",
            "các khoản của điều", "khoản nào của điều",
        ),
    ),
    (
        "list_articles",
        (
            "có những điều nào", "gồm những điều", "liệt kê các điều",
            "các điều của chương", "điều nào trong chương",
        ),
    ),
    (
        "list_chapters",
        (
            "có những chương nào", "gồm những chương", "liệt kê các chương",
            "cấu trúc văn bản", "tổng quan văn bản",
        ),
    ),
    # Lookup intents (giữ từ bản gốc)
    (
        "penalty_lookup",
        (
            "phạt bao nhiêu", "mức phạt", "tiền phạt", "xử phạt", "phạt tiền",
        ),
    ),
    (
        "rule_lookup",
        (
            "quy tắc", "được phép", "không được", "có được phép",
            "có quyền", "nghĩa vụ",
        ),
    ),
    (
        "procedure_lookup",
        (
            "thủ tục", "đăng ký", "thi ", "cấp ", "đổi ", "làm thế nào để",
            "trình tự",
        ),
    ),
]


def detect_intent_heuristic(question: str) -> Intent:
    """
    Heuristic intent detection (khi LLM không khả dụng).
    Mở rộng: thêm list_chapters / list_articles / list_clauses.
    """
    q = question.lower().strip()
    if not q:
        return "general_info"
    # Match theo thứ tự ưu tiên (list_* trước, lookup sau)
    for intent, keywords in _HEURISTIC_INTENT_PATTERNS:
        if any(kw in q for kw in keywords):
            return intent
    return "general_info"


# ============================================================
# MISSING FACT DETECTION (mới)
# ============================================================
_MISSING_FACT_HINTS: dict[str, tuple[str, ...]] = {
    # vehicle_type: câu hỏi phạt mà thiếu "xe gì"
    "vehicle_type": (
        # các cụm từ mơ hồ không chỉ rõ xe gì
        "đi như thế nào", "vi phạm", "lỗi", "phạt bao nhiêu", "mức phạt",
    ),
    # document_scope: "nghị định nào quy định", "văn bản nào"
    "document_scope": (
        "văn bản nào", "nghị định nào", "luật nào", "thông tư nào",
    ),
    # specific_article: câu chỉ rõ điều luật
    # (helper - thường KHÔNG bị missing)
    "time_period": (
        "từ năm", "trước năm", "sau năm", "hiện nay", "hiện tại",
    ),
}


def detect_missing_facts(
    cleaned_query: str,
    intent: Intent,
    key_terms: list[str],
) -> list[str]:
    """
    Phát hiện các dữ kiện có thể thiếu trong câu hỏi.

    Heuristic:
      - penalty_lookup mà không có vehicle/document_scope → missing
      - list_* intent không trigger missing (user muốn list tổng quát)
      - Các intent khác: check keyword mơ hồ

    Returns:
        list[str]: danh sách tên fact bị missing (vd ["vehicle_type", "document_scope"]).
                   Empty list = câu hỏi đầy đủ dữ kiện.
    """
    missing: list[str] = []
    q = cleaned_query.lower()

    # List intents không tính missing - user muốn overview
    if intent.startswith("list_"):
        return missing

    # Penalty lookup thường cần vehicle_type rõ ràng
    if intent == "penalty_lookup":
        has_vehicle = any(
            v in q
            for v in ("xe máy", "xe ô tô", "ô tô", "mô tô", "xe đạp", "xe tải", "container")
        )
        if not has_vehicle:
            missing.append("vehicle_type")

    # Các intent khác: detect chung
    for fact_name, hints in _MISSING_FACT_HINTS.items():
        if fact_name == "vehicle_type":
            continue  # đã xử lý ở trên
        if any(hint in q for hint in hints) and len(key_terms) <= 1:
            missing.append(fact_name)

    return missing


# ============================================================
# POLICY BUILDER (chính)
# ============================================================
_INTENSITY_BY_INTENT: dict[Intent, Intensity] = {
    "penalty_lookup": "default",
    "rule_lookup": "default",
    "procedure_lookup": "default",
    "general_info": "default",
    "list_chapters": "list",
    "list_articles": "list",
    "list_clauses": "list",
    "missing_fact_query": "deep",
}


_EXPANSION_BY_INTENT: dict[Intent, Expansion] = {
    "penalty_lookup": "siblings",    # mặc định: lấy các Khoản cùng Điều
    "rule_lookup": "siblings",
    "procedure_lookup": "parent",      # thủ tục thường nằm ở level cao hơn
    "general_info": "siblings",
    "list_chapters": "none",          # list, không mở rộng
    "list_articles": "none",
    "list_clauses": "none",
    "missing_fact_query": "neighbors", # thiếu dữ kiện → mở rộng đủ hướng
}


_MAX_EVIDENCE_BY_INTENT: dict[Intent, int] = {
    "penalty_lookup": 10,
    "rule_lookup": 10,
    "procedure_lookup": 8,
    "general_info": 10,
    "list_chapters": 5,
    "list_articles": 20,
    "list_clauses": 20,
    "missing_fact_query": 15,
}


_FILTERS_BY_INTENT: dict[Intent, dict[str, Any]] = {
    # Penalty thường nằm ở Nghị định; cần filter active
    "penalty_lookup": {
        "require_active": True,
        "document_type": "Nghị định",
    },
    # Rule thường ở Luật; cần active
    "rule_lookup": {
        "require_active": True,
        "document_type": "Luật",
    },
    # Procedure có thể ở Luật hoặc Nghị định; cần active
    "procedure_lookup": {
        "require_active": True,
        "document_type": None,
    },
    # List overview → không filter active (xem cả structure)
    "list_chapters": {
        "require_active": False,
        "document_type": None,
    },
    "list_articles": {
        "require_active": False,
        "document_type": None,
    },
    "list_clauses": {
        "require_active": False,
        "document_type": None,
    },
    # Thiếu fact → không filter (lấy rộng, để B7 + user tự chọn)
    "missing_fact_query": {
        "require_active": False,
        "document_type": None,
    },
    "general_info": {
        "require_active": False,
        "document_type": None,
    },
}


def build_retrieval_policy(
    intent: str,
    *,
    missing_facts: list[str] | None = None,
    expansion_hint: str = "default",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build retrieval policy cho B4.

    Args:
        intent:           intent từ B2
        missing_facts:    list fact bị thiếu (nếu không rỗng → boost expansion)
        expansion_hint:   "broad" | "focused" | "list_view" (gợi ý từ B2)
        overrides:        dict cho phép override 1 phần policy
                          (vd: {"intensity": "deep"} nếu LLM tự tin).

    Returns:
        dict policy:
            {
                "intensity": "default"|"deep"|"list",
                "expansion": "none"|"siblings"|"parent"|"neighbors",
                "max_evidence_hint": int,
                "filters": {"require_active": bool, "document_type": str|None},
                "missing_facts": list[str],
                "source_intent": str,           # để debug
            }
    """
    # Validate intent — fallback về general_info nếu không hợp lệ
    valid_intents = set(_INTENSITY_BY_INTENT.keys())
    safe_intent: Intent = intent if intent in valid_intents else "general_info"

    policy: dict[str, Any] = {
        "intensity": _INTENSITY_BY_INTENT[safe_intent],
        "expansion": _EXPANSION_BY_INTENT[safe_intent],
        "max_evidence_hint": _MAX_EVIDENCE_BY_INTENT[safe_intent],
        "filters": dict(_FILTERS_BY_INTENT[safe_intent]),
        "missing_facts": list(missing_facts or []),
        "source_intent": safe_intent,
    }

    # Nếu có missing_facts → boost lên neighbors để lấy đủ context
    if policy["missing_facts"] and safe_intent != "missing_fact_query":
        if policy["expansion"] == "siblings":
            policy["expansion"] = "neighbors"

    # Áp dụng expansion_hint (nếu khác default)
    if expansion_hint == "broad" and policy["expansion"] == "siblings":
        policy["expansion"] = "neighbors"
    elif expansion_hint == "list_view" and policy["intensity"] != "list":
        policy["expansion"] = "none"
        policy["intensity"] = "list"
    elif expansion_hint == "focused" and policy["expansion"] == "neighbors":
        policy["expansion"] = "siblings"

    # Áp dụng overrides (nếu có)
    if overrides:
        for key in ("intensity", "expansion", "max_evidence_hint"):
            if key in overrides and overrides[key] is not None:
                policy[key] = overrides[key]
        if "filters" in overrides and isinstance(overrides["filters"], dict):
            policy["filters"].update(overrides["filters"])

    return policy


def merge_policy_with_env(
    policy: dict[str, Any],
    *,
    default_max_evidence: int | None = None,
    default_intensity: str | None = None,
) -> dict[str, Any]:
    """
    Áp dụng ENV default (nếu có) làm fallback an toàn — không bao giờ downscale
    `max_evidence_hint` xuống dưới ENV default.
    """
    if default_max_evidence is not None:
        policy["max_evidence_hint"] = max(
            int(policy.get("max_evidence_hint", 10)),
            int(default_max_evidence),
        )
    return policy
