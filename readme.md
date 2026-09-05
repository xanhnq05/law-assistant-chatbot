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
