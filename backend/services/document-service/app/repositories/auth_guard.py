"""Auth dependency cho document-service.

Hiện tại: TẠM THỜI bỏ qua toàn bộ JWT/admin verification.
- Trả về user giả `{id: "admin", email: "admin@local.dev", role: "admin"}`.
- TODO Phase sau: bật lại JWT verify khi auth-service đã hoàn thiện
  và frontend đã chuyển sang dùng real login (không còn hardcode).
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.config import log


# Fake admin user — được trả về cho MỌI request.
_FAKE_ADMIN_USER: Dict[str, Any] = {
    "id": "admin",
    "email": "admin@local.dev",
    "name": "Administrator (hardcoded)",
    "role": "admin",
}


def get_current_user(request: object = None) -> Dict[str, Any]:
    """Auth bypass — luôn trả fake admin user.

    Trước đây verify JWT + load user từ Mongo. Hiện tại FE đang hardcode
    login, nên tạm bỏ. Sẽ bật lại sau.
    """
    return dict(_FAKE_ADMIN_USER)


def require_admin(request: object = None) -> Dict[str, Any]:
    """Auth bypass — luôn pass với role admin giả."""
    log.debug("require_admin bypassed (hardcoded)")
    return dict(_FAKE_ADMIN_USER)
