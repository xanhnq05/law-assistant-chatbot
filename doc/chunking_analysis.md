# Phân tích chunking dữ liệu JSON hiện tại

> Cập nhật: 2026-08-16. Tài liệu này phân tích cách `data_import/import_data_pinecone.py` đang cắt
> vector hiện tại, chỉ ra các điểm yếu, và đề xuất chiến lược mới.

---

## 1. Cách cắt HIỆN TẠI

`data_import/import_data_pinecone.py` (`build_units`, dòng 133-241) tạo **1 vector cho mỗi đơn vị** trong cây:

```
document
└── chapters
    └── articles
        ├── clause (1 vector)
        │   └── point (1 vector)
        └── article text (1 vector)
```

**Cụ thể**: Với mỗi article có N khoản + M điểm → tạo N+M+1 vector.

### Ví dụ thực tế
File Nghị định 168, Điều 6 có:
- 1 article (vector: "Điều 6. Xử phạt...")
- 4 khoản (mỗi khoản = 1 vector)
- khoản 4 có 5 điểm a,b,c,d,đ (mỗi điểm = 1 vector)

→ Tổng cộng **~12 vector** cho 1 điều luật.

### Thống kê
- **Luật 36**: 89 articles × trung bình ~5 khoản × ~2 điểm ≈ **~1.500 vector**
- **Nghị định 168**: 55 articles × trung bình ~10 khoản × ~5 điểm ≈ **~3.000 vector**

---

## 2. Các điểm yếu NGHIÊM TRỌNG

### 🔴 Bug #1: Mất ngữ cảnh khi tách điểm

**Hiện trạng**: Mỗi `point` được embed riêng lẻ:
```json
{ "label": "đ", "text": "Đối với xe máy: phạt tiền từ 4.000.000đ đến 6.000.000đ" }
```

→ Vector không biết `đ` là điểm gì, của khoản nào, điều nào.

**Ví dụ thực**: User hỏi *"Phạt bao nhiêu khi đi xe máy không nhường đường cho xe xin vượt?"*:
- Câu embed → vector
- Điểm `đ` chỉ embed `"Đối với xe máy: phạt tiền từ 4.000.000đ đến 6.000.000đ"`
- Match? Có thể match (có từ "xe máy", "phạt tiền") → **OK**
- Nhưng **mất thông tin điều kiện**: khoản 4 chỉ áp dụng khi **không gây tai nạn** (khoản 5), khoản 2 chỉ áp dụng khi **có GPLX**, v.v...

→ LLM chỉ thấy 1 điểm → trả lời sai đối tượng.

### 🔴 Bug #2: Thiếu metadata khi embed

**Hiện trạng** (`import_data_pinecone.py:295-325`):
- Vector của `point` chỉ có `text` + metadata cơ bản (id, law_id, article_id...)
- **KHÔNG** có: tên điều, tên khoản (cha), nội dung khoản (cha)

→ Retrieval dùng cosine similarity trên text thuần, model embedding không hiểu `"đ) Đối với xe máy: ..."` đang nằm trong ngữ cảnh nào.

### 🔴 Bug #3: Khoản lớn bị chia nhỏ vô lý

**Hiện trạng**: Một khoản có 10 điểm (vd: khoản 4 Điều 6 NĐ 168) → 10 vector riêng.
- Mỗi vector rất ngắn (~30-50 từ) → embedding ít có ý nghĩa ngữ nghĩa
- 10 vector có thể **match trùng nhau** với cùng 1 câu hỏi → context bị duplicate

### 🔴 Bug #4: Không phân biệt loại văn bản

**Hiện trạng**: Tất cả vector được embed giống nhau, lưu cùng 1 index Pinecone.
- User hỏi "phạt bao nhiêu" → có thể retrieve cả quy tắc (Luật 36) lẫn mức phạt (NĐ 168)
- LLM bị loạn, phải tự phân biệt

---

## 3. Đề xuất chiến lược chunking MỚI: **Parent-Context Chunking**

### Nguyên tắc

```
┌─ VECTOR 1: Article-level ───────────────────────┐
│ "Điều 6. Xử phạt hành vi không nhường đường     │
│  cho xe xin vượt, gây ùn tắc giao thông"        │
│  + toàn bộ khoản 1, 2, 3, 4, 5 (tóm tắt)        │
└──────────────────────────────────────────────────┘
┌─ VECTOR 2: Clause-level (mỗi khoản) ────────────┐
│ "Điều 6, Khoản 4: Phạt tiền từ 4-6 triệu đối  │
│  với người điều khiển xe máy. Bao gồm:         │
│  a) Không có GPLX... b) Có GPLX...               │
│  c) ... d) ... đ) Đối với xe máy..."            │
│  (= gộp toàn bộ điểm vào 1 vector)              │
└──────────────────────────────────────────────────┘
```

### Quy tắc cụ thể

| Loại đơn vị | Khi nào embed | Text được embed |
|---|---|---|
| **Article** | Nếu article có text riêng (mở điều) | Title + text |
| **Clause** | LUÔN LUÔN | Title điều + "Khoản X: " + text khoản + TẤT CẢ điểm (gộp) |
| **Point** | CHỈ embed riêng nếu clause text rỗng | "Điều X Khoản Y Điểm z: text" |

### Metadata bắt buộc thêm vào mỗi vector

| Field | Mục đích |
|---|---|
| `chapter_title` | Tên chương (vd: "QUY TẮC GIAO THÔNG ĐƯỜNG BỘ") |
| `article_title` | Tên điều (vd: "Xử phạt hành vi không nhường đường") |
| `article_number` | Số điều (vd: "6") |
| `clause_number` | Số khoản (vd: "4") - hoặc rỗng nếu là article-level |
| `full_path` | Citation đầy đủ (vd: "Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4") |
| `document_type` | "Luật" / "Nghị định" - cho filter |
| `applies_to` | Phân loại: "vehicle_type", "penalty_amount", "general_rule" (nếu detect được) |

### Ước lượng số vector MỚI

| File | Hiện tại | Mới | Giảm |
|---|---|---|---|
| Luật 36 | ~1.500 | ~500 (89 articles + ~400 clauses) | 67% |
| Nghị định 168 | ~3.000 | ~600 (55 articles + ~550 clauses) | 80% |

→ Ít vector hơn → nhưng **chất lượng cao hơn** vì có parent context.

---

## 4. Code mẫu (snippet)

```python
def build_clause_blob(article: dict, clause: dict, chapter_title: str) -> str:
    """Build the text that will be embedded for a clause unit."""
    parts = []
    # Parent context
    parts.append(f"[{chapter_title}]")
    parts.append(f"Điều {article['number']}. {article.get('title', '').strip()}")
    parts.append(f"Khoản {clause['number']}: {clause.get('text', '').strip()}")

    # Inline all points so the embedding captures conditions too
    for point in clause.get("points", []):
        label = point.get("label") or point.get("number") or "?"
        parts.append(f"  {label}) {point.get('text', '').strip()}")

    return "\n".join(parts).strip()


def build_article_blob(article: dict, chapter_title: str) -> str:
    """Build a summary-level blob for the article as a whole."""
    parts = [
        f"[{chapter_title}]",
        f"Điều {article['number']}. {article.get('title', '').strip()}",
    ]
    if article.get("text"):
        parts.append(article["text"].strip())
    return "\n".join(parts).strip()
```

---

## 5. Kế hoạch triển khai

| Bước | Mô tả | Thời gian |
|---|---|---|
| 1 | Backup file JSON hiện tại vào `doc/.backup_split/` | 5 phút |
| 2 | Viết `clean_text.py`: làm sạch PDF garbage (footer "Người ký:") | 30 phút |
| 3 | Viết `build_units_v2.py` với logic parent-context | 1 giờ |
| 4 | Re-import vào Pinecone (xóa index cũ trước) | 30 phút |
| 5 | Test retrieval với 20 câu hỏi mẫu | 1 giờ |

---

## 6. Đề xuất các cải tiến bổ sung (chunking xong rồi làm)

1. **Filter retrieval theo `document_type`** trong B2 (xem file `backend/rag/steps.py:48-85`)
   - Câu hỏi "phạt bao nhiêu" → chỉ retrieve `Nghị định`
   - Câu hỏi "quy tắc là gì" → chỉ retrieve `Luật`

2. **Thêm BM25 hybrid search** (xem đánh giá trước - ưu tiên 2.2)

3. **Đổi embedding model** sang `intfloat/multilingual-e5-large` (1024 dim) - xem ưu tiên 2.3

4. **Thêm reranker** `BAAI/bge-reranker-v2-m3` sau retrieval - xem ưu tiên 2.1

---

## Tài liệu liên quan

- `doc/schema.json` - JSON Schema chuẩn cho dữ liệu
- `data_import/validate_docs.py` - Validate dữ liệu đầu vào
- `data_import/merge_law36.py` - Gộp 2 file Luật 36 bị tách