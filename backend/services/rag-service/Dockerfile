# syntax=docker/dockerfile:1.6
# ============================================================
# rag-service — 7-step RAG pipeline (B1-B7)
#
# rag-service là SELF-CONTAINED microservice:
#   - Mọi code (config, db clients, rag logic) nằm trong `app/`.
#   - KHÔNG phụ thuộc file nào nằm ngoài `services/rag-service/`.
#   - Build context = thư mục service (chứ không phải backend/).
#
# Build:
#   docker build -f services/rag-service/Dockerfile -t rag-service services/rag-service
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
COPY requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Copy TOÀN BỘ service (self-contained)
COPY app ./app

# PYTHONPATH để 'app' module resolve được
# Khi uvicorn chạy `app.main:app`, Python tìm package `app` ở /home/app/
ENV PYTHONPATH=/home/app

RUN chown -R app:app /home/app
USER app

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8003", \
     "--app-dir", "/home/app"]
