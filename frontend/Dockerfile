# syntax=docker/dockerfile:1.6
# ============================================================
# Frontend (Vite + React) — multi-stage build
# Stage 1: build static assets ra /dist
# Stage 2: serve qua nginx:alpine (port 80 nội bộ container)
#
# Cách dùng:
#   - Khi chạy bằng docker compose (root project), nginx-gateway sẽ
#     proxy đến service `frontend` ở cổng 80 nội bộ.
#   - Truy cập web: http://localhost:8080
#
# Lưu ý: khi build, VITE_API_URL được truyền qua --build-arg.
# Frontend bundle sẽ gọi thẳng nginx-gateway (cùng network).
# ============================================================

# ===== Stage 1: build =====
FROM node:20-alpine AS builder

WORKDIR /home/app

# Cài deps trước để tận dụng Docker layer cache
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy toàn bộ source + build production
COPY . .

# Khi build, VITE_API_URL được nhúng vào bundle.
# Trình duyệt chạy trên host gọi nginx-gateway qua localhost:8080,
# nginx sẽ proxy /auth, /chats sang đúng service backend.
# (Đây là URL browser gọi, không phải URL nội bộ container.)
ARG VITE_API_URL=http://localhost:8080
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# ===== Stage 2: serve static qua nginx =====
FROM nginx:1.27-alpine

# Copy bundle Vite đã build sang nginx html dir
COPY --from=builder /home/app/dist /usr/share/nginx/html

# Healthcheck đơn giản (kiểm tra nginx còn sống)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ > /dev/null || exit 1

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]