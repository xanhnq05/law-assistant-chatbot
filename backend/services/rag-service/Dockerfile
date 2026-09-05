# syntax=docker/dockerfile:1.6
# ============================================================
# rag-service — RAG public endpoint (B1->B2->B3 pipeline)
#
# Build context PHẢI là thư mục `backend/` (không phải
# thư mục service) vì service này tái sử dụng code từ
# backend/core, backend/database, backend/rag.
#
# Build: docker build -f services/rag-service/Dockerfile -t rag-service backend
# ============================================================
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Cài build deps cho sentence-transformers / torch wheels (CPU)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# User non-root
RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /home/app

# Copy requirements và cài trước để cache layer
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy code RAG dùng chung + service riêng
COPY core ./core
COPY database ./database
COPY rag ./rag
COPY services/rag-service/service ./services/rag-service/service

# Đảm bảo PYTHONPATH đúng để 'core', 'rag', 'database' resolve được
ENV PYTHONPATH=/home/app:/home/app/services/rag-service

RUN chown -R app:app /home/app
USER app

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/', timeout=3).status==200 else 1)"

CMD ["uvicorn", "services.rag-service.service.main:app", \
     "--host", "0.0.0.0", "--port", "8003", \
     "--app-dir", "/home/app"]
