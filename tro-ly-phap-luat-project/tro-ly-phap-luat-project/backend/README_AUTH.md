# Auth thật bằng Google OAuth (Authorization Code Flow) + Mongo + JWT

## 1. Thêm vào `config.py` hiện có của bạn

`mongo_client.py` bạn gửi đang import `log, MONGODB_PASSWORD, MONGODB_URI, MONGODB_USERNAME, DATABASE_NAME`
từ `config.py` — mình **không đụng vào phần đó**. Chỉ cần thêm đoạn sau vào cuối `config.py`:

```python
import os

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# Domain của frontend (nơi user sẽ được redirect về sau khi đăng nhập Google xong)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5500")
```

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `JWT_SECRET_KEY` bạn
đã có sẵn trong `.env` rồi — chỉ cần thêm dòng `FRONTEND_URL=http://localhost:5500` (hoặc domain
frontend thật của bạn) vào `.env` là đủ.

## 2. Cài thêm thư viện

```bash
pip install fastapi "uvicorn[standard]" pyjwt httpx python-dotenv
```

(`pymongo` bạn đã có sẵn vì đang dùng trong `mongo_client.py`.)

## 3. Cấu trúc mới thêm vào

```
auth/
  schemas.py       # Pydantic models
  jwt_handler.py    # tạo/giải mã JWT (thuần, không phụ thuộc FastAPI)
  dependencies.py   # get_current_user, require_role -> dùng ở mọi router cần login
  google_oauth.py   # nói chuyện trực tiếp với Google (build URL, đổi code, lấy userinfo)
  service.py        # điều phối: Google -> tìm/tạo user trong Mongo -> phát JWT
  router.py         # /auth/google/login, /auth/google/callback, /auth/me
chat/
  repository.py     # Mongo: collections "chats" và "messages"
  llm.py            # ⚠️ stub — nối vào chain LangChain/Groq/Neo4j/Pinecone thật của bạn ở đây
  router.py         # /chats, /chats/{id}, /chats/{id}/messages
main.py             # gắn router vào FastAPI app
```

## 4. Luồng chạy thực tế

1. Frontend cho user bấm nút "Đăng nhập Google" → **redirect thẳng trình duyệt** tới
   `GET http://localhost:8000/auth/google/login` (không phải gọi bằng `fetch`, vì cần
   trình duyệt thật sự chuyển trang sang Google).
2. Server tạo `state` ngẫu nhiên, lưu vào cookie, redirect sang trang Google.
3. User chọn tài khoản, đồng ý quyền → Google redirect về đúng
   `GOOGLE_REDIRECT_URI` (`http://localhost:8000/auth/google/callback`) kèm `?code=...&state=...`.
4. Server đối chiếu `state`, đổi `code` lấy `access_token` (cần `client_secret`, chỉ làm được ở server),
   gọi Google lấy `sub/email/name/picture` thật.
5. **TH1 - chưa có tài khoản**: tạo document mới trong collection `users` (`role: "user"`).
   **TH2 - đã có**: chỉ cập nhật lại name/picture/email mới nhất, không tạo trùng.
6. Server phát JWT nội bộ (`sub`, `role`, `email`), redirect trình duyệt về
   `FRONTEND_URL/#token=<jwt>`.
7. Frontend đọc `window.location.hash`, lưu JWT (biến JS/`sessionStorage`), xóa khỏi thanh địa chỉ,
   rồi dùng `Authorization: Bearer <jwt>` cho mọi API sau đó (`/auth/me`, `/chats`, ...).
8. `/chats/*` dùng `Depends(require_role("user"))` để vừa xác thực vừa kiểm tra role trong 1 bước —
   lịch sử chat được lưu vào 2 collection Mongo `chats` (mỗi hồ sơ hội thoại) và `messages`
   (từng đoạn chat, tham chiếu `chat_id`), luôn gắn theo `user_id` lấy từ JWT chứ không tin
   giá trị do client tự gửi lên.

## 5. Chạy thử

```bash
uvicorn main:app --reload --port 8000
```

Mở trình duyệt vào: `http://localhost:8000/auth/google/login`
(nhớ thêm chính email Google của bạn vào **OAuth consent screen → Test users**
trên Google Cloud Console nếu app đang ở chế độ Testing).

Sau khi đăng nhập xong, bạn sẽ được redirect về `FRONTEND_URL/#token=...`.
Copy token đó test tiếp:

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token vừa copy>"

curl http://localhost:8000/chats \
  -H "Authorization: Bearer <token vừa copy>"
```

## 6. Việc còn cần bạn tự làm

- Nối `chat/llm.py` vào chain LangChain/Groq/Neo4j/Pinecone thật (hiện đang trả lời giả).
- Trong `main.py`, đổi `allow_origins=[FRONTEND_URL]` thành domain thật khi deploy production
  (đừng để `*` một khi đã set `allow_credentials=True`).
- Cân nhắc thêm refresh token nếu muốn JWT hết hạn xong tự làm mới mà không bắt user đăng nhập lại.
