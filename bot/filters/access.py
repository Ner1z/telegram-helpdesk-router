from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.storage.base import TicketStore

logger = logging.getLogger(__name__)


class AdminChatFilter(BaseFilter):
    def __init__(self, admin_chat_ids: frozenset[int]) -> None:
        self._admin_chat_ids = admin_chat_ids

    async def __call__(self, message: Message) -> bool:
        return message.chat.id in self._admin_chat_ids


class AdminUserFilter(BaseFilter):
    def __init__(self, admin_user_ids: frozenset[int]) -> None:
        self._admin_user_ids = admin_user_ids

    async def __call__(self, message: Message) -> bool:
        if message.from_user is None:
            return False
        if message.from_user.is_bot:
            return False
        return message.from_user.id in self._admin_user_ids


class BannedUserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        event_from_user = data.get("event_from_user")
        if event_from_user is None:
            return await handler(event, data)

        ticket_store: TicketStore | None = data.get("ticket_store")
        if ticket_store is None:
            logger.error("ticket_store_missing_in_middleware")
            return await handler(event, data)

        if await ticket_store.is_user_banned(event_from_user.id):
            logger.info(
                "blocked_message_from_banned_user",
                extra={"user_id": event_from_user.id},
            )
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer("Недоступно.", show_alert=False)
                except Exception:
                    logger.debug("callback_answer_failed_for_banned_user")
            return None

        return await handler(event, data)
