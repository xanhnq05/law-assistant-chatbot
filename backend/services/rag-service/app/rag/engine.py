"""
Heavy resources holder: LLM (Groq), embedding model, Pinecone client,
Neo4j driver. Created once at startup, closed at shutdown.

Đây là "container" chứa toàn bộ resource nặng - được khởi tạo 1 lần khi
service start và tái sử dụng xuyên suốt vòng đời của process.
"""
from __future__ import annotations

from langchain_groq import ChatGroq
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

from app.core.config import (
    EMBEDDING_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MODEL_FAST,
    GROQ_TEMPERATURE,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    log,
)
from app.db.neo4j_client import get_neo4j_client


class RagEngine:
    """Singleton wrapper owning all heavy resources for the 7-step pipeline."""

    def __init__(self) -> None:
        # B6 - Generation LLM (Groq main model).
        self.llm: ChatGroq | None = None
        # B7 - Verifier LLM (Groq fast model - đủ tốt cho symbolic check).
        self.verifier_llm: ChatGroq | None = None
        # B3 - Embedding model.
        self.embedder: SentenceTransformer | None = None
        # B4 - Pinecone vector DB.
        self.pinecone_idx = None
        # B4 - Neo4j graph DB.
        self._neo_client = None

    # ============================================================
    # INIT / CLOSE
    # ============================================================
    def init(self) -> None:
        if not GROQ_API_KEY:
            raise RuntimeError("Missing GROQ_API_KEY in env")
        log.info("Loading LLM (Groq main=%s, verifier=%s) ...", GROQ_MODEL, GROQ_MODEL_FAST)
        self.llm = ChatGroq(
            model=GROQ_MODEL,
            temperature=GROQ_TEMPERATURE,
            api_key=GROQ_API_KEY,
        )
        self.verifier_llm = ChatGroq(
            model=GROQ_MODEL_FAST,
            temperature=0,
            api_key=GROQ_API_KEY,
        )

        log.info("Loading embedding model %s ...", EMBEDDING_MODEL)
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)

        log.info("Connecting Neo4j ...")
        self._neo_client = get_neo4j_client()
        self._neo_client.connect()

        log.info("Connecting Pinecone (index=%s) ...", PINECONE_INDEX_NAME)
        pc = Pinecone(api_key=PINECONE_API_KEY)
        self.pinecone_idx = pc.Index(PINECONE_INDEX_NAME)

        log.info("RAG engine ready.")

    def close(self) -> None:
        if self._neo_client:
            self._neo_client.close()
            self._neo_client = None

    # ============================================================
    # ACCESSORS
    # ============================================================
    def get_neo_driver(self):
        if self._neo_client is None:
            return None
        return self._neo_client.driver

    def get_pinecone_index(self):
        return self.pinecone_idx

    def get_embedder(self):
        return self.embedder

    def get_llm(self):
        """B6 - answer generation."""
        return self.llm

    def get_verifier_llm(self):
        """B7 - symbolic verifier."""
        return self.verifier_llm

    def neo_session(self, database: str | None = None):
        """Convenience: open a Neo4j session against the configured database."""
        if self._neo_client is None:
            raise RuntimeError("RAG engine not initialized. Call init() first.")
        return self._neo_client.session(database=database)
