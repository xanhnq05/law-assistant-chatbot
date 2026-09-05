# Trợ Lý Pháp Luật - Frontend

Frontend thuần HTML + CSS + JavaScript (vanilla), không cần bundler.

## Chạy local

Yêu cầu: [Python 3](https://www.python.org/) đã cài.

```bash
cd frontend
python -m http.server 5500
```

Mở trình duyệt tại: [http://localhost:5500](http://localhost:5500)

Hoặc nếu đã cài `npm`:

```bash
npm start
```

## Cấu trúc

```
frontend/
├── index.html     # Trang chính + template cho login / app shell
├── style.css      # Toàn bộ style
├── script.js      # Logic gọi API + render UI
├── package.json   # Script tiện cho npm start
└── README.md
```

## Cấu hình

Mặc định frontend gọi backend ở `http://localhost:8000`. Để đổi, sửa hằng số `API_BASE_URL` trong `script.js`:

```js
const API_BASE_URL = "https://api.tro-ly-phap-luat.vn";
```

## Liên kết với backend

| Endpoint | Mục đích |
|----------|----------|
| `GET  /auth/google/login` | Bắt đầu OAuth flow |
| `GET  /auth/google/callback` | Google redirect về, backend redirect tiếp về frontend kèm `#token=...` |
| `GET  /auth/me` | Lấy thông tin user hiện tại (cần JWT) |
| `GET  /chats` | Danh sách chat session |
| `POST /chats` | Tạo chat session mới |
| `GET  /chats/{id}` | Lấy 1 chat session |
| `DELETE /chats/{id}` | Xoá chat session |
| `POST /chats/{id}/messages` | Gửi message - backend tự gọi RAG trả lời |
| `POST /api/chat` | Public RAG (không cần auth) |

Frontend sẽ tự lưu JWT vào `sessionStorage` sau khi OAuth thành công.

## Luồng hoạt động

1. Người dùng bấm "Đăng nhập bằng Gmail" → redirect tới `http://localhost:8000/auth/google/login`
2. Backend redirect sang Google OAuth
3. Google xác thực xong → redirect về `http://localhost:8000/auth/google/callback`
4. Backend tạo JWT → redirect về `http://localhost:5500/#token=<JWT>`
5. Frontend đọc token từ hash, lưu vào `sessionStorage`, gọi `/auth/me` để hiển thị user
6. Người dùng hỏi luật → frontend gọi `POST /chats/{id}/messages` → backend tự sinh câu trả lời từ RAG (Pinecone + Neo4j + Groq LLM)
