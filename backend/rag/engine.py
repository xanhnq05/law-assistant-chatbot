"""
Heavy resources holder: LLM (Groq), embedding model, Pinecone client,
Neo4j driver. Created once at startup, closed at shutdown.
"""
from __future__ import annotations

from langchain_groq import ChatGroq
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

from core.config import (
    EMBEDDING_MODEL,
    GROQ_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    log,
)
from database import get_neo4j_client


class RagEngine:
    """Singleton wrapper that owns all heavy resources."""

    def __init__(self) -> None:
        self.llm: ChatGroq | None = None
        self.embedder: SentenceTransformer | None = None
        self.pinecone_idx = None
        self._neo_client = None

    def init(self) -> None:
        log.info("Loading LLM (Groq %s) ...", GROQ_MODEL)
        self.llm = ChatGroq(model=GROQ_MODEL, temperature=0)

        log.info("Loading embedding model %s ...", EMBEDDING_MODEL)
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)

        log.info("Connecting Neo4j ...")
        self._neo_client = get_neo4j_client()
        self._neo_client.connect()

        log.info("Connecting Pinecone ...")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        self.pinecone_idx = pc.Index(PINECONE_INDEX_NAME)

        log.info("RAG engine ready.")

    def close(self) -> None:
        if self._neo_client:
            self._neo_client.close()
            self._neo_client = None

    def get_neo_driver(self):
        if self._neo_client is None:
            return None
        return self._neo_client.driver

    def get_pinecone_index(self):
        return self.pinecone_idx

    def get_embedder(self):
        return self.embedder

    def get_llm(self):
        return self.llm

    def neo_session(self, database: str | None = None):
        """Convenience: open a Neo4j session against the configured database."""
        if self._neo_client is None:
            raise RuntimeError("RAG engine not initialized. Call init() first.")
        return self._neo_client.session(database=database)