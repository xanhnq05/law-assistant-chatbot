"""rag-service app package.

Pipeline 7 bước (theo kiến trúc image 1 & 2):
  B1. LangChain Orchestration (chain runner + state)
  B2. Query Cleaner (chuẩn hoá text câu hỏi)
  B3. Embedding (sentence-transformers)
  B4. Hybrid Retrieval (Pinecone vector + Neo4j graph traversal)
  B5. Context Builder (chuẩn hoá block cho LLM)
  B6. LLM Generation (Groq)
  B7. Symbolic Verification (hybrid rule-based + LLM-as-Judge)

Cấu trúc:
    app/
    ├── api/            # FastAPI routes
    ├── core/           # Config + models + state
    ├── db/             # Pinecone, Neo4j clients
    ├── rag/            # Toàn bộ pipeline 7 bước
    │   ├── orchestrator.py   # LangChain state graph
    │   ├── steps/            # Từng bước trong pipeline
    │   ├── prompts/          # System prompts cho mỗi step
    │   └── ...
    └── verification/    # Symbolic verification (B7)
"""

__version__ = "2.0.0"
