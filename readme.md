# Trợ lý Luật Giao thông - RAG Chatbot

Hệ thống truy xuất và trả lời câu hỏi về Luật Trật tự, An toàn Giao thông Đường bộ (Việt Nam).

## Kiến trúc

```
docs/             # JSON văn bản luật (input)
       |
    10|       v
data_import/      # Scripts đẩy data lên DB
   |        |
   v        v
 Neo4j   Pinecone       (knowledge layer)
   |        |
   +--+-----+
      v
backend/          # FastAPI server (RAG pipeline B1->B2->B3)
      |     +--- routers/ (auth, chat)
      |     +--- services/ (auth, chat)
      |     +--- utils/auth/ (JWT, Google OAuth, user CRUD)
      |     +--- utils/chat/ (chat session CRUD)
      |     +--- utils/user/ (load user/history)
      |     +--- schemas/ (Pydantic models)
      |     +--- database/ (MongoDB, Neo4j)
      +-- 30|      v
frontend/         # React chat UI
```

Pipeline RAG (trong `backend/app.py`):
- **B1 Query Understanding** - Groq LLM tái cấu trúc câu hỏi
- **B2 Retrieval** - Pinecone (vector) + Neo4j (graph context)
- **B3 Answer Generation** - Groq LLM trả lời + trích dẫn

## Cấu trúc thư mục

```
    40|backend/
├── app.py                 # FastAPI entry point, gắn routers
├── requirements.txt
├── .env / env_example
├── core/
│   ├── config.py          # Env vars + logging
│   └── models.py          # Pydantic request/response (RAG)
├── database/
│   ├── __init__.py
│   ├── mongo_client.py    # MongoDB singleton
│   └── neo4j_client.py   # Neo4j singleton
├── schemas/               # Pydantic models
│   ├── __init__.py
│   ├── user.py            # User, UserPublic, LoginResponse, GoogleUserInfo
│   ├── chat_message.py    # ChatMessage, AddMessageRequest
│   ├── chat_session.py    # ChatSession, CreateChatRequest, UpdateChatRequest, ChatSessionResponse
│   └── history_chat.py    # ChatHistory, ChatHistoryEntry, ChatHistoryResponse
├── services/
│   ├── auth_service.py    # Xử lý login Google, tạo JWT, get_current_user
│   └── chat_service.py    # Điều phối chat history CRUD
├── routers/
│   ├── __init__.py
│   ├── auth_router.py     # /auth/google/login, /auth/google/callback, /auth/me
│   └── chat_router.py     # /chats/... endpoints
├── utils/
│   ├── auth/
│   │   ├── auth_gg.py         # Google OAuth flow
│   │   ├── jwt.py             # Tạo/verify JWT
│   │   ├── check_exist.py     # Tìm user theo google_id/email/_id
│   │   ├── create_user.py     # Tạo user mới trong MongoDB
│   │   ├── update_last_login.py
│   │   └── create_history_chat.py  # Tạo document chat_history rỗng cho user mới
│   ├── chat/
│   │   ├── create_chat.py      # Tạo chat session mới
│   │   ├── get_chat.py        # Lấy 1 session
│   │   ├── update_chat.py     # Cập nhật title
│   │   ├── delete_chat.py     # Xoá session
│   │   ├── get_chat_history.py # Lấy toàn bộ history
│   │   ├── check_chat_owner.py # Kiểm tra quyền sở hữu
│   │   └── add_message.py     # Thêm message vào session
│   └── user/
│       ├── load_user.py        # Lấy user, load_user_public
│       └── load_history.py    # Lấy chat history
├── rag/
│   ├── engine.py           # Singleton: LLM, embedder, Pinecone, Neo4j
│   ├── steps.py            # B1, B2, B3 pipeline
│   ├── prompts.py          # System prompts
│   └── context.py         # Context formatting
└── data_import/
    ├── import_data_neo4j.py
    ├── import_data_pinecone.py
    └── requirements.txt
```

## Cài đặt

### 1. Backend

```bash
cd backend
python -m pip install -r requirements.txt
cp env_example .env
# Sửa .env: GROQ_API_KEY, NEO4J_*, PINECONE_API_KEY,
#            MONGODB_*, GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI,
#            JWT_SECRET_KEY
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

### Authentication

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET`  | `/auth/google/login` | Redirect sang Google OAuth |
| `GET`  | `/auth/google/callback` | Google redirect về, trả về JWT + user |
| `GET`  | `/auth/me` | Lấy thông tin user hiện tại (cần JWT) |

#### `GET /auth/me` — Response

```json
{
  "id": "...",
  "google_id": "...",
  "email": "user@gmail.com",
  "name": "Nguyen Van A",
  "picture": "https://...",
  "email_verified": true,
  "role": "user"
}
```

#### `GET /auth/google/callback` — Response

```json
{
  "user": { "id": "...", "google_id": "...", ... },
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "is_new_user": false
}
```

### Chat History (yêu cầu JWT)

Header: `Authorization: Bearer <access_token>`

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST`  | `/chats/` | Tạo chat session mới |
| `GET`   | `/chats/` | Lấy toàn bộ chat history |
| `GET`   | `/chats/{session_id}` | Lấy 1 chat session |
| `PATCH` | `/chats/{session_id}` | Cập nhật title |
| `DELETE`| `/chats/{session_id}` | Xoá session |
| `POST`  | `/chats/{session_id}/messages` | Thêm message |

#### `POST /chats/` — Request

```json
{ "title": "Hỏi về vượt đèn đỏ" }
```

#### `POST /chats/{session_id}/messages` — Request

```json
{
  "role": "user",
  "content": "Đi xe máy vượt đèn đỏ bị phạt bao nhiêu?",
  "sources": []
}
```

#### Chat Session Response

```json
{
  "session_id": "...",
  "user_id": "...",
  "title": "Hỏi về vượt đèn đỏ",
  "messages": [
    {
      "message_id": "...",
      "role": "user",
      "content": "Đi xe máy vượt đèn đỏ bị phạt bao nhiêu?",
      "sources": [],
      "created_at": "2026-09-03T..."
    },
    {
      "message_id": "...",
      "role": "assistant",
      "content": "Theo Điều 53 Nghị định 100...",
      "sources": [...],
      "created_at": "2026-09-03T..."
    }
  ],
  "created_at": "2026-09-03T...",
  "updated_at": "2026-09-03T...",
  "metadata": { "message_count": 2 }
}
```

### RAG Chat (public, không cần auth)

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET`  | `/` | Health check |
| `POST` | `/api/chat` | Hỏi luật giao thông |

#### `POST /api/chat` — Request

```json
{ "question": "...", "top_k": 5 }
```

#### `POST /api/chat` — Response

```json
{
  "answer": "Câu trả lời...",
  "sources": [
    {
      "citation": "Điều 30, Khoản 1",
      "score": 0.85,
      "context_block": "...",
      "law_document_type": "Nghị định",
      "law_document_number": "100/2019/NĐ-CP",
      "law_title": "Quy định về xử phạt...",
      "law_date_enacted": "2019-11-12"
    }
  ],
  "debug": {
    "reformulated_query": "...",
    "legal_domain": "...",
    "key_legal_terms": []
  }
}
```

## MongoDB Collections

| Collection | Mô tả |
|------------|-------|
| `users` | User document: google_id, email, name, role, timestamps |
| `chat_history` | 1 document/user, chứa mảng `chats` (sessions) |
| `chats[]` | Mỗi session: session_id, title, messages[], timestamps |

## Stack

| Layer | Tech |
|---|---|
| Vector DB | Pinecone (384 dim, cosine) |
| Graph DB | Neo4j Aura |
| Document DB | MongoDB |
| Embedding | sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (local) |
| LLM | Groq llama-3.3-70b-versatile |
| Backend | FastAPI + uvicorn |
| Frontend | React 18 + Vite |
| Auth | Google OAuth + JWT (HS256) |

## Environment Variables

```bash
# MongoDB
MONGODB_URI=mongodb+srv://...
MONGODB_USERNAME=...
MONGODB_PASSWORD=...
DATABASE_NAME=law_assistant

# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# JWT
JWT_SECRET_KEY=...
JWT_EXPIRE_MINUTES=60

# RAG
GROQ_API_KEY=...
PINECONE_API_KEY=...
NEO4J_URI=bolt://...
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j

# Frontend redirect
FRONTEND_URL=http://localhost:5500
```
