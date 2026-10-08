# syntax=docker/dockerfile:1.6
# ============================================================
# admin-frontend — Admin Document Management SPA
# ============================================================
FROM node:22-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# -------- runtime --------
FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ || exit 1
