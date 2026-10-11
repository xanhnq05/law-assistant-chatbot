# b2-b5-test — Acceptance test B1→B5

Thư mục này chứa test E2E chạy pipeline **B1 (Orchestrator) → B2 (Cleaner) → B3 (Embedding) → B4 (Retrieval) → B5 (Context Builder)** và in ra `LegalContext` (Pydantic contract — đầu vào chính thức cho B6/B7).

## Files

| File | Mô tả |
|---|---|
| `test_inputs.py` | 25 testcase input + expected result, dựa trên cấu trúc **Nghị định 168/2024/NĐ-CP** (xử phạt VPHC giao thông đường bộ, có hiệu lực từ 01/01/2025). Phân bố: 10 penalty, 4 rule, 3 procedure, 4 list, 2 follow-up, 2 missing-fact. |
| `test_pipeline_to_b5.py` | Test chạy B1→B5, in ra `LegalContext` JSON, assert các field theo `expected`. |

## Cách chạy

### 1. Chuẩn bị ENV
File `backend/.env` phải có sẵn (đã có sẵn trong repo):
- `GROQ_API_KEY`
- `PINECONE_API_KEY`
- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`

### 2. Đảm bảo Nghị định 168 đã được import
Index phải có dữ liệu. Nếu chưa:
```bash
cd backend
python -m uvicorn app.main:app --reload --port 8004  # document-service
# Gọi API admin để trigger parse + import
```

### 3. Chạy pytest
```bash
cd backend/services/rag-service
python -m pytest tests/b2-b5-test/test_pipeline_to_b5.py -v -s
```

### 4. Chạy nhanh 3 testcase đầu (không pytest)
```bash
cd backend/services/rag-service
python tests/b2-b5-test/test_pipeline_to_b5.py
```

## Cấu trúc testcase (test_inputs.py)

```python
@dataclass
class TestCase:
    id: str                       # "T01_penalty_khong_nhuong_duong_xe_may"
    description: str              # Mô tả ngắn
    question: str                 # Câu hỏi user
    history: list[dict] | None    # Conversation history (cho follow-up)
    top_k: int = 5
    expected: ExpectedResult      # Assertions sẽ check
    tags: list[str]               # Để filter
```

`ExpectedResult` chứa các assertion:
- `intent` — `penalty_lookup` / `rule_lookup` / `procedure_lookup` / `general_info` / `list_*` / `missing_fact_query`
- `policy_intensity` / `policy_expansion` / `policy_require_active` / `policy_document_type`
- `resolved_query_contains` — token phải có trong `request.resolved_query`
- `min_evidence` — số evidence tối thiểu
- `must_contain_citation` — vd `["Điều 8"]` phải có trong citation
- `expansion_kinds_seen` — vd `["anchor", "horizontal"]` cả 2 phải có
- `hierarchy_expanded` — True nếu policy.expansion != "none"
- `missing_facts` — vd `["vehicle_type"]`

## Phân bố testcase theo intent

| Intent | Số case | Tags |
|---|---|---|
| penalty_lookup | 10 | `penalty` (xe-may, oto, nong-do-con, mu-bao-hiem,...) |
| rule_lookup | 4 | `rule` (nhuong-duong, toc-do, uu-tien, GPLX) |
| procedure_lookup | 3 | `procedure` (thi-GPLX, dang-ky-xe, khieu-nai) |
| list_chapters | 2 | `list` (structure) |
| list_articles | 1 | `list` (structure) |
| list_clauses | 1 | `list` (structure) |
| follow-up (penalty) | 1 | `followup` (context-aware) |
| follow-up (rule) | 1 | `followup` (context-aware) |
| missing-fact (penalty) | 1 | `missing-fact` (vehicle-type) |
| missing-fact (vague) | 1 | `missing-fact` (vague) |
| **Tổng** | **25** | |

## Cấu trúc Nghị định 168 trên S3 (Supabase)

`{BUCKET_JSON}/D168-2024-ND-CP/structured/law.json`:
```
{
  "schema_version": "1.1.0",
  "document": {
    "id": "D168-2024-ND-CP",
    "number": "168/2024/NĐ-CP",
    "type": "Nghị định",
    "title": "Quy định xử phạt VPHC trong lĩnh vực giao thông đường bộ",
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
        { "id": "D168-2024-ND-CP-A-2", "number": "2", "title": "Nguyên tắc xử phạt", "clauses": [...] }
      ]
    }
  ]
}
```

ID format (theo `legal_structure_parser.py`):
- Chapter: `D168-2024-ND-CP-CH-{ROMAN}` (e.g. `-CH-I`)
- Article: `D168-2024-ND-CP-A-{N}` (e.g. `-A-8`)
- Clause: `D168-2024-ND-CP-A-{N}-K{M}` (e.g. `-A-8-K1`)
- Point: `D168-2024-ND-CP-A-{N}-K{M}-P{LETTER}` (e.g. `-A-8-K1-Pa`)

## Output mong đợi khi chạy

Khi chạy `test_pipeline_to_b5.py`, mỗi testcase sẽ in ra:
```
================================================================================
[LegalContext] intent='penalty_lookup', history_dependent=False
  resolved_query      = 'phạt xe máy không nhường đường'
  retrieval_policy    = {"intensity": "default", "expansion": "siblings", ...}
  evidence_count      = 8
  citation_count      = 8
  hierarchy_docs      = 1
  expansion_executed  = {'kind_counts': {'anchor': 4, 'horizontal': 4}}

  --- Top 3 evidence ---
  [1] EV-001 | clause | active=True | kind=anchor
      citation: ['Nghị định 168/2024/NĐ-CP', 'Chương II', 'Điều 6', 'Khoản 4']
      content: Phạt tiền từ 4.000.000đ đến 6.000.000đ...
================================================================================
```

## Đánh giá kết quả

Mỗi testcase in ra `LegalContext`. Bạn đánh giá:
1. **Intent detect đúng chưa?** (penalty / rule / procedure / list_* / missing_fact)
2. **Retrieval policy build đúng chưa?** (intensity, expansion, require_active, document_type)
3. **History resolve đúng chưa?** (resolved_query có chứa token mong đợi không)
4. **Evidence có chứa citation đúng không?** (vd: "Điều 8" cho câu hỏi về nồng độ cồn)
5. **Expansion có mở rộng đúng không?** (anchor + horizontal cho siblings policy)
6. **Status filter đúng chưa?** (require_active=True → tất cả evidence phải active)
7. **Câu thiếu dữ kiện có trigger missing_facts không?** (vd: "Phạt bao nhiêu khi vượt đèn đỏ?" → vehicle_type)
