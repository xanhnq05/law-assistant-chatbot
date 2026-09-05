# Trợ Lý Pháp Luật — Cấu trúc dự án

```
tro-ly-phap-luat-project/
│
├── frontend/                    # Web tĩnh (HTML/CSS/JS thuần), không cần build
│   ├── index.html                #   khung trang, nạp font + lucide icon + script.js
│   ├── style.css                 #   toàn bộ giao diện (theme tối, navy/vàng/cam/đỏ)
│   └── script.js                 #   state, render UI, gọi API backend (auth + chat)
│
└── backend/                     # API FastAPI + MongoDB
    ├── main.py                   #   khởi tạo FastAPI app, gắn router, CORS
    ├── mongo_client.py           #   (của bạn) singleton kết nối MongoDB
    ├── config.py                 #   ⚠️ CHƯA CÓ Ở ĐÂY — dùng file config.py bạn đang có,
    │                              #      chỉ cần thêm các biến mới (xem README_AUTH.md)
    ├── requirements.txt          #   thư viện cần cài thêm cho phần auth/chat
    ├── .env.example               #   danh sách biến môi trường cần có (không chứa giá trị thật)
    ├── README_AUTH.md             #   hướng dẫn chi tiết luồng đăng nhập + cách test
    │
    ├── auth/                     #   MỌI THỨ liên quan đăng nhập/JWT nằm ở đây
    │   ├── schemas.py             #     Pydantic models (GoogleUserInfo, UserOut, ...)
    │   ├── jwt_handler.py         #     tạo/giải mã JWT (thuần, không phụ thuộc FastAPI)
    │   ├── dependencies.py        #     get_current_user, require_role() -> dùng ở router khác
    │   ├── google_oauth.py        #     build URL đăng nhập, đổi code lấy token, lấy userinfo
    │   ├── service.py             #     điều phối: Google -> tìm/tạo user trong Mongo -> phát JWT
    │   └── router.py              #     /auth/google/login, /auth/google/callback, /auth/me
    │
    └── chat/                     #   Lưu & xử lý lịch sử chat
        ├── repository.py          #     Mongo: collection "chats" (hồ sơ) + "messages" (từng đoạn)
        ├── llm.py                 #     ⚠️ stub — nối vào chain LangChain/Groq/Neo4j/Pinecone thật
        └── router.py              #     /chats, /chats/{id}, /chats/{id}/messages
```

## Frontend và backend nói chuyện với nhau qua đâu?

- `frontend/script.js` có hằng số `API_BASE_URL` (mặc định `http://localhost:8000`) — trỏ tới backend.
- `backend/.env` có biến `FRONTEND_URL` (mặc định `http://localhost:5500`) — trỏ ngược lại tới frontend,
  dùng để redirect sau khi đăng nhập Google xong và để cấu hình CORS.
- Hai giá trị này **phải khớp** với cổng thật bạn chạy từng bên.

## Chạy thử toàn bộ

```bash
# Terminal 1 — backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend (không mở file trực tiếp, phải qua server)
cd frontend
python3 -m http.server 5500
```

Mở `http://localhost:5500`, bấm "Đăng nhập bằng Gmail". Chi tiết luồng OAuth từng bước
xem trong `backend/README_AUTH.md`.

## Việc bạn cần tự làm khi ráp vào dự án thật

1. Đặt `config.py` gốc của bạn (đã có Neo4j/Pinecone/Groq/LangSmith) vào `backend/`,
   rồi thêm các biến mới liệt kê trong `backend/README_AUTH.md`.
2. Merge `requirements.txt` này với requirements hiện có của dự án.
3. Nối `backend/chat/llm.py` vào pipeline RAG thật (hiện đang trả lời giả để demo luồng).
