# Trợ lý Luật Giao thông - RAG Chatbot

Hệ thống truy xuất và trả lời câu hỏi về Luật Trật tự, An toàn Giao thông Đường bộ (Việt Nam).

## Kiến trúc

```
docs/             # JSON văn bản luật (input)
       |
       v
data_import/      # Scripts đẩy data lên DB
   |        |
   v        v
 Neo4j   Pinecone       (knowledge layer)
   |        |
   +--+-----+
      v
backend/          # FastAPI server (RAG pipeline B1->B2->B3)
      |
      v
frontend/         # React chat UI
```Pipeline RAG (trong `backend/app.py`):
- **B1 Query Understanding** - Groq LLM tái cấu trúc câu hỏi
- **B2 Retrieval** - Pinecone (vector) + Neo4j (graph context)
- **B3 Answer Generation** - Groq LLM trả lời + trích dẫn

## Cấu trúc thư mục

```
tro_ly_luat/
├── backend/           # FastAPI server
│   ├── app.py         # Main app với /api/chat
│   ├── requirements.txt
│   ├── .env           # API keys (không commit)
│   └── env_example
├── frontend/          # React + Vite
│   ├── src/App.jsx
│   ├── package.json
│   └── vite.config.js # Proxy /api -> backend :8000
├── data_import/       # Scripts seed data vào Neo4j + Pinecone
│   ├── import_data_neo4j.py
│   ├── import_data_pinecone.py
│   └── requirements.txt
├── docs/              # JSON luật (source of truth)
└── .gitignore
```

## Cài đặt

### 1. Backend

```bash
cd backend
python -m pip install -r requirements.txt
cp env_example .env
# Sửa .env: điền GROQ_API_KEY, NEO4J_*, PINECONE_API_KEY
python -m uvicorn app:app --reload --port 8000
```

### 2. Import data (chỉ chạy 1 lần khi setup)

```bash
cd data_import
python -m pip install -r requirements.txt
python import_data_neo4j.py    # JSON -> Neo4j graph
python import_data_pinecone.py # JSON -> Pinecone vectors
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

## API

### `POST /api/chat`

Request:
```json
{ "question": "...", "top_k": 5 }
```

Response:
```json
{
  "answer": "Câu trả lời...",
  "sources": [
    { "citation": "Điều 30, Khoản 1", "score": 0.85, "context_block": "..." }
  ],
  "debug": {
    "reformulated_query": "...",
    "legal_domain": "...",
    "key_legal_terms": []
  }
}
```

## Stack

| Layer | Tech |
|---|---|
| Vector DB | Pinecone (384 dim, cosine) |
| Graph DB | Neo4j Aura |
| Embedding | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (local) |
| LLM | Groq llama-3.3-70b-versatile |
| Backend | FastAPI + uvicorn |
| Frontend | React 18 + Vite |
