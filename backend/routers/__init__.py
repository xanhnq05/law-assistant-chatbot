"""
Routers package.
"""
from __future__ import annotations

from routers.auth_router import router as auth_router
from routers.chat_router import router as chat_router

__all__ = ["auth_router", "chat_router"]