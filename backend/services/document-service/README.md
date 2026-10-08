# document-service

Admin Document Management microservice cho Trợ Lý Pháp Luật.

## Mục đích
- Cho admin upload PDF/DOCX văn bản pháp luật.
- Phase 1 (current): upload lên Supabase Storage, lưu metadata vào Mongo, dry-run pipeline.
- Phase 2+ (sẽ làm sau): parse → validate → import Neo4j → embed → upsert Pinecone.

## Tech stack
- FastAPI + Uvicorn (port 8004)
- MongoDB (cùng cluster với auth-service)
- Supabase Storage (PDF/DOCX + JSON intermediate)
- JWT verify-only (cùng secret với auth-service)

## Cấu trúc thư mục
```
app/
├── core/config.py            # Env loading, logging
├── db/
│   ├── mongo_client.py       # Singleton Mongo
│   └── supabase_client.py    # Singleton Supabase (service-role)
├── repositories/
│   ├── jwt_helper.py         # Decode JWT
│   ├── user_repository.py    # Đọc role từ Mongo
│   └── auth_guard.py         # get_current_user + require_admin
├── schemas/document.py       # Pydantic models
├── services/document_upload_service.py  # Phase 1 dry-run
├── api/routes/admin.py       # /admin/health, /admin/me, /admin/documents/*
└── output/
    ├── document/             # JSON intermediate cho documents
    └── relationship/         # JSON intermediate cho relationships
```

## Chạy local
```powershell
cd backend/services/document-service
$env:PYTHONPATH = "."
python -m uvicorn app.main:app --reload --port 8004
```

## Endpoints

| Method | Path                          | Auth        | Mô tả |
|--------|-------------------------------|-------------|-------|
| GET    | /                             | public      | Health |
| GET    | /admin/health                 | public      | Admin health |
| GET    | /admin/me                     | JWT         | Current user (id, email, role) |
| POST   | /admin/documents/upload       | JWT + admin | Upload PDF/DOCX + metadata (multipart) |
| GET    | /admin/documents              | JWT + admin | List documents admin đã tạo |

## Test
```powershell
# 1. Tạo admin user test trong Mongo
python tests/setup_test_admin.py

# 2. Chạy e2e test
python tests/test_admin_e2e.py
```

## Supabase setup

Cần tạo 2 bucket trên Supabase Storage (Service: tro-ly-luat, Region: gần VN):

| Bucket       | Mục đích                          | Quyền |
|--------------|-----------------------------------|-------|
| `documents`  | PDF/DOCX upload từ admin          | private |
| `json`       | JSON intermediate (Phase 2+)      | private |

Service-role key (`SUPABASE_SECRET_KEY`) dùng để bypass RLS khi upload.

## Biến môi trường cần có

Xem [backend/.env](../../.env) — section "DOCUMENT SERVICE":
- `DOCUMENT_SERVICE_PORT=8004`
- `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_BUCKET_DOCUMENTS=documents`
- `SUPABASE_BUCKET_JSON=json`
- `JWT_SECRET_KEY` (shared với auth-service)
- `MONGODB_URI`, `MONGODB_USERNAME`, `MONGODB_PASSWORD`, `DATABASE_NAME`
- `ADMIN_FRONTEND_URL=http://localhost:5174`
- Optional: `ADMIN_EMAILS_ALLOWLIST` (comma-separated email được promote admin)
