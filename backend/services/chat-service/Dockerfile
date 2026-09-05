# syntax=docker/dockerfile:1.6
# ============================================================
# chat-service — CRUD chat session + proxy sang rag-service
# ============================================================
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app app

WORKDIR /home/app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app

RUN chown -R app:app /home/app
USER app

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8002/', timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
