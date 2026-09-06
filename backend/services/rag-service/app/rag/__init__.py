"""RAG package - 7-step pipeline implementation.

Sub-modules:
    orchestrator.py   : LangChain pipeline runner (chain state)
    steps/
        ├── cleaner.py        : B2 - Query Cleaner
        ├── embedding.py      : B3 - Embedding
        ├── retrieval.py      : B4 - Hybrid Retrieval (Pinecone + Neo4j)
        ├── context_builder.py: B5 - Context Builder
        ├── generator.py      : B6 - LLM Generation
        └── verification.py   : B7 - Symbolic Verification
    prompts/
        ├── cleaner.py        : Prompt cho query cleaner
        ├── generator.py      : Prompt cho answer generation
        └── verifier.py       : Prompt cho symbolic verifier
    context.py         : Citation + LLM context block helpers
    engine.py          : Heavy resources holder (LLM, embedder, DB clients)
"""
