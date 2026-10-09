"""Supabase client singleton cho document-service.

Phase 1: chỉ dùng Storage API (upload PDF/DOCX + JSON intermediate).
Phase 2+: có thể thêm DB queries nếu cần.

Service-role (secret_key) bắt buộc để upload vượt RLS của bucket private.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from supabase import Client, create_client

if TYPE_CHECKING:
    from supabase._sync.client import SyncClient

from app.core.config import (
    SUPABASE_SECRET_KEY,
    SUPABASE_URL,
    log,
)


class SupabaseClient:
    """Supabase client wrapper với lazy initialization."""

    _instance: SupabaseClient | None = None
    _client: Client | None = None

    def __new__(cls) -> SupabaseClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def connect(self) -> Client:
        """Khởi tạo Supabase client (service-role). Idempotent."""
        if self._client is None:
            if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
                raise RuntimeError(
                    "SUPABASE_URL và SUPABASE_SECRET_KEY phải có trong .env"
                )
            log.info("Connecting Supabase at %s ...", SUPABASE_URL)
            self._client = create_client(
                supabase_url=SUPABASE_URL,
                supabase_key=SUPABASE_SECRET_KEY,
            )
            log.info("Supabase client initialized.")
        return self._client

    @property
    def client(self) -> Client:
        return self.connect()


def get_supabase_client() -> SupabaseClient:
    """Singleton accessor."""
    return SupabaseClient()
