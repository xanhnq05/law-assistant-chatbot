"""Bộ testcase input cho rag-service — 25 case dựa trên Nghị định 168/2024/NĐ-CP.

Cấu trúc Nghị định 168/2024/NĐ-CP (Quy định xử phạt VPHC trong lĩnh vực
giao thông đường bộ; có hiệu lực từ 01/01/2025). Tổng cộng 11 Chương,
~69 Điều. Một số điều quan trọng:

  Điều 2  - Nguyên tắc xử phạt
  Điều 3  - Đối tượng bị xử phạt
  Điều 5  - Mức phạt chung (cảnh cáo, phạt tiền, tước GPLX, tịch thu)
  Điều 6  - Nhóm hành vi vi phạm quy tắc giao thông (phần lớn penalty)
  Điều 7  - Vi phạm về tốc độ
  Điều 8  - Vi phạm về nồng độ cồn
  Điều 9  - Không đội mũ bảo hiểm / thắt dây an toàn
  Điều 10 - Vượt đèn đỏ / không chấp hành tín hiệu
  Điều 11 - Đi ngược chiều, lấn làn
  Điều 12 - Dừng đỗ sai quy định
  Điều 24 - Xử phạt người điều khiển xe mô tô, xe gắn máy
  Điều 30 - Xử phạt người điều khiển xe ô tô
  Điều 33 - Tước quyền sử dụng GPLX
  Điều 36 - Hình thức xử phạt bổ sung
  Điều 56 - Xử phạt đối với người đi bộ
  Điều 65 - Điều khoản áp dụng

Cấu trúc JSON trên S3 (Supabase bucket 'json' / 'documents'):
    documents/D168-2024-ND-CP/structured/law.json
    {
      "schema_version": "1.1.0",
      "document": {
        "id": "D168-2024-ND-CP",
        "number": "168/2024/NĐ-CP",
        "type": "Nghị định",
        "title": "Quy định xử phạt vi phạm hành chính trong lĩnh vực giao thông đường bộ",
        "status": "active",
        "date_enacted": "2024-12-26",
        "date_effective": "2025-01-01",
        "issuing_authority": "Chính phủ"
      },
      "chapters": [
        {
          "id": "D168-2024-ND-CP-CH-I",
          "number": "I",
          "title": "CHƯƠNG I - QUY ĐỊNH CHUNG",
          "articles": [
            {
              "id": "D168-2024-ND-CP-A-2",
              "number": "2",
              "title": "Nguyên tắc xử phạt",
              "clauses": [
                {"id": "D168-2024-ND-CP-A-2-K1", "number": "1", "text": "..."},
                ...
              ]
            }
          ]
        }
      ]
    }

Cách dùng:
    from tests.b2-b5-test.test_inputs import TEST_CASES, TestCase
    case = TEST_CASES[0]
    print(case.question, case.expected)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExpectedResult:
    """Kết quả kỳ vọng cho 1 testcase (assertions sẽ check)."""

    # B2 expectations
    intent: str | None = None  # penalty_lookup / rule_lookup / procedure_lookup / general_info / list_chapters / list_articles / list_clauses / missing_fact_query
    resolved_query_contains: list[str] = field(default_factory=list)  # token phải có trong resolved_query
    history_dependent: bool | None = None

    # B2 policy
    policy_intensity: str | None = None  # default / deep / list
    policy_expansion: str | None = None  # none / siblings / parent / neighbors
    policy_require_active: bool | None = None  # True / False / None (=không check)
    policy_document_type: str | None = None  # "Nghị định" / "Luật" / None

    # B4/B5 expectations
    min_evidence: int | None = None  # evidence tối thiểu phải có
    must_contain_citation: list[str] = field(default_factory=list)
    # vd: ["Điều 8"] - phải có ít nhất 1 evidence cite "Điều 8"
    expansion_kinds_seen: list[str] = field(default_factory=list)
    # vd: ["anchor", "horizontal"] - cả 2 kind phải xuất hiện
    hierarchy_expanded: bool | None = None  # True nếu có expansion
    missing_facts: list[str] = field(default_factory=list)
    # vd: ["vehicle_type"]


@dataclass
class TestCase:
    """1 testcase đầu vào."""

    id: str
    description: str
    question: str
    history: list[dict[str, str]] | None = None
    top_k: int = 5
    expected: ExpectedResult = field(default_factory=ExpectedResult)
    tags: list[str] = field(default_factory=list)


# ============================================================
# TEST CASES — 25 case dựa trên Nghị định 168/2024/NĐ-CP
# Chia thành 4 nhóm theo intent:
#   1. Penalty lookup (Điều 6-12, 24, 30) - hỏi mức phạt
#   2. Rule lookup - hỏi quy tắc
#   3. Procedure lookup - hỏi thủ tục
#   4. List_* intents - hỏi cấu trúc
#   5. Follow-up (có history)
#   6. Missing-fact (câu hỏi thiếu dữ kiện)
# ============================================================

TEST_CASES: list[TestCase] = [
    # =============================================================
    # NHÓM 1: PENALTY LOOKUP (~10 case)
    # =============================================================
    TestCase(
        id="T01_penalty_khong_nhuong_duong_xe_may",
        description="Hỏi mức phạt không nhường đường cho xe máy (Điều 6, Khoản 4)",
        question="Phạt bao nhiêu khi đi xe máy không nhường đường cho người đi bộ?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            policy_document_type="Nghị định",
            min_evidence=1,
            must_contain_citation=["Điều 6"],
        ),
        tags=["penalty", "xe-may", "khong-nhuong-duong"],
    ),
    TestCase(
        id="T02_penalty_vuot_den_do",
        description="Hỏi mức phạt vượt đèn đỏ (Điều 10)",
        question="Vượt đèn đỏ bị phạt bao nhiêu tiền?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
            must_contain_citation=["Điều 10"],
        ),
        tags=["penalty", "vuot-den-do"],
    ),
    TestCase(
        id="T03_penalty_oto_chai_dam",
        description="Hỏi mức phạt ô tô chạy quá tốc độ (Điều 7)",
        question="Ô tô chạy quá tốc độ cho phép ở khu vực đông dân cư phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
            must_contain_citation=["Điều 7"],
        ),
        tags=["penalty", "oto", "toc-do"],
    ),
    TestCase(
        id="T04_penalty_nong_do_con",
        description="Hỏi mức phạt uống rượu bia lái xe (Điều 8)",
        question="Lái xe khi nồng độ cồn vượt quá 0.4 phần nghìn bị phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
            must_contain_citation=["Điều 8"],
        ),
        tags=["penalty", "nong-do-con", "ruou-bia"],
    ),
    TestCase(
        id="T05_penalty_khong_mu_bh",
        description="Hỏi mức phạt không đội mũ bảo hiểm (Điều 9, 24)",
        question="Đi xe máy không đội mũ bảo hiểm bị phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["penalty", "mu-bao-hiem"],
    ),
    TestCase(
        id="T06_penalty_di_nguoc_chieu",
        description="Hỏi mức phạt đi ngược chiều (Điều 11)",
        question="Điều khiển xe đi ngược chiều trên đường một chiều bị xử phạt thế nào?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
            must_contain_citation=["Điều 11"],
        ),
        tags=["penalty", "nguoc-chieu"],
    ),
    TestCase(
        id="T07_penalty_dung_do_sai",
        description="Hỏi mức phạt dừng đỗ sai quy định (Điều 12)",
        question="Dừng xe trên cầu, trong hầm bị phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["penalty", "dung-do"],
    ),
    TestCase(
        id="T08_penalty_tuoc_GPLX",
        description="Hỏi về tước GPLX (Điều 33, 36)",
        question="Bị tước giấy phép lái xe tối đa bao nhiêu tháng?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["penalty", "GPLX", "tuoc"],
    ),
    TestCase(
        id="T09_penalty_nguoi_di_bo",
        description="Hỏi mức phạt cho người đi bộ vi phạm (Điều 56)",
        question="Người đi bộ qua đường sai quy định bị phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["penalty", "nguoi-di-bo"],
    ),
    TestCase(
        id="T10_penalty_cho_khach",
        description="Hỏi mức phạt chở quá số người trên xe máy",
        question="Chở 4 người trên xe máy 2 người bị phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["penalty", "cho-khach", "xe-may"],
    ),

    # =============================================================
    # NHÓM 2: RULE LOOKUP (~4 case) - hỏi quy tắc giao thông
    # =============================================================
    TestCase(
        id="T11_rule_quy_tac_nhuong_duong",
        description="Hỏi quy tắc nhường đường (Điều 6 + Luật 36)",
        question="Quy tắc nhường đường tại ngã tư được quy định thế nào?",
        expected=ExpectedResult(
            intent="rule_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            policy_document_type="Luật",
            min_evidence=1,
        ),
        tags=["rule", "nhuong-duong"],
    ),
    TestCase(
        id="T12_rule_toc_do_toi_da",
        description="Hỏi tốc độ tối đa cho phép trong khu vực đô thị (Điều 7)",
        question="Tốc độ tối đa cho phép của ô tô trong khu vực đông dân cư là bao nhiêu km/h?",
        expected=ExpectedResult(
            intent="rule_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["rule", "toc-do", "do-thi"],
    ),
    TestCase(
        id="T13_rule_uu_tien",
        description="Hỏi quy tắc ưu tiên đường giao nhau",
        question="Khi đến ngã tư không có đèn, xe nào được quyền ưu tiên đi trước?",
        expected=ExpectedResult(
            intent="rule_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["rule", "uu-tien", "nga-tu"],
    ),
    TestCase(
        id="T14_rule_gplx_han",
        description="Hỏi thời hạn GPLX (Điều 33)",
        question="Giấy phép lái xe hạng B1 có thời hạn bao lâu?",
        expected=ExpectedResult(
            intent="rule_lookup",
            policy_intensity="default",
            policy_expansion="siblings",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["rule", "GPLX", "thoi-han"],
    ),

    # =============================================================
    # NHÓM 3: PROCEDURE LOOKUP (~3 case) - hỏi thủ tục
    # =============================================================
    TestCase(
        id="T15_procedure_thi_GPLX",
        description="Hỏi thủ tục thi GPLX (Điều 56, Luật)",
        question="Thủ tục thi giấy phép lái xe ô tô hạng B2 gồm những bước nào?",
        expected=ExpectedResult(
            intent="procedure_lookup",
            policy_intensity="default",
            policy_expansion="parent",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["procedure", "GPLX", "thi"],
    ),
    TestCase(
        id="T16_procedure_dang_ky_xe",
        description="Hỏi thủ tục đăng ký xe (Điều 3, 65)",
        question="Đăng ký xe ô tô mới cần những giấy tờ gì?",
        expected=ExpectedResult(
            intent="procedure_lookup",
            policy_intensity="default",
            policy_expansion="parent",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["procedure", "dang-ky-xe"],
    ),
    TestCase(
        id="T17_procedure_khieu_nai",
        description="Hỏi thủ tục khiếu nại quyết định xử phạt (Điều 65)",
        question="Khi bị phạt oan, tôi có quyền khiếu nại ở đâu và trong thời hạn bao lâu?",
        expected=ExpectedResult(
            intent="procedure_lookup",
            policy_intensity="default",
            policy_expansion="parent",
            policy_require_active=True,
            min_evidence=1,
        ),
        tags=["procedure", "khieu-nai"],
    ),

    # =============================================================
    # NHÓM 4: LIST_* INTENTS (~4 case) - hỏi cấu trúc văn bản
    # =============================================================
    TestCase(
        id="T18_list_chapters",
        description="Hỏi cấu trúc: Nghị định 168 có những chương nào?",
        question="Nghị định 168/2024/NĐ-CP có những chương nào?",
        expected=ExpectedResult(
            intent="list_chapters",
            policy_intensity="list",
            policy_expansion="none",
            policy_require_active=False,
            min_evidence=0,  # có thể 0 nếu list chỉ trả Chapter rows
            hierarchy_expanded=False,
        ),
        tags=["list", "structure", "chapters"],
    ),
    TestCase(
        id="T19_list_articles",
        description="Hỏi cấu trúc: Chương II có những điều nào?",
        question="Chương II của Nghị định 168 có những điều luật nào?",
        expected=ExpectedResult(
            intent="list_articles",
            policy_intensity="list",
            policy_expansion="none",
            policy_require_active=False,
            min_evidence=0,
            hierarchy_expanded=False,
        ),
        tags=["list", "structure", "articles"],
    ),
    TestCase(
        id="T20_list_clauses",
        description="Hỏi cấu trúc: Điều 8 có những khoản nào?",
        question="Điều 8 về nồng độ cồn có những khoản nào?",
        expected=ExpectedResult(
            intent="list_clauses",
            policy_intensity="list",
            policy_expansion="none",
            policy_require_active=False,
            min_evidence=0,
            hierarchy_expanded=False,
        ),
        tags=["list", "structure", "clauses"],
    ),
    TestCase(
        id="T21_list_overview",
        description="Hỏi tổng quan văn bản",
        question="Tổng quan Nghị định 168 có những nội dung gì?",
        expected=ExpectedResult(
            intent="list_chapters",
            policy_intensity="list",
            policy_expansion="none",
            policy_require_active=False,
            min_evidence=0,
        ),
        tags=["list", "overview"],
    ),

    # =============================================================
    # NHÓM 5: FOLLOW-UP (có history) - 2 case
    # =============================================================
    TestCase(
        id="T22_followup_xe_may_to_oto",
        description="Follow-up: đã hỏi xe máy không nhường đường, giờ hỏi ô tô",
        question="Còn ô tô thì sao?",
        history=[
            {"role": "user", "content": "Phạt bao nhiêu khi đi xe máy không nhường đường?"},
            {"role": "assistant", "content": "Theo Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4: phạt 4-6 triệu đồng đối với xe mô tô, xe gắn máy."},
        ],
        expected=ExpectedResult(
            intent="penalty_lookup",
            history_dependent=True,
            resolved_query_contains=["ô tô", "không nhường đường"],
            policy_intensity="default",
            policy_expansion="neighbors",  # follow-up → boost lên neighbors
            min_evidence=1,
        ),
        tags=["followup", "context-aware"],
    ),
    TestCase(
        id="T23_followup_do_thi_to_ngoai",
        description="Follow-up: đã hỏi tốc độ đô thị, giờ hỏi ngoại thành",
        question="Còn ngoài khu đô thị thì sao?",
        history=[
            {"role": "user", "content": "Tốc độ tối đa của ô tô trong khu đô thị là bao nhiêu?"},
            {"role": "assistant", "content": "Trong khu đô thị, ô tô được chạy tối đa 50 km/h (theo Điều 7 Nghị định 168)."},
        ],
        expected=ExpectedResult(
            intent="rule_lookup",
            history_dependent=True,
            resolved_query_contains=["ngoài", "khu đô thị", "tốc độ"],
            min_evidence=1,
        ),
        tags=["followup", "context-aware", "ngoai-thanh"],
    ),

    # =============================================================
    # NHÓM 6: MISSING-FACT (câu hỏi thiếu dữ kiện) - 2 case
    # =============================================================
    TestCase(
        id="T24_missing_vehicle_type",
        description="Câu phạt mà không rõ xe gì → trigger missing_fact_query",
        question="Phạt bao nhiêu khi vượt đèn đỏ?",
        expected=ExpectedResult(
            intent="penalty_lookup",
            policy_intensity="default",
            policy_expansion="neighbors",  # missing_facts → boost lên neighbors
            missing_facts=["vehicle_type"],
            min_evidence=1,
        ),
        tags=["missing-fact", "vehicle-type"],
    ),
    TestCase(
        id="T25_missing_generic_penalty",
        description="Câu phạt quá ngắn, không rõ hành vi cụ thể",
        question="Vi phạm giao thông bị phạt bao nhiêu?",
        expected=ExpectedResult(
            intent="general_info",  # hoặc penalty_lookup tùy LLM
            policy_expansion="neighbors",  # có thể do missing_facts
            min_evidence=1,
        ),
        tags=["missing-fact", "vague"],
    ),
]


# ============================================================
# Convenience: filter testcase theo tag
# ============================================================
def get_cases_by_tag(tag: str) -> list[TestCase]:
    """Lấy các testcase có chứa tag."""
    return [c for c in TEST_CASES if tag in c.tags]


def get_cases_by_intent(intent: str) -> list[TestCase]:
    """Lấy các testcase có intent khớp."""
    return [c for c in TEST_CASES if c.expected.intent == intent]


# ============================================================
# In summary khi chạy trực tiếp
# ============================================================
if __name__ == "__main__":
    print(f"Tổng cộng: {len(TEST_CASES)} testcase\n")
    by_intent: dict[str, int] = {}
    for c in TEST_CASES:
        intent = c.expected.intent or "(unknown)"
        by_intent[intent] = by_intent.get(intent, 0) + 1
    print("Phân bố theo intent:")
    for intent, count in sorted(by_intent.items(), key=lambda x: -x[1]):
        print(f"  {intent:30s}: {count} case")
    print("\nDanh sách testcase:")
    for c in TEST_CASES:
        print(f"  [{c.id}] {c.description[:80]}")
        print(f"      Q: {c.question[:100]}")
