# Plan sửa đổi B2 & B4 — Cải thiện truy xuất theo dạng câu hỏi, tránh thiếu dữ kiện

> **Owner**: dev1 (B2 + B4)
> **Handoff cho dev2**: B5 (đã được chuẩn hóa làm contract) → B6/B7/Follow-up Question Generator
> **Nguồn đặc tả**: `tổng hợp sửa đổi các bước.pdf` (đã thống nhất 2 phe)
> **Phạm vi**: CHỈ sửa B2 (cleaner) + B4 (retrieval). KHÔNG đụng B6/B7/Follow-up.
> **Nguyên tắc**: B5 là contract chính thức — B2 + B4 chỉ cần làm sao để `LegalContext.evidence` + metadata mới đủ tín hiệu cho dev2 dùng.

---

## 0. Tóm tắt vấn đề hiện tại

### B2 — `app/rag/steps/cleaner.py`
- **Chỉ trả 4 trường**: `cleaned_query`, `legal_domain`, `key_legal_terms`, `intent`.
- **Heuristic intent thiếu tinh tế**: chỉ check vài keyword đơn lẻ → nhiều câu dài/multi-intent rơi vào `general_info`.
- **Không dùng conversation history**: tham số `history` đã có ở `ChatRequest` nhưng `step_clean_query` BỎ QUA → câu "Còn ô tô thì sao?" vẫn đi qua retrieval gốc.
- **Không suy luận "câu hỏi đang thiếu dữ kiện gì"** để báo cho B4 mở rộng policy.

### B4 — `app/rag/steps/retrieval.py`
- **Có soft intent boost** (tốt).
- **Có reranker hook** (đang tắt mặc định — chấp nhận được).
- **CHƯA có Context Expansion**: rule UP/DOWN/HORIZONTAL theo cấu trúc pháp luật **chưa hề tồn tại** trong code.
- **CHƯA có status/version filter**: truy vấn document hết hạn/bãi bỏ vẫn được đưa vào evidence.
- **CHƯA có Policy decision** để biết câu này nên "deep" hay "broad".

### B5 — `app/rag/steps/context_builder.py` + `app/rag/schemas/legal_context.py`
- ĐÃ CÓ `LegalContext` schema với `evidence[]`, `hierarchy`, `citations[]`, `request.retrieval_query`.
- **Mở rộng cần làm**:
  1. `RequestInfo` thêm `retrieval_policy` (intensity + direction + expansion) để dev2 không cần đoán.
  2. `EvidenceItem` thêm `is_active`, `effective_from`, `effective_to`, `is_current_version` để B7 + Follow-up đánh giá.
  3. `EvidenceItem.amendments` đã có nhưng parser cần trích `direction`, `note` rõ ràng hơn.

---

## 1. Mục tiêu của đợt sửa đổi này

| # | Mục tiêu | Tiêu chí nghiệm thu |
|---|---|---|
| O1 | B2 hiểu được câu hỏi follow-up dựa trên hội thoại | `cleaned["resolved_query"]` chứa câu đầy đủ sau khi resolve tham chiếu |
| O2 | B2 suy luận được "câu hỏi đang thiếu dữ kiện gì" | Có 4 intent mở rộng: `list_chapters` / `list_articles` / `list_clauses` / `general_info_with_missing_facts` |
| O3 | B2 build được **retrieval policy** (intensity + direction + expansion) | Trả về dict `retrieval_policy` cho B4 |
| O4 | B4 mặc định lấy đúng 1 node, sau đó mở rộng theo policy | `evidence` cuối cùng phải chứa cả anchor node + các node expanded |
| O5 | B4 lọc được văn bản hết hiệu lực | Document status `expired`/`repealed` KHÔNG lọt vào evidence, trừ khi có quan hệ `AMENDED_BY` đến bản active |
| O6 | B5 đóng gói chuẩn để dev2 không phải đoán | `LegalContext` có `retrieval_policy`, mỗi evidence có status/active/effective_*, hierarchy có marker cho "phạm vi đã mở rộng" |
| O7 | Tất cả đều **backward-compat** | Pipeline hiện tại chạy được với input cũ; không vỡ test đang pass |

---

## 2. Phạm vi kỹ thuật — File sẽ sửa (và file KHÔNG đụng)

### Dev1 sửa
- `app/rag/prompts/cleaner.py` — nâng cấp system prompt.
- `app/rag/steps/cleaner.py` — parse thêm field, tích hợp history.
- `app/rag/steps/embedding.py` — embed enriched query (nếu B3 mới có key phụ).
- `app/rag/steps/retrieval.py` — thêm policy execution, expansion, status filter.
- `app/rag/context.py` — thêm helper build Cypher cho expansion (UP/DOWN/HORIZONTAL).
- `app/rag/steps/context_builder.py` — wrap policy vào `RequestInfo`.
- `app/rag/schemas/legal_context.py` — mở rộng `RequestInfo` + `EvidenceItem` (chỉ thêm field, không xóa).
- `app/core/config.py` — thêm ENV mới (`DEFAULT_EXPANSION_*`).
- `tests/test_cleaner.py`, `tests/test_retrieval.py`, `tests/test_context_builder.py` — bổ sung case mới.

### KHÔNG đụng (giao cho dev2)
- `app/rag/prompts/generator.py`, `app/rag/steps/generator.py` (B6)
- `app/rag/prompts/verifier.py`, `app/rag/steps/verification.py` (B7)
- Bất cứ thứ gì liên quan Follow-up Question Generator
- `app/api/routes/chat.py`, `app/core/models.py` (trừ khi cần thêm field optional)

### Module mới (nếu cần)
- `app/rag/steps/policy.py` — nơi tập trung build `RetrievalPolicy` từ B2 output.
- `app/rag/steps/expansion.py` — nơi tập trung logic expansion (UP/DOWN/HORIZONTAL) + chạy Cypher.

---

## 3. Thiết kế chi tiết — B2

### 3.1. Schema output mới của B2

```python
# Trước (hiện tại)
{
    "cleaned_query": str,
    "legal_domain": str,
    "key_legal_terms": list[str],
    "intent": "penalty_lookup" | "rule_lookup" | "procedure_lookup" | "general_info",
    "original": str,
}

# Sau (backward-compat — luôn có field cũ + thêm field mới)
{
    # ===== Field cũ (KHÔNG xóa) =====
    "cleaned_query": str,                 # alias = resolved_query
    "legal_domain": str,
    "key_legal_terms": list[str],
    "intent": str,                        # mở rộng thêm giá trị mới (xem 3.2)
    "original": str,

    # ===== Field mới =====
    "resolved_query": str,                # câu hỏi sau khi resolve follow-up từ history
    "history_dependent": bool,            # True nếu câu cần history mới hiểu được
    "expansion_hint": str,                # "broad" | "focused" | "list_view"
    "missing_facts": list[str],           # vd ["vehicle_type", "specific_article"]
    "retrieval_policy": {                 # đây là contract chính thức xuống B4
        "intensity": "default" | "deep" | "list",
        "expansion": "none" | "siblings" | "parent" | "neighbors",
        "max_evidence_hint": int,         # gợi ý cap cho B4 (B4 vẫn dùng config cũ nếu None)
        "filters": {
            "require_active": bool,       # True nếu user hỏi về hiệu lực hiện tại
            "document_type": str | None,  # gợi ý "Nghị định" / "Luật" / None
        },
    },
}
```

### 3.2. Intent mở rộng

| Intent cũ | Intent mới (giữ tương thích) | Ý nghĩa |
|---|---|---|
| `penalty_lookup` | `penalty_lookup` | Hỏi mức phạt (giữ nguyên) |
| `rule_lookup` | `rule_lookup` | Hỏi quy tắc (giữ nguyên) |
| `procedure_lookup` | `procedure_lookup` | Hỏi thủ tục (giữ nguyên) |
| `general_info` | `general_info` | Hỏi chung (giữ nguyên) |
| — | `list_chapters` | "Văn bản này có những chương nào?" → B4 không expand DOWN, chỉ list Chapter |
| — | `list_articles` | "Chương II có những điều nào?" → B4 không expand DOWN, list Article |
| — | `list_clauses` | "Điều 6 có những khoản nào?" → B4 list toàn bộ Clause cùng Article |
| — | `missing_fact_query` | Câu hỏi thiếu dữ kiện quan trọng (vd: "Phạt bao nhiêu?" thiếu hành vi cụ thể) |

Lý do mở rộng: theo PDF "Các query mang tính cấu trúc/danh sách có thể override" → cần intent riêng.

### 3.3. History resolution (mới)

Khi `history` có trong input:

1. **Nếu câu hiện tại có dấu hiệu tham chiếu** (`"còn"`, `"vậy"`, `"thế"`, `"cái đó"`, `"thì"`, đại từ `"nó"/"họ"/"đó"` khi không có danh từ đi kèm):
   - Dùng LLM với prompt phụ `SYSTEM_FOLLOWUP_RESOLVER` (định nghĩa dưới).
   - LLM resolve câu hiện tại dựa trên câu gần nhất của assistant → trả `resolved_query`.
2. **Ngược lại**: `resolved_query = cleaned_query` (giữ nguyên).

Thêm constant prompt trong `app/rag/prompts/cleaner.py`:

```python
SYSTEM_FOLLOWUP_RESOLVER = """Bạn là trợ lý pháp lý.

Bạn nhận được:
- Một câu hỏi mới (có thể chứa đại từ tham chiếu).
- Một đoạn hội thoại trước đó.

Nhiệm vụ: VIẾT LẠI câu hỏi mới thành câu ĐỘC LẬP, đầy đủ nghĩa, KHÔNG cần đọc hội thoại.
Trả về JSON: {"resolved_query": "...", "history_dependent": true|false}.

QUY TẮC:
1. Thay "còn ô tô thì sao?" → "Ô tô đi ngược chiều bị phạt bao nhiêu?"
2. Giữ nguyên ngôn ngữ tiếng Việt.
3. KHÔNG thêm thông tin pháp luật ngoài context hội thoại.
4. Nếu không thể resolve → trả câu gốc, history_dependent=false.
"""
```

Pipeline execution:
```
B2 input: question + history
  │
  ├─ Detect reference markers (regex) → is_reference = True/False
  │
  ├─ If is_reference AND history:
  │     resolved = LLM.invoke(SYSTEM_FOLLOWUP_RESOLVER + history + question)
  │     resolved_query = resolved["resolved_query"]
  │     history_dependent = True
  │
  └─ Else:
        resolved_query = question đã rule-based-clean
        history_dependent = False

  → Sau đó mới gọi SYSTEM_QUERY_CLEANER (cũ) với resolved_query
  → Merge: { ...cũ, resolved_query, history_dependent, ...mở rộng }
```

> **Lưu ý quan trọng**: vẫn giữ fallback rule-based cho cả 2 bước. Nếu LLM fail → trả câu gốc, `history_dependent=False` để tránh suy luận sai.

### 3.4. Policy decision (mới)

Sau khi có intent + key_terms, build `retrieval_policy` theo bảng:

| Intent | `intensity` | `expansion` | `max_evidence_hint` | `filters.require_active` | `filters.document_type` |
|---|---|---|---|---|---|
| `penalty_lookup` | `default` | `siblings` | 10 | True | "Nghị định" |
| `rule_lookup` | `default` | `siblings` | 10 | True | "Luật" |
| `procedure_lookup` | `default` | `parent` | 8 | True | None |
| `list_chapters` | `list` | `none` | 5 | False | None |
| `list_articles` | `list` | `none` | 20 | False | None |
| `list_clauses` | `list` | `none` | 20 | False | None |
| `missing_fact_query` | `deep` | `neighbors` | 15 | False | None |
| `general_info` | `default` | `siblings` | 10 | False | None |

**Định nghĩa expansion (dùng chung cho B4)**:
- `none` — không mở rộng, chỉ anchor node từ Pinecone.
- `siblings` — mở rộng HORIZONTAL: các Khoản cùng Điều.
- `parent` — mở rộng UP: 1 cấp (Khoản → Điều, Điều → Chương).
- `neighbors` — mở rộng UP + DOWN + HORIZONTAL (dùng cho missing_fact_query).

**Ý chính đồng ý trong PDF**: "Đây là default policy, không phải luật cứng" → policy này chỉ là **gợi ý mặc định**, B4 vẫn có thể override nếu intent classifier đủ tự tin.

---

## 4. Thiết kế chi tiết — B4

### 4.1. Signature mới

```python
def step_retrieve_hybrid(
    engine,
    cleaned: dict[str, Any],          # đã có sẵn, GIỜ chứa thêm retrieval_policy
    query_vector: list[float],
    top_k: int = 5,
    extra_top_k: int | None = None,
    query_text: str | None = None,
) -> list[dict[str, Any]]:
    """
    Returns list blocks MỚI: đã có status filter + đã expansion theo policy.
    Mỗi block có thêm field:
      - is_active: bool           # status + effective_* check
      - effective_from: str|None
      - effective_to: str|None
      - expanded_from: list[str]  # vector_id của anchor đã mở rộng RA node này
      - expansion_kind: str       # "anchor" | "up" | "down" | "horizontal"
    """
```

### 4.2. Pipeline B4 mới (thay thế luồng cũ)

```
B4 input: cleaned (có retrieval_policy) + query_vector + query_text
  │
  ├── B4a. Pinecone query (như cũ) → raw_matches
  │
  ├── B4b. Soft intent boost (như cũ) → boosted
  │
  ├── B4c. STATUS FILTER (MỚI) ─────────────────────────────
  │   Với mỗi match, query Neo4j:
  │     MATCH (d:Document {id: $document_id})
  │     RETURN d.status AS status,
  │            d.effective_from AS effective_from,
  │            d.effective_to   AS effective_to,
  │            EXISTS { (d)<-[:AMENDED_BY|REPLACED_BY]-(:Article) } AS has_active_amendment
  │   Rule:
  │     if policy.filters.require_active == True:
  │         drop nếu:
  │           - status != "active", HOẶC
  │           - effective_to != None và < today, MÀ không có has_active_amendment
  │     else:
  │         vẫn giữ nhưng flag is_active=False, để B7/B6 biết đường cảnh báo
  │
  ├── B4d. Rerank (như cũ, optional) → anchors
  │
  ├── B4e. EXPANSION (MỚI, theo policy) ────────────────────
  │   Với mỗi anchor (top_k match), thực hiện:
  │     if policy.expansion == "none":   bỏ qua
  │     if policy.expansion == "siblings":  lấy tất cả Clause cùng Article
  │     if policy.expansion == "parent":    lấy Article (nếu anchor là Clause) HOẶC Chapter (nếu anchor là Article)
  │     if policy.expansion == "neighbors":  parent + siblings + children
  │
  │   Query Neo4j (1 lần / expansion kind) bằng Cypher OPTIONAL MATCH.
  │   Các node mở rộng gắn flag `expanded_from = [anchor_vector_id]`,
  │   `expansion_kind = "horizontal" | "up" | "down"`.
  │
  ├── B4f. Dedup merge (Neo4j batch UNWIND, P0 cũ vẫn dùng) → enriched_blocks
  │
  └── Output: enriched_blocks có anchor + expanded
```

### 4.3. Cypher helpers (mới trong `app/rag/context.py`)

```python
NEO4J_STATUS_QUERY = """
MATCH (d:Document {id: $document_id})
RETURN d.id AS document_id,
       d.status AS status,
       d.effective_from AS effective_from,
       d.effective_to AS effective_to
"""

NEO4J_DOC_HAS_ACTIVE_AMENDMENT = """
MATCH (d:Document {id: $document_id})
OPTIONAL MATCH (a:Article {document_id: d.id})-[am:AMENDED_BY|REPLACED_BY]->(other)
RETURN EXISTS { (a)-[:AMENDED_BY|REPLACED_BY]->() } AS has_active_amendment
"""

NEO4J_EXPANSION_HORIZONTAL = """
MATCH (a:Article {id: $article_id})
OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(k:Clause)
WITH a, collect(DISTINCT {
    id: k.id, document_id: k.document_id,
    article_id: a.id, chapter_id: a.chapter_id,
    number: k.number, text: k.text,
    type: 'Clause'
}) AS clauses
RETURN a, clauses
"""

NEO4J_EXPANSION_PARENT = """
MATCH (n {id: $node_id})
WHERE n:Article OR n:Clause
OPTIONAL MATCH (parent)-[:HAS_ARTICLE|HAS_CLAUSE]->(n)
RETURN
  CASE
    WHEN n:Article THEN head(labels(parent))
    WHEN n:Clause THEN head(labels(parent))
    ELSE null
  END AS parent_label,
  parent {.id, .number, .title, .text} AS parent_props
"""

NEO4J_EXPANSION_NEIGHBORS = """
MATCH (n {id: $node_id})
WHERE n:Article OR n:Clause OR n:Document
OPTIONAL MATCH (n)-[:HAS_CLAUSE|IS_PART_OF*1..2]-(neighbor)
RETURN collect(DISTINCT neighbor {.id, .number, .title, .text}) AS neighbors
"""
```

> Lưu ý: Cypher cụ thể cần test khi làm. Phần này là gợi ý để dev1 tham khảo, có thể tinh chỉnh khi implement.

### 4.4. Status filter rule (rule code, không cần LLM)

```python
def _is_document_active(meta: dict, today_iso: str) -> tuple[bool, bool]:
    """
    Returns (is_active, has_active_amendment).
    is_active = True nghĩa là văn bản đang có hiệu lực tính đến ngày today.
    has_active_amendment nghĩa là amendment nào đó đã thay thế bản này.
    """
    status = meta.get("status", "active")
    effective_to = meta.get("effective_to")  # có thể None
    if status != "active":
        # Nếu bị bãi bỏ / hết hạn → check xem có amendment active không
        return (False, meta.get("has_active_amendment", False))
    if effective_to and effective_to < today_iso:
        return (False, False)
    return (True, False)
```

Trong B4: nếu `policy.filters.require_active == True` thì drop match có `is_active == False`.

---

## 5. Thiết kế chi tiết — B5 (chỉnh sửa tối thiểu)

B5 là contract — chỉ cần mở rộng để "đóng gói" đầy đủ cho dev2.

### 5.1. `RequestInfo` — thêm field

```python
class RequestInfo(BaseModel):
    # ... các field cũ giữ nguyên ...
    history_dependent: bool = False               # MỚI
    resolved_query: str = ""                       # MỚI (= cleaned_query nếu không có history)
    retrieval_policy: dict[str, Any] = {}          # MỚI (lưu dict để B6/B7 + dev2 đọc)
```

### 5.2. `EvidenceItem` — thêm field

```python
class EvidenceItem(BaseModel):
    # ... các field cũ giữ nguyên ...
    is_active: bool = True                         # MỚI (default True để back-compat)
    effective_from: str | None = None              # MỚI
    effective_to: str | None = None                # MỚI
    expansion_kind: str = "anchor"                 # MỚI (anchor|up|down|horizontal|neighbor)
    expanded_from: list[str] = []                  # MỚI (vector_id của anchor đã mở rộng RA node này)
```

Cập nhật `LegalContextBuilder.build()`:
1. Merge `cleaned.retrieval_policy` → `request.retrieval_policy`.
2. Merge `cleaned.history_dependent` + `resolved_query` → `request.*`.
3. Với mỗi block trong kept, đọc các field mới từ block (do B4 set):
   - `is_active` ← block["is_active"]
   - `effective_from` ← block.get("effective_from")
   - `effective_to` ← block.get("effective_to")
   - `expansion_kind` ← block.get("expansion_kind", "anchor")
   - `expanded_from` ← block.get("expanded_from", [])

### 5.3. `HierarchyModel` — thêm marker (optional, không bắt buộc)

```python
class HierarchyModel(BaseModel):
    # ...
    expanded: bool = False           # MỚI: True nếu policy.expansion != "none"
    expansion_summary: str = ""      # MỚI: "siblings: Article 6: 4 clauses" ...
```

> Marker này giúp dev2 / debug biết evidence đến từ anchor hay mở rộng.

### 5.4. `LegalContext.stats` — thêm policy echo

```python
stats["retrieval_policy"] = request.retrieval_policy
stats["expansion_executed"] = {
    "kind_counts": {"anchor": N, "horizontal": M, ...},
    "dropped_inactive": K,
}
```

---

## 6. Backward-compat checklist

| API / hàm | Có break? | Ghi chú |
|---|---|---|
| `POST /api/chat` request | Không | `history` đã là field optional sẵn |
| `POST /api/chat` response (`ChatResponse`) | Không | Tất cả field mới thêm vào `LegalContext` (B5 internal), không ảnh hưởng response |
| `build_context_for_llm()`, `build_sources_for_response()` | Không | Giữ signature & behavior cũ |
| `step_clean_query` signature | Không | Chỉ `cleaned` dict có thêm field mới (callers không cần biết) |
| `step_retrieve_hybrid` signature | Không | Chỉ enriched_blocks có thêm field |
| `LegalContext` Pydantic | Không | Thêm field optional → existing JSON vẫn parse được (default value) |
| `RequestInfo`, `EvidenceItem` | Không | Default value cho field mới |
| `tests/test_legal_context.py` | Không | Nếu fail → fix test, KHÔNG đổi code cũ |

---

## 7. Handoff cho dev2

Sau khi dev1 hoàn thành B2 + B4 + B5 (mở rộng), dev2 sẽ nhận `LegalContext` với cấu trúc:

```
LegalContext
├── request
│   ├── original_query
│   ├── normalized_query
│   ├── retrieval_query
│   ├── language
│   ├── intent                        ← giá trị mở rộng (penalty/rule/.../list_chapters/list_clauses/...)
│   ├── legal_domain
│   ├── key_terms
│   ├── history_dependent             ← MỚI
│   ├── resolved_query                ← MỚI
│   └── retrieval_policy              ← MỚI: {intensity, expansion, max_evidence_hint, filters}
│
├── evidence[]                        ← mỗi item có thêm:
│   ├── ... (các field cũ)
│   ├── is_active                     ← MỚI
│   ├── effective_from / effective_to ← MỚI
│   ├── expansion_kind                ← MỚI
│   └── expanded_from                 ← MỚI
│
├── hierarchy
│   ├── documents / ungrouped (cũ)
│   ├── expanded                      ← MỚI
│   └── expansion_summary             ← MỚI
│
├── formatted_context                 ← (cũ — không đổi format)
├── citations[]                       ← (cũ)
└── stats
    ├── ... (cũ)
    ├── retrieval_policy              ← MỚI
    └── expansion_executed            ← MỚI
```

Dev2 chỉ cần đọc `LegalContext` (file `app/rag/schemas/legal_context.py`) để biết B5 cung cấp gì, **không cần đọc B2/B4 code**.

### Gợi ý cho dev2 (không bắt buộc trong đợt này)
- Dùng `request.retrieval_policy.filters.require_active` để B7 biết câu này cần hard-verify về hiệu lực.
- Dùng `evidence[].is_active` để B7 set status `WARN` cho câu trả lời có chứa evidence inactive.
- Dùng `evidence[].expansion_kind == "anchor"` vs `!= "anchor"` để đánh trọng số claim citation.
- `citation ↔ evidence_id` mapping đã có sẵn (CIT-NNN ↔ EV-NNN) — B7 không cần tự build.

---

## 8. Kế hoạch triển khai (gợi ý timeline)

| Phase | Task | Test |
|---|---|---|
| **P0** | Schema mở rộng `RequestInfo`, `EvidenceItem`, `HierarchyModel` (chỉ thêm field, default an toàn) | `tests/test_legal_context.py` chạy OK |
| **P1** | B2 — thêm `resolved_query`, `history_dependent`, `expansion_hint`, `missing_facts`, `retrieval_policy`. Không đụng field cũ. | `tests/test_cleaner.py` thêm 4-5 case: follow-up, list_chapters, list_articles, missing_fact, back-compat |
| **P2** | B3 — embed vẫn dùng `retrieval_query` cũ (không đổi) | (giữ nguyên) |
| **P3** | B4 — thêm status filter + expansion engine (siblings/parent/neighbors) | `tests/test_retrieval.py` thêm 4 case: status filter drop, siblings mở rộng, parent up, neighbors full |
| **P4** | B5 — wrap policy + status fields vào `LegalContext` | `tests/test_context_builder.py` thêm 3 case: policy echo, active flag, expansion_kind đa dạng |
| **P5** | `tests/test_orchestrator.py` — E2E happy path + 1 case thiếu dữ kiện | regression |

**Không cần thiết phải làm theo thứ tự**, miễn P0 trước rồi P1 + P3 song song được.

---

## 9. Câu hỏi cần user quyết trước khi code

1. **History lưu ở đâu trong tương lai?**
   - PDF nói MongoDB, nhưng trong phạm vi đợt này dev1 chỉ cần `ChatRequest.history` (đã có).
   - Không cần persistence trong đợt này (Redis/Supabase có thể dành cho follow-up sau).

2. **Reranker bật hay tắt mặc định?**
   - Hiện `RERANKER_ENABLED=false` (tốt cho dev, nặng cho prod).
   - Dev1 không nên thay đổi default để không phá test. Để runtime config.

3. **`expansion_kind` enum chuẩn hóa thế nào?**
   - Dev1 gợi ý: `"anchor" | "horizontal" | "up" | "down" | "neighbor"` (lower_snake_case cho đồng nhất với các field khác).
   - Comment từ user nếu muốn đổi.

4. **Backward-compat field `cleaned_query`**: có nên trùng `resolved_query` khi không có history không?
   - Dev1 gợi ý: CÓ — `cleaned_query = resolved_query` luôn (để code B6/B7 cũ đọc được).

---

## 10. File sẽ được tạo / sửa (kết luận)

### Sửa
1. `app/rag/prompts/cleaner.py` — thêm `SYSTEM_FOLLOWUP_RESOLVER`, nâng cấp `SYSTEM_QUERY_CLEANER` (thêm trường mới).
2. `app/rag/steps/cleaner.py` — thêm history-aware resolve + policy decision.
3. `app/rag/steps/retrieval.py` — thêm status filter + expansion execution + block fields mới.
4. `app/rag/context.py` — thêm Cypher helpers (UP/DOWN/HORIZONTAL/STATUS).
5. `app/rag/steps/context_builder.py` — wrap policy echo vào `LegalContext`.
6. `app/rag/schemas/legal_context.py` — mở rộng schema (chỉ thêm optional field).
7. `app/core/config.py` — thêm ENV `DEFAULT_RETRIEVAL_INTENSITY`, `TODAY_OVERRIDE` (test).
8. `tests/test_cleaner.py` — bổ sung case history + intent mới.
9. `tests/test_retrieval.py` — bổ sung case expansion + status filter.
10. `tests/test_context_builder.py` — bổ sung case policy echo + expansion kind.

### Tạo mới
1. `app/rag/steps/policy.py` — `build_retrieval_policy(intent, ...) -> dict` (tập trung quy tắc mapping intent → policy đã liệt kê ở §3.4).
2. `app/rag/steps/expansion.py` — `expand(anchor_node, policy, neo_session) -> list[block]` (chạy Cypher mở rộng).
3. `tests/test_policy.py` — đơn vị cho policy builder.
4. `tests/test_expansion.py` — đơn vị cho expansion engine (mock neo session).

### KHÔNG đụng
- `app/rag/prompts/generator.py`, `app/rag/steps/generator.py` (B6)
- `app/rag/prompts/verifier.py`, `app/rag/steps/verification.py` (B7)
- `app/api/routes/chat.py`, `app/core/models.py` (giữ nguyên API public)
- Toàn bộ phần Follow-up Question Generator
- Toàn bộ `document-service`

---

## 11. Acceptance test cho dev1 (trước khi bàn giao)

```python
# 1. Back-compat: câu không có history, intent cũ → policy = default + siblings
assert cleaned_intent_penalty["retrieval_policy"] == {
    "intensity": "default", "expansion": "siblings",
    "max_evidence_hint": 10,
    "filters": {"require_active": True, "document_type": "Nghị định"}
}

# 2. Follow-up: "Còn ô tô thì sao?" với history xe máy → resolved_query chứa "ô tô"
assert cleaned_history["history_dependent"] == True
assert "ô tô" in cleaned_history["resolved_query"]

# 3. List intent: "Điều 6 có những khoản nào?" → policy = list + none
assert cleaned_list["retrieval_policy"]["intensity"] == "list"
assert cleaned_list["retrieval_policy"]["expansion"] == "none"
assert cleaned_list["intent"] == "list_clauses"

# 4. B4 status filter: document hết hạn + require_active=True → drop khỏi evidence
# 5. B4 expansion: anchor at Clause → expansion siblings → evidence chứa tất cả Clause cùng Article
# 6. LegalContext.evidence[0].is_active có giá trị đúng (True/False), expansion_kind ∈ {anchor, horizontal, up, down, neighbor}
# 7. E2E: full pipeline chạy, response shape không đổi, debug có thêm stats.retrieval_policy
```

Khi tất cả pass → báo dev2 nhận hàng.
