"""
Pinecone vector database connection singleton.

Usage:
    from database.pinecone_client import get_pinecone_client, get_index

    # Get the default index
    index = get_index("law-assistant")

    # Or use the client directly
    client = get_pinecone_client()
    index = client.Index("law-assistant")
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pinecone import Pinecone, ServerlessSpec

if TYPE_CHECKING:
    from pinecone import Index

from core.config import log, PINECONE_API_KEY


class PineconeClient:
    """Pinecone client wrapper with lazy initialization."""

    _instance: PineconeClient | None = None
    _client: Pinecone | None = None

    def __new__(cls) -> PineconeClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Pinecone:
        """Establish connection to Pinecone. Idempotent."""
        if self._client is None:
            log.info("Connecting Pinecone...")
            self._client = Pinecone(api_key=PINECONE_API_KEY)
            log.info("Pinecone client initialized successfully.")
        return self._client

    def get_index(self, index_name: str) -> Index:
        """Get a Pinecone index by name."""
        self.connect()
        return self._client.Index(index_name)

    def list_indexes(self) -> list[str]:
        """List all available indexes."""
        self.connect()
        return [idx.name for idx in self._client.list_indexes()]

    def index_exists(self, index_name: str) -> bool:
        """Check if an index exists."""
        self.connect()
        return index_name in self.list_indexes()

    def create_index_if_not_exists(
        self,
        index_name: str,
        dimension: int = 1536,
        metric: str = "cosine",
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> Index:
        """Create an index if it doesn't exist."""
        self.connect()

        if not self.index_exists(index_name):
            log.info("Creating Pinecone index '%s' (dim=%d)...", index_name, dimension)
            self._client.create_index(
                name=index_name,
                dimension=dimension,
                metric=metric,
                spec=ServerlessSpec(cloud=cloud, region=region),
            )
            log.info("Index '%s' created successfully.", index_name)
        else:
            log.info("Index '%s' already exists.", index_name)

        return self.get_index(index_name)

    @property
    def client(self) -> Pinecone:
        """Get the active client, connecting if necessary."""
        return self.connect()


def get_pinecone_client() -> PineconeClient:
    """Get or create the global Pinecone client instance."""
    return PineconeClient()


def get_index(index_name: str) -> Index:
    """Convenience function to get an index directly."""
    return get_pinecone_client().get_index(index_name)
