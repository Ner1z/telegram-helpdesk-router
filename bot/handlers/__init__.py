from __future__ import annotations

from bot.handlers.admin import build_admin_router
from bot.handlers.user import build_user_router

__all__ = ["build_admin_router", "build_user_router"]
