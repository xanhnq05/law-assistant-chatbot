"""Pinecone connection singleton cho document-service.

Phase 2+: lift toàn bộ logic từ `data_import/import_data_pinecone.py`.
Phase 1 chỉ cần stub.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pinecone import Pinecone, ServerlessSpec

if TYPE_CHECKING:
    from pinecone import Index

from app.core.config import log

PINECONE_API_KEY = None
PINECONE_INDEX_NAME = "law-rag-v1"


class PineconeClient:
    _instance: PineconeClient | None = None
    _client: Pinecone | None = None

    def __new__(cls) -> PineconeClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Pinecone:
        if self._client is None:
            if not PINECONE_API_KEY:
                raise RuntimeError("Pinecone chưa được kích hoạt cho document-service (Phase 2+).")
            log.info("Connecting Pinecone ...")
            self._client = Pinecone(api_key=PINECONE_API_KEY)
            log.info("Pinecone client initialized.")
        return self._client


def get_pinecone_client() -> PineconeClient:
    return PineconeClient()


def get_index(index_name: str | None = None) -> Index:
    return get_pinecone_client()._client.Index(index_name or PINECONE_INDEX_NAME)
