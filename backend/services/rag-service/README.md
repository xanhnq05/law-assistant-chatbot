# rag-service — 7-step Hybrid RAG pipeline

Service RAG cho chatbot pháp luật giao thông Việt Nam, theo kiến trúc
trong 2 ảnh thiết kế:

- **Image 1**: LangChain Orchestration → Query Cleaner → Embedding →
  Hybrid Retrieval → Context Builder → LLM Generation → **Symbolic Verification**
- **Image 2**: Bước 7 (Symbolic Verification) là bước cuối cùng xác thực câu trả lời

## Cấu trúc thư mục

```
backend/services/rag-service/
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI entrypoint
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       └── chat.py                # POST /api/chat (thin wrapper)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                  # Service config + re-export shared
│   │   └── models.py                  # Pydantic schemas (request/response)
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── engine.py                  # RagEngine: heavy resources holder
│   │   ├── context.py                 # Citation + LLM context helpers
│   │   ├── orchestrator.py            # LangChain pipeline runner (B1)
│   │   ├── steps/                     # Các bước pipeline (B2-B7)
│   │   │   ├── __init__.py
│   │   │   ├── cleaner.py             # B2 - Query Cleaner
│   │   │   ├── embedding.py           # B3 - Embedding câu hỏi
│   │   │   ├── retrieval.py           # B4 - Hybrid Retrieval
│   │   │   ├── context_builder.py     # B5 - Context Builder
│   │   │   ├── generator.py           # B6 - LLM Generation
│   │   │   └── verification.py        # B7 - Symbolic Verification
│   │   └── prompts/                   # System prompts cho mỗi step
│   │       ├── __init__.py
│   │       ├── cleaner.py
│   │       ├── generator.py
│   │       └── verifier.py
│   └── (các thư mục khác)
├── tests/                             # Pytest unit tests
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_cleaner.py                # B2
│   ├── test_embedding.py              # B3
│   ├── test_retrieval.py              # B4
│   ├── test_context_builder.py        # B5
│   ├── test_generator.py              # B6
│   ├── test_verification.py           # B7
│   └── test_orchestrator.py           # Full pipeline
├── Dockerfile
├── pytest.ini
├── requirements.txt
└── README.md
```

## Pipeline 7 bước

| Bước | Tên                  | Module                              | Mô tả                                                       |
|------|----------------------|-------------------------------------|-------------------------------------------------------------|
| B1   | Orchestrator         | `rag/orchestrator.py`               | LangChain pipeline state machine, kết nối các step         |
| B2   | Query Cleaner        | `rag/steps/cleaner.py`              | LLM làm sạch + tái cấu trúc câu hỏi, tách intent           |
| B3   | Embedding            | `rag/steps/embedding.py`            | Encode câu hỏi thành vector (sentence-transformers)        |
| B4   | Hybrid Retrieval     | `rag/steps/retrieval.py`            | Pinecone vector search + Neo4j enrich (Document/Chapter/Article/Clause + Relationships) |
| B5   | Context Builder      | `rag/steps/context_builder.py`      | Dedup, sắp xếp, format context cho LLM                     |
| B6   | LLM Generation       | `rag/steps/generator.py`            | Groq LLM sinh câu trả lời có trích dẫn                    |
| B7   | Symbolic Verification| `rag/steps/verification.py`         | Hybrid: rule-based + LLM-as-Judge xác thực đáp án          |

## B7 - Symbolic Verification (Hybrid)

Chiến lược kết hợp:

1. **Rule-based** (luôn chạy):
   - Detect citation trong answer (`Điều X, Khoản Y, Điểm Z`)
   - Match với context_blocks
   - Kiểm tra fallback message
2. **LLM-as-Judge** (optional, bật qua env `VERIFIER_LLM_ENABLED=true`):
   - Gọi Groq model nhỏ (`llama-3.1-8b-instant`)
   - Đánh giá grounded/correct/addressed
3. **Combine**: `final_score = 0.6 * rule_score + 0.4 * llm_confidence`
4. **Status**:
   - `PASS` (≥ 0.6) : có citation hợp lệ, cites valid doc
   - `WARN` (≥ 0.3) : thiếu 1 trong các tiêu chí
   - `FAIL` (< 0.3)  : không đạt

## Luồng Hybrid Retrieval (B4 chi tiết)

```
câu hỏi
   │
   ▼
[1] Embed câu hỏi → vector
   │
   ▼
[2] Pinecone query (top_k=8) → list vector matches
   │  metadata: {document_id, chapter_id, article_id, clause_id}
   │
   ▼
[3] Filter theo intent (penalty/rule/procedure)
   │
   ▼
[4] Với MỖI match, query Neo4j:
       MATCH (d:Document)
       OPTIONAL MATCH (c:Chapter)
       OPTIONAL MATCH (a:Article)
       OPTIONAL MATCH (k:Clause)
       OPTIONAL MATCH (a)-[am:AMENDS|REPLACES|REPEALS]->(related)
   │
   ▼
[5] Trả về enriched block:
       {citation, context_block, related_amendments, ...}
```

## Chạy local

```bash
cd backend
$env:PYTHONPATH="backend;backend/services/rag-service"
uvicorn services.rag-service.app.main:app --reload --port 8003
```

## Chạy Docker

```bash
docker compose up rag-service
```

## Tests

```bash
cd backend/services/rag-service
pip install -r requirements.txt
pytest tests/ -v
```

## API contract

### POST `/api/chat`

**Request:**
```json
{
  "question": "Phạt bao nhiêu khi đi xe máy không nhường đường?",
  "top_k": 5,
  "verify": true
}
```

**Response:**
```json
{
  "answer": "Theo Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4, phạt 4-6 triệu đồng.\n\nTrích dẫn:\n- Nghị định 168/2024/NĐ-CP, Điều 6, Khoản 4: ...",
  "sources": [
    {
      "citation": "Nghị định 168/2024/NĐ-CP - Điều 6, Khoản 4",
      "score": 0.91,
      "context_block": "...",
      "law_document_type": "Nghị định",
      "law_document_number": "168/2024/NĐ-CP",
      "related_amendments": []
    }
  ],
  "verification": {
    "status": "pass",
    "confidence": 0.85,
    "has_citation": true,
    "citation_count": 1,
    "cites_valid_doc": true,
    "context_grounded": true,
    "issues": [],
    "llm_judge_used": true,
    "llm_judge_reason": "OK"
  },
  "debug": {
    "cleaned_query": "phạt xe máy không nhường đường",
    "legal_domain": "xử phạt giao thông",
    "key_legal_terms": ["phạt", "xe máy", "không nhường đường"],
    "intent": "penalty_lookup",
    "retrieved_count": 5,
    "context_chars": 1234
  }
}
```
