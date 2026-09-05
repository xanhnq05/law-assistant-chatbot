# syntax=docker/dockerfile:1.6
# ============================================================
# Frontend — Trợ Lý Pháp Luật (vanilla HTML/CSS/JS)
# Serve qua nginx, image rất nhỏ (~30 MB)
#
# Lưu ý: file config.js chứa URL backend (mặc định
# http://localhost:8080 cho Docker). Khi muốn deploy lên
# domain khác, sửa trực tiếp frontend/config.js trước khi build.
# ============================================================
FROM nginx:1.27-alpine

# Xoá default config của nginx
RUN rm /etc/nginx/conf.d/default.conf

# Copy nginx config riêng
COPY nginx.conf /etc/nginx/conf.d/app.conf

# Copy static files
COPY index.html style.css script.js config.js /usr/share/nginx/html/

# Healthcheck dùng wget có sẵn trong alpine
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1

EXPOSE 80
