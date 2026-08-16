"""
Heavy resources holder: LLM (Groq), embedding model, Pinecone client,
Neo4j driver. Created once at startup, closed at shutdown.
"""
from __future__ import annotations

from langchain_groq import ChatGroq
from neo4j import GraphDatabase
from pinecone import Pinecone
from sentence_transformers import SentenceTransformer

from config import (
    EMBEDDING_MODEL,
    GROQ_MODEL,
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    log,
)


class RagEngine:
    """Singleton wrapper that owns all heavy resources."""

    def __init__(self) -> None:
        self.llm: ChatGroq | None = None
        self.embedder: SentenceTransformer | None = None
        self.pinecone_idx = None
        self.neo_driver = None

    def init(self) -> None:
        log.info("Loading LLM (Groq %s) ...", GROQ_MODEL)
        self.llm = ChatGroq(model=GROQ_MODEL, temperature=0)

        log.info("Loading embedding model %s ...", EMBEDDING_MODEL)
        self.embedder = SentenceTransformer(EMBEDDING_MODEL)

        log.info("Connecting Neo4j ...")
        self.neo_driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)
        )
        self.neo_driver.verify_connectivity()

        log.info("Connecting Pinecone ...")
        pc = Pinecone(api_key=PINECONE_API_KEY)
        self.pinecone_idx = pc.Index(PINECONE_INDEX_NAME)

        log.info("RAG engine ready.")

    def close(self) -> None:
        if self.neo_driver:
            self.neo_driver.close()

    def get_neo_driver(self):
        return self.neo_driver

    def get_pinecone_index(self):
        return self.pinecone_idx

    def get_embedder(self):
        return self.embedder

    def get_llm(self):
        return self.llm

    def neo_session(self):
        """Convenience: open a Neo4j session against the configured database."""
        return self.neo_driver.session(database=NEO4J_DATABASE)