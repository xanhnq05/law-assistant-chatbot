# rag-service — Kiến trúc Pipeline 7 bước

> Cập nhật: 2026-09-05. Tài liệu này mô tả cấu trúc và pipeline mới của `rag-service`,
> theo 2 ảnh thiết kế (image 1: LangChain Orchestration & image 2: Hybrid RAG system).

## 1. Pipeline tổng quan

```
┌─────────────────────────────────────────────────────────────────────┐
│  USER → POST /api/chat                                              │
│      {question, top_k, verify}                                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B1. LangChain Orchestrator  (rag/orchestrator.py)                  │
│      - Quản lý state machine                                        │
│      - Điều phối B2 → B3 → B4 → B5 → B6 → B7                       │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B2. Query Cleaner  (rag/steps/cleaner.py)                          │
│      Input:  raw question                                           │
│      Output: {cleaned_query, legal_domain, key_legal_terms, intent} │
│      LLM:   Groq (llama-3.3-70b)                                    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B3. Embedding  (rag/steps/embedding.py)                            │
│      Model: sentence-transformers/paraphrase-multilingual-MiniLM    │
│      Output: vector 384-d normalized                                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B4. Hybrid Retrieval  (rag/steps/retrieval.py)                     │
│      ┌──────────────────────────────────────────┐                   │
│      │ 4a. Pinecone vector query (top_k=8)      │                   │
│      │     ↓ metadata {document_id, article..} │                   │
│      │ 4b. Filter theo intent (penalty/rule..)  │                   │
│      │     ↓                                    │                   │
│      │ 4c. Neo4j enrich cho TỪNG match:        │                   │
│      │     Document + Chapter + Article        │                   │
│      │     + Clause + Relationships             │                   │
│      │     (AMENDS, REPLACES, REPEALS, ADDS)   │                   │
│      └──────────────────────────────────────────┘                   │
│      Output: list enriched blocks (top_k=5)                         │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B5. Context Builder  (rag/steps/context_builder.py)                │
│      - Dedup theo citation                                          │
│      - Sort theo score desc                                         │
│      - Highlight quan hệ AMEND/REPLACE/REPEAL                       │
│      - Format LLM-ready string                                      │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B6. LLM Generation  (rag/steps/generator.py)                       │
│      LLM:   Groq (llama-3.3-70b-versatile)                          │
│      Prompt: SYSTEM_ANSWER_GENERATION (prompts/generator.py)        │
│      Output: answer có trích dẫn rõ ràng                           │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  B7. Symbolic Verification  (rag/steps/verification.py)             │
│      ┌──────────────────────────────────────────┐                   │
│      │ Rule-based (luôn chạy):                   │                   │
│      │   - Extract citation từ answer            │                   │
│      │   - Match với context_blocks              │                   │
│      │   - Check fallback message                │                   │
│      │     ↓                                      │                   │
│      │ LLM-as-Judge (optional, hybrid):          │                   │
│      │   - Groq llama-3.1-8b-instant             │                   │
│      │   - Prompt: SYSTEM_VERIFIER               │                   │
│      │   - Đánh giá grounded/correct/addressed   │                   │
│      │     ↓                                      │                   │
│      │ Combine: 0.6 * rule + 0.4 * llm_conf      │                   │
│      │     ↓                                      │                   │
│      │ Status: PASS / WARN / FAIL                │                   │
│      └──────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  RESPONSE → USER                                                    │
│  {answer, sources[], verification, debug{...}}                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Cấu trúc thư mục

```
backend/services/rag-service/
├── app/
│   ├── main.py                      # FastAPI entrypoint
│   ├── api/routes/chat.py           # POST /api/chat
│   ├── core/
│   │   ├── config.py                # Service config
│   │   └── models.py                # Pydantic schemas
│   └── rag/
│       ├── engine.py                # Heavy resources
│       ├── context.py               # Citation helpers
│       ├── orchestrator.py          # B1
│       ├── steps/
│       │   ├── cleaner.py           # B2
│       │   ├── embedding.py         # B3
│       │   ├── retrieval.py         # B4
│       │   ├── context_builder.py   # B5
│       │   ├── generator.py         # B6
│       │   └── verification.py      # B7
│       └── prompts/
│           ├── cleaner.py
│           ├── generator.py
│           └── verifier.py
├── tests/
│   ├── conftest.py                  # Mock fixtures
│   ├── test_cleaner.py              # B2
│   ├── test_embedding.py            # B3
│   ├── test_retrieval.py            # B4
│   ├── test_context_builder.py      # B5
│   ├── test_generator.py            # B6
│   ├── test_verification.py         # B7
│   └── test_orchestrator.py         # Full pipeline
├── Dockerfile
├── requirements.txt
├── pytest.ini
└── README.md
```

## 3. Data Flow chi tiết cho Hybrid Retrieval (B4)

```
question
   │
   ▼ (B3 - Embedding)
[vector 384-d]
   │
   ▼ (B4a - Pinecone)
[top_k=8 raw_matches]    mỗi match có metadata:
                          - document_id, chapter_id
                          - article_id, clause_id
                          - type (article/clause)
                          - chapter_title, article_title, ...
   │
   ▼ (B4b - Intent filter)
[filtered matches]
   │   penalty_lookup → chỉ giữ Nghị định
   │   rule_lookup    → chỉ giữ Luật
   │   general_info   → giữ tất cả
   ▼
   ▼ (B4c - Neo4j enrich cho mỗi match)
   Cypher:
     MATCH (d:Document {id:$document_id})
     OPTIONAL MATCH (c:Chapter)-[:HAS_ARTICLE]->(a:Article)
     OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(k:Clause)
     OPTIONAL MATCH (a)-[am:AMENDS|REPLACES|REPEALS|ADDS]->(related)
     OPTIONAL MATCH (a)-[am2:AMENDED_BY|REPLACED_BY|REPEALED_BY|ADDED_IN]->(related2)
     RETURN ...
   │
   ▼
[enriched blocks]
  - citation
  - context_block (LLM-ready text)
  - law_document_type, law_document_number, law_title
  - law_date_enacted, law_date_effective, law_issuing_authority
  - chapter_number, chapter_title
  - article_number, article_title
  - clause_number
  - related_amendments: [{type, target_id, target_label, ...}]
   │
   ▼
[top_k=5 blocks] → B5
```

## 4. Symbolic Verification (B7) — Hybrid

### 4.1 Rule-based (luôn chạy)

| Check                  | Logic                                                 | Score |
|------------------------|-------------------------------------------------------|-------|
| `has_citation`         | Detect pattern "Điều X[, Khoản Y[, Điểm Z]]"         | +0.4  |
| `cites_valid_doc`      | Citation tồn tại trong context_blocks                 | +0.3  |
| `context_grounded`     | Answer có chứa article_number từ context              | +0.3  |
| Penalty `fallback`     | "không tìm thấy" trong answer → max score = 0.4       | -     |

### 4.2 LLM-as-Judge (optional, Groq llama-3.1-8b-instant)

```json
{
  "is_grounded": true,
  "has_citation": true,
  "citation_correct": true,
  "addresses_question": true,
  "confidence": 0.85,
  "issues": [],
  "reason": "Câu trả lời đúng, có trích dẫn"
}
```

### 4.3 Combine & Status

```
final_score = 0.6 * rule_score + 0.4 * llm_confidence

if final_score ≥ 0.6 AND has_citation AND cites_valid_doc:
    status = PASS
elif final_score ≥ 0.3:
    status = WARN
else:
    status = FAIL
```

## 5. Config (env vars)

| Biến                          | Mặc định                                        | Mô tả                              |
|-------------------------------|-------------------------------------------------|------------------------------------|
| `GROQ_API_KEY`                | (bắt buộc)                                      | Groq API key                       |
| `GROQ_MODEL`                  | `llama-3.3-70b-versatile`                       | LLM cho B6                         |
| `GROQ_MODEL_FAST`             | `llama-3.1-8b-instant`                          | LLM cho B7 verifier                |
| `EMBEDDING_MODEL`             | `paraphrase-multilingual-MiniLM-L12-v2`         | B3 model                           |
| `EMBEDDING_DIM`               | `384`                                           | Vector dim                         |
| `PINECONE_INDEX_NAME`         | `law-rag-v1`                                    | Pinecone index                     |
| `PINECONE_TOP_K`              | `8`                                             | Lấy dư từ Pinecone để filter       |
| `VERIFICATION_PASS_THRESHOLD` | `0.6`                                           | Ngưỡng PASS cho B7                 |
| `VERIFIER_LLM_ENABLED`        | `true`                                          | Bật/tắt LLM-as-Judge              |
| `RAG_SERVICE_PORT`            | `8003`                                          | Service port                       |

## 6. Chạy & Test

### Local
```bash
cd backend
$env:PYTHONPATH="backend;backend/services/rag-service"
uvicorn services.rag-service.app.main:app --reload --port 8003
```

### Docker
```bash
docker compose up rag-service
```

### Tests
```bash
cd backend/services/rag-service
pytest tests/ -v
```
