# Admin SPA (Trợ Lý Pháp Luật)

SPA riêng cho admin quản lý văn bản pháp luật — chạy port **5174**, không qua nginx.

## Setup

```powershell
cd frontend/admin
npm install
npm run dev
# Mở http://localhost:5174
```

## Tech stack

- React 19 + TypeScript + Vite
- Zustand (auth state)
- Axios (multi-service)
- React Router 7
- Tailwind CSS 3
- Sonner (toast)

## Cấu trúc

```
src/
├── App.tsx                    # Routing + auth guard
├── main.tsx
├── index.css                  # Tailwind + theme variables
├── lib/
│   ├── services.ts            # axios authApi + docApi
│   └── utils.ts
├── services/
│   ├── authService.ts         # Gọi auth-service backend (Google OAuth)
│   └── documentService.ts     # Gọi document-service:8004
├── store/useAdminAuth.ts      # Zustand store (adminToken + user + role check)
├── pages/
│   ├── LoginPage.tsx          # OAuth Google button
│   └── UploadPage.tsx         # Drag-drop upload + metadata form + list
└── components/
    └── FileDropzone.tsx       # Drag-drop multi-file (PDF/DOCX)
```

## Auth flow

1. User mở `http://localhost:5174/upload`
2. Nếu chưa có adminToken → redirect `/login`
3. Click "Đăng nhập với Google" → redirect sang `auth-service:8001/auth/google/login`
4. Google OAuth → callback → redirect về `http://localhost:5174/#token=<jwt>`
5. App parse token, lưu vào localStorage(`adminToken`)
6. Gọi `/auth/me` → check role. Nếu `role !== "admin"` → đẩy ra + error.

## Upload flow (Phase 1)

1. Admin kéo thả PDF/DOCX (có thể nhiều file cho cùng 1 Document)
2. Điền metadata: title, số văn bản, năm, status, ngày ban hành/hiệu lực, cơ quan
3. Nếu `AMENDMENT` → chọn Document gốc (`amends_document_id`)
4. Submit → gọi `POST /admin/documents/upload` (multipart)
5. **Submit bị chặn cho đến khi response trả về** (nút disabled + spinner)
6. Sau khi xong → reset form + refresh list + toast thông báo

## Tích hợp backend

| Service              | URL                                  | Env var                       |
|----------------------|--------------------------------------|-------------------------------|
| auth-service         | http://localhost:8001                | VITE_AUTH_SERVICE_URL         |
| document-service     | http://localhost:8004                | VITE_DOCUMENT_SERVICE_URL     |

Cấu hình trong `.env.local`:
```
VITE_AUTH_SERVICE_URL=http://localhost:8001
VITE_DOCUMENT_SERVICE_URL=http://localhost:8004
```

## Phase 2+ (sẽ làm)

- Pipeline progress (real-time status updates)
- Admin Review page (AMBIGUOUS amendment mapping)
- Document detail page (xem chapters/articles sau khi parse xong)
- Delete + metadata edit
- Bulk operations
