"""
B3 - Embedding câu hỏi.

Sử dụng sentence-transformers đã load sẵn trong engine.embedder.
Trả về vector normalized (cho cosine similarity).
"""
from __future__ import annotations

from typing import Any


def step_embed_question(engine, text: str) -> list[float]:
    """Encode 1 câu text thành vector float normalized."""
    if engine.get_embedder() is None:
        raise RuntimeError("Embedder chưa được khởi tạo.")
    vec = engine.get_embedder().encode(
        [text],
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )[0].tolist()
    return vec


def step_embed_batch(engine, texts: list[str]) -> list[list[float]]:
    """Encode nhiều text cùng lúc (dùng cho re-ranking hoặc multi-query)."""
    if engine.get_embedder() is None:
        raise RuntimeError("Embedder chưa được khởi tạo.")
    return engine.get_embedder().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).tolist()


def step_embed_cleaned_query(engine, cleaned: dict[str, Any]) -> list[float]:
    """Embed cleaned_query (kết hợp query + key_legal_terms để retrieval tốt hơn)."""
    base = cleaned.get("cleaned_query") or cleaned.get("original") or ""
    terms = cleaned.get("key_legal_terms") or []
    if terms:
        # Kết hợp query + top terms để vector có tín hiệu mạnh hơn
        enriched = f"{base}\nThuật ngữ: {' '.join(terms[:5])}"
    else:
        enriched = base
    return step_embed_question(engine, enriched)
