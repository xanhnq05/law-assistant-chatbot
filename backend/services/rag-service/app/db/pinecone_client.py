"""
Pinecone connection singleton - self-contained trong rag-service.

rag-service tự khởi tạo + dùng Pinecone; không phụ thuộc
service khác.

Usage:
    from db.pinecone_client import get_pinecone_client, get_index

    index = get_pinecone_client().get_index("law-rag-v1")
    res = index.query(vector=..., top_k=10)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pinecone import Pinecone, ServerlessSpec

if TYPE_CHECKING:
    from pinecone import Index

from app.core.config import PINECONE_API_KEY, PINECONE_INDEX_NAME, log


class PineconeClient:
    """Pinecone client wrapper với lazy initialization."""

    _instance: PineconeClient | None = None
    _client: Pinecone | None = None

    def __new__(cls) -> PineconeClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Pinecone:
        """Khởi tạo Pinecone client. Idempotent."""
        if self._client is None:
            log.info("Connecting Pinecone ...")
            self._client = Pinecone(api_key=PINECONE_API_KEY)
            log.info("Pinecone client initialized.")
        return self._client

    def get_index(self, index_name: str | None = None) -> Index:
        """Lấy index theo tên (mặc định = PINECONE_INDEX_NAME)."""
        self.connect()
        name = index_name or PINECONE_INDEX_NAME
        return self._client.Index(name)

    def list_indexes(self) -> list[str]:
        self.connect()
        return [idx.name for idx in self._client.list_indexes()]

    def index_exists(self, index_name: str | None = None) -> bool:
        name = index_name or PINECONE_INDEX_NAME
        return name in self.list_indexes()

    def create_index_if_not_exists(
        self,
        index_name: str | None = None,
        dimension: int = 384,
        metric: str = "cosine",
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> Index:
        """Tạo index nếu chưa có (idempotent)."""
        self.connect()
        name = index_name or PINECONE_INDEX_NAME

        if not self.index_exists(name):
            log.info("Creating Pinecone index '%s' (dim=%d) ...", name, dimension)
            self._client.create_index(
                name=name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(cloud=cloud, region=region),
            )
            log.info("Index '%s' created.", name)
        else:
            log.info("Index '%s' already exists.", name)

        return self.get_index(name)

    @property
    def client(self) -> Pinecone:
        return self.connect()


def get_pinecone_client() -> PineconeClient:
    """Singleton accessor."""
    return PineconeClient()


def get_index(index_name: str | None = None) -> Index:
    """Shortcut: lấy index trực tiếp."""
    return get_pinecone_client().get_index(index_name)
