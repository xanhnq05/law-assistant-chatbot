# Frontend - Law RAG Chatbot

Giao diện chat đơn giản gửi câu hỏi tới backend FastAPI.

## Yêu cầu

- Node.js >= 18

## Cài đặt

```bash
cd frontend
npm install
```

## Chạy dev

Đảm bảo backend đang chạy ở `http://127.0.0.1:8000` rồi:

```bash
npm run dev
```

Mở `http://127.0.0.1:5173`.

## Cấu trúc

```
frontend/
├── index.html
├── package.json
├── vite.config.js      # Proxy /api -> backend :8000
└── src/
    ├── main.jsx        # Entry
    ├── App.jsx         # Component chat
    ├── App.css
    └── index.css
```

API endpoint duy nhất: `POST /api/chat` → `{question, top_k}` → `{answer, sources, debug}`
