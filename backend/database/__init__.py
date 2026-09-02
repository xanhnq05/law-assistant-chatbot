"""
Database connection module.

Provides unified access to:
- Neo4j (graph database)
- MongoDB (document database)
- Pinecone (vector database)
"""
from __future__ import annotations

from database.mongo_client import MongoDBClient, get_mongo_client, get_database
from database.neo4j_client import Neo4jClient, get_neo4j_client
from database.pinecone_client import PineconeClient, get_pinecone_client, get_index

__all__ = [
    "MongoDBClient",
    "get_mongo_client",
    "get_database",
    "Neo4jClient",
    "get_neo4j_client",
    "PineconeClient",
    "get_pinecone_client",
    "get_index",
]
