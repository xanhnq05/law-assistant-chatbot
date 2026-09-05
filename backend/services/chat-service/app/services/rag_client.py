"""HTTP client để gọi rag-service.

chat-service không tự chạy RAG (LLM/Embedder/Pinecone/Neo4j) — nó sẽ
POST sang rag-service mỗi khi cần trả lời. Nếu rag-service không khả
dụng, trả fallback để user không bị 500.

Cung cấp cả 2 API:
- ask(question, top_k)          : async, dùng cho async endpoint
- ask_sync(question, top_k)     : sync, dùng cho def endpoint (router cũ)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from app.core.config import RAG_SERVICE_URL, RAG_TIMEOUT_SECONDS, log


class RagClient:
    """Thin HTTP client cho rag-service (sync + async)."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[float] = None):
        self.base_url = (base_url or RAG_SERVICE_URL).rstrip("/")
        self.timeout = timeout or RAG_TIMEOUT_SECONDS

    # ------------------------------------------------------------
    # SYNC
    # ------------------------------------------------------------
    def ask_sync(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        payload = {"question": question, "top_k": top_k}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.warning("rag-service không khả dụng (%s) — trả fallback.", exc)
            return self._fallback(str(exc))

        return {
            "answer": data.get("answer", ""),
            "sources": data.get("sources", []),
            "debug": data.get("debug", {}),
        }

    # Alias để giữ tương thích tên hàm cũ.
    def ask_sync_safe(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        return self.ask_sync(question, top_k)

    # ------------------------------------------------------------
    # ASYNC
    # ------------------------------------------------------------
    async def ask(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        payload = {"question": question, "top_k": top_k}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            log.warning("rag-service không khả dụng (%s) — trả fallback.", exc)
            return self._fallback(str(exc))

        return {
            "answer": data.get("answer", ""),
            "sources": data.get("sources", []),
            "debug": data.get("debug", {}),
        }

    # ------------------------------------------------------------
    # FALLBACK
    # ------------------------------------------------------------
    @staticmethod
    def _fallback(reason: str) -> Dict[str, Any]:
        return {
            "answer": (
                "Xin lỗi, hệ thống RAG hiện chưa khả dụng. "
                "Vui lòng thử lại sau ít phút.\n"
                f"(Lý do: {reason})"
            ),
            "sources": [],
            "debug": {"rag_unavailable": True},
        }


def get_rag_client() -> RagClient:
    return RagClient()
