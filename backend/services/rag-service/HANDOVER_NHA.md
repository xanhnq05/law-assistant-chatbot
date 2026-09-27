# 📋 Bàn giao cho DEV2 — Phần đã được dev1 implement (NHẦM)

> **Lưu ý quan trọng**: 2 phần dưới đây theo PDF `tổng hợp sửa đổi các bước` là trách nhiệm của **dev2**, KHÔNG phải dev1. Tuy nhiên dev1 đã vô tình implement một phần trong đợt sửa B2/B4 lần này.
>
> Tài liệu này liệt kê CHÍNH XÁC những gì dev1 đã code để dev2 review, hoàn thiện, hoặc viết lại (nếu cần) cho phù hợp với thiết kế B6/B7/Follow-up của dev2.

---

## 1. Conversation Memory (in-process) — DEV1 đã implement

### 📍 Vị trí code đã có
- **`backend/services/rag-service/app/rag/memory.py`** (file MỚI, 290 dòng)
- **`backend/services/rag-service/app/rag/orchestrator.py`** (đã tích hợp vào B1)
- **`backend/services/rag-service/app/api/routes/chat.py`** (đã nhận `session_id`)
- **`backend/services/rag-service/app/core/models.py`** (`ChatRequest.session_id`)
- **`backend/services/rag-service/tests/test_memory.py`** (17 tests PASS)

### 🎯 Chức năng đã có (do dev1 implement)

```python
# Từ memory.py - public API
class ConversationMemory:
    """In-process conversation memory singleton."""
    
    # Session ops
    def get_or_create(session_id: str) -> Session
    def get(session_id: str) -> Session | None
    def delete(session_id: str) -> bool
    def clear_all() -> None
    def stats() -> dict
    
    # Message ops
    def add_message(session_id, role, content, metadata=None)
    def add_exchange(session_id, user_message, assistant_message, **metadata)
    
    # Retrieve cho query
    def get_history_for_query(session_id, max_msgs=6) -> list[dict]
    def get_context_summary(session_id) -> str
    
    # Summarization (placeholder, chưa auto)
    def set_summary(session_id, summary)
    def needs_summary(session_id) -> bool

def get_memory() -> ConversationMemory   # singleton accessor
```

### ✅ Đã có (theo spec PDF)
- **Recent Messages**: lưu 20 msg gần nhất, query lấy 6 msg (= 3 cặp) — ✅
- **Lưu/cập nhật conversation**: có `add_message()` / `add_exchange()` — ✅
- **Singleton + TTL cleanup** (2 giờ idle) — ✅
- **FIFO trim** khi quá MAX_MESSAGES_PER_SESSION — ✅
- **Thread-safe** bằng `threading.Lock` — ✅

### ❌ CHƯA có (dev2 cần làm tiếp theo PDF)
- **Conversation Summary** tự động (hiện chỉ có `needs_summary` flag + manual `set_summary`)
- **Background job** để summarize khi `needs_summary=True`
- **MongoDB persistence** (theo PDF "Với stack hiện tại, có thể dùng MongoDB") — hiện đang in-process only
- **Schema đầy đủ**:
  ```
  conversations: { conversation_id, user_id, summary, created_at, updated_at }
  messages:      { message_id, conversation_id, role, content, created_at, metadata }
  ```

### ⚠️ Quan trọng cho dev2
Dev2 có 2 lựa chọn:
1. **Dùng tiếp** memory.py của dev1 (in-process) cho dev/test, integrate MongoDB sau.
2. **Viết lại** theo thiết kế MongoDB-first của dev2.

Nếu dev2 viết lại, cần:
- Cập nhật lại `orchestrator.py: _resolve_history()` + `_save_to_memory()` cho dùng MongoDB API.
- Xóa/sửa `memory.py` (hoặc giữ làm fallback in-process).

---

## 2. Follow-up Question Generator — DEV1 CHƯA LÀM

> Theo PDF: "Follow-up Question Generator được bổ sung. Phần này giao cho người làm B6/B7 cùng thực hiện."

### 🔍 Dev1 KHÔNG tạo file/module nào liên quan trực tiếp.

`grep -i "follow.?up"` chỉ match ở:
- `PLAN_B2_B4.md` (doc mô tả kế hoạch)
- `schemas/legal_context.py`, `steps/cleaner.py`, `orchestrator.py`, `prompts/cleaner.py` — không có logic Follow-up, chỉ là TODO/comment.

**→ Dev2 hoàn toàn tự do làm từ đầu.**

### 📐 Spec từ PDF cho dev2
```
Input: User Query + Verified Answer + Legal Context
Output: ~3 câu hỏi tiếp theo

Điều kiện:
- Chỉ gợi ý dựa trên nội dung đã verified/context hiện có
- Không tự bịa thêm vấn đề pháp luật ngoài phạm vi evidence
- Đây là thành phần riêng sau verification, không thuộc B7
```

### 💡 Suggest cho dev2 (ngoài spec)
Vì B5 đã chuẩn hóa `LegalContext`, dev2 có sẵn:
- `LegalContext.evidence[].content` + `hierarchy_path` (text pháp luật đã retrieved)
- `LegalContext.citations[]` (đã trỏ về evidence)
- Sau B7 verified → `VerificationResult.status/confidence`

Gợi ý vị trí module:
```python
app/rag/steps/followup_generator.py     # step mới, gọi SAU B7
app/rag/prompts/followup.py             # system prompt cho generator LLM
```

Hoặc nếu dev2 muốn dev1 tạo skeleton, có thể bảo dev1 làm tiếp.

---

## 3. Tổng hợp file đã sửa / tạo cho 2 phần này

| File | Trạng thái | Mục đích |
|------|------------|----------|
| `app/rag/memory.py` | **TẠO MỚI** | In-process Conversation Memory |
| `app/rag/orchestrator.py` | **ĐÃ SỬA** | Tích hợp memory vào B1 (load/save history) |
| `app/api/routes/chat.py` | **ĐÃ SỬA** | Truyền `session_id` vào pipeline |
| `app/core/models.py` | **ĐÃ SỬA** | Thêm `ChatRequest.session_id` (optional) |
| `tests/test_memory.py` | **TẠO MỚI** | 17 tests cho memory |
| `app/rag/steps/followup_generator.py` | ❌ CHƯA CÓ | Để dev2 tạo |
| `app/rag/prompts/followup.py` | ❌ CHƯA CÓ | Để dev2 tạo |

---

## 4. Hành động cần làm

1. **Dev2 review** file `memory.py` + cách `orchestrator.py` tích hợp.
2. **Dev2 quyết định**:
   - ✅ Giữ nguyên + bổ sung summary/background job/MongoDB → tạo follow-up ticket.
   - ⚠️ Hoặc **rút lại** conversation memory khỏi dev1 (move hết sang dev2) → dev1 rollback 5 file trên.
3. **Follow-up Generator**: dev2 tạo từ đầu (không bị overlap với dev1).

---

**Dev1 đã note lại phần này trong [BACKLOG.md](#) và không làm tiếp cho tới khi có xác nhận từ dev2.**
