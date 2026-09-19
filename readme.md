# Trợ Lý Pháp Luật - RAG Chatbot

Hệ thống chatbot pháp luật Việt Nam (Google OAuth + MongoDB + RAG pipeline).

## Chạy bằng Docker

Yêu cầu: [Docker Desktop](https://www.docker.com/products/docker-desktop/) đã cài.

### 1. Chuẩn bị `.env`

File `.env` ở thư mục gốc dự án đã có sẵn secret — cứ dùng luôn. Nếu muốn thay đổi, sửa trực tiếp file đó (KHÔNG commit lên git).

Đảm bảo 2 URL Google OAuth trong `.env` đã được add vào Google Cloud Console → Authorized redirect URIs:
```
http://localhost:8080/auth/google/callback
```

### 2. Build & chạy

```powershell
docker compose up --build
```

Lần đầu sẽ mất ~5 phút để build image (chủ yếu do chat-service cài pymongo + authlib).

### 3. Truy cập

| URL | Dùng để |
|---|---|
| http://localhost:8080 | Frontend (UI chat) |
| http://localhost:8001/docs | Swagger auth-service |
| http://localhost:8002/docs | Swagger chat-service |

### 4. Các lệnh thường dùng

```powershell
# Xem log tất cả container
docker compose logs -f

# Log riêng 1 service
docker compose logs -f chat-service

# Rebuild 1 service sau khi sửa code
docker compose up --build auth-service

# Dừng (giữ image, dữ liệu)
docker compose down

# Dừng + xoá image (clean slate)
docker compose down --rmi all
```

### 5. Lưu ý

- **rag-service đang tắt** trong `docker-compose.yml`. Khi đó:
  - `chat-service` không trả lời được câu hỏi (sẽ trả fallback "RAG chưa sẵn sàng").
  - Frontend gọi `/api/chat` sẽ nhận 503.
  - Khi muốn bật lại: mở `docker-compose.yml`, uncomment block `rag-service` + bật `depends_on` trong chat-service + bật block `/api/` trong `frontend/nginx.conf`.

- **JWT_SECRET_KEY** phải giống nhau giữa `auth-service` và `chat-service`. File `.env` ở root + các `.env` trong từng service đã được set đồng bộ.

---

## Chạy bằng Terminal (mở từng cmd riêng — không dùng Docker)

Yêu cầu:
- Python 3.10+
- Node.js 18+
- File `.env` ở `backend/` đã có sẵn (copy từ `.env.example` nếu chưa có)

### 0. Cài dependencies (chỉ làm 1 lần đầu)

Mở 4 terminal riêng biệt, mỗi cái cd vào thư mục tương ứng:

```powershell
# Terminal 1 — auth-service
cd backend\services\auth-service
pip install -r requirements.txt

# Terminal 2 — chat-service
cd backend\services\chat-service
pip install -r requirements.txt

# Terminal 3 — rag-service (chạy nếu muốn dùng RAG, nếu không thì bỏ qua)
cd backend\services\rag-service
pip install -r requirements.txt

# Terminal 4 — frontend
cd frontend
npm install
```

### 1. Chạy 3 backend services (mỗi cái 1 terminal riêng)

```powershell
# Terminal 1 — auth-service  (port 8001)
cd backend\services\auth-service
python -m uvicorn app.main:app --reload --port 8001
```

```powershell
# Terminal 2 — chat-service  (port 8002)
cd backend\services\chat-service
python -m uvicorn app.main:app --reload --port 8002
```

```powershell
# Terminal 3 — rag-service  (port 8003) — optional, cần cho Guest chat có câu trả lời
cd backend\services\rag-service
python -m uvicorn app.main:app --reload --port 8003
```

> Tip: cờ `--reload` tự restart server khi code thay đổi. Cổng khác nhau để chạy song song.

### 2. Chạy frontend

```powershell
# Terminal 4
cd frontend
npm run dev
```

Frontend sẽ chạy ở `http://localhost:5173`.

### 3. Truy cập các service

| URL | Dùng để |
|---|---|
| http://localhost:5173 | Frontend (UI chat) |
| http://localhost:8001/docs | Swagger auth-service |
| http://localhost:8002/docs | Swagger chat-service |
| http://localhost:8003/docs | Swagger rag-service |

### 4. File `.env.local` của frontend

Frontend tự đọc URL từng service từ `frontend/.env.local` (đã có sẵn):

```
VITE_AUTH_SERVICE_URL=http://localhost:8001
VITE_CHAT_SERVICE_URL=http://localhost:8002
VITE_RAG_SERVICE_URL=http://localhost:8003
```

Nếu muốn đi qua nginx gateway (8080) thì đổi cả 3 dòng trên thành `http://localhost:8080`.

### 5. Lưu ý khi chạy manual

- Mỗi service phải chạy ở đúng cổng đã khai báo trong `.env.local` của frontend, không thì request sẽ fail.
- **JWT_SECRET_KEY** trong `backend/.env` phải giống nhau giữa `auth-service` và `chat-service` (đã set sẵn).
- MongoDB connection string trong `backend/.env` (`MONGODB_URI`) dùng chung cho cả 3 service.
- Nếu 1 service không cần (vd: rag), các service còn lại vẫn chạy độc lập — frontend vẫn vào được chat, chỉ RAG không trả lời được.

