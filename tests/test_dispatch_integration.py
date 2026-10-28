from __future__ import annotations

from typing import Any

import pytest
from aiogram import Bot
from aiogram.methods import AnswerCallbackQuery, DeleteMessage, EditMessageText, SendMessage
from aiogram.types import Update

from bot.config import Settings
from bot.models import TicketStatus
from bot.runtime import build_dispatcher
from bot.services.helpdesk import HelpdeskService
from bot.storage.memory import MemoryTicketStore
from tests.conftest import TEST_BOT_TOKEN

USER_ID = 1001
ADMIN_ID = 42
ADMIN_CHAT_ID = -1001234567890


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._next_message_id = 500

    async def __call__(self, bot: Bot, method: Any, **kwargs: Any) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            self._next_message_id += 1
            return type("SentMessage", (), {"message_id": self._next_message_id})()
        if isinstance(method, (AnswerCallbackQuery, DeleteMessage, EditMessageText)):
            return True
        return True

    async def close(self) -> None:
        return None


def user_payload(text: str, message_id: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": message_id,
        "date": 1_700_000_000,
        "chat": {"id": USER_ID, "type": "private", "first_name": "Test"},
        "from": {
            "id": USER_ID,
            "is_bot": False,
            "first_name": "Test",
            "username": "test_user",
            "language_code": "ru",
        },
        "text": text,
    }
    if text.startswith("/"):
        payload["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
        ]
    return payload


def admin_payload(
    text: str,
    message_id: int,
    reply_to_message_id: int | None = None,
    from_user_id: int = ADMIN_ID,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message_id": message_id,
        "date": 1_700_000_001,
        "chat": {
            "id": ADMIN_CHAT_ID,
            "type": "supergroup",
            "title": "Support",
        },
        "from": {
            "id": from_user_id,
            "is_bot": False,
            "first_name": "Admin",
            "username": "admin_user",
        },
        "text": text,
    }
    if text.startswith("/"):
        payload["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
        ]
    if reply_to_message_id is not None:
        payload["reply_to_message"] = {
            "message_id": reply_to_message_id,
            "date": 1_700_000_000,
            "chat": {
                "id": ADMIN_CHAT_ID,
                "type": "supergroup",
                "title": "Support",
            },
            "from": {
                "id": 999,
                "is_bot": True,
                "first_name": "Helpdesk",
                "username": "helpdesk_bot",
            },
            "text": "Ticket message",
        }
    return payload


def make_update(update_id: int, payload: dict[str, Any]) -> Update:
    return Update.model_validate({"update_id": update_id, **payload})


async def build_test_runtime(settings: Settings):
    store = MemoryTicketStore()
    bot = Bot(token=TEST_BOT_TOKEN)
    fake_session = FakeSession()
    bot.session = fake_session  # type: ignore[assignment]
    service = HelpdeskService(settings=settings, ticket_store=store, bot=bot)
    dispatcher = build_dispatcher(settings=settings, ticket_store=store, helpdesk_service=service)
    return store, bot, fake_session, dispatcher


@pytest.mark.asyncio
async def test_user_to_admin_to_user_routing_and_close(settings: Settings) -> None:
    store, bot, fake_session, dispatcher = await build_test_runtime(settings)

    await dispatcher.feed_update(bot, make_update(1, {"message": user_payload("/start", 1)}))
    assert any("Поддержка" in getattr(call, "text", "") for call in fake_session.calls)

    callback_update = make_update(
        2,
        {
            "callback_query": {
                "id": "callback-1",
                "from": {
                    "id": USER_ID,
                    "is_bot": False,
                    "first_name": "Test",
                    "username": "test_user",
                },
                "message": user_payload("Choose a category", 2),
                "chat_instance": "instance-1",
                "data": "route:general",
            }
        },
    )
    await dispatcher.feed_update(bot, callback_update)
    assert await store.pop_pending_category(USER_ID) == "general"

    await store.set_pending_category(USER_ID, "general", ttl_seconds=3600)
    await dispatcher.feed_update(
        bot,
        make_update(
            3,
            {"message": user_payload("My account is blocked", 3)},
        ),
    )

    history = await store.list_user_tickets(USER_ID, limit=10)
    assert len(history) == 1
    ticket = await store.get_ticket(history[0])
    assert ticket is not None
    assert ticket.status is TicketStatus.OPEN
    assert await store.get_active_ticket_hash(USER_ID) == ticket.token_hash

    await dispatcher.feed_update(
        bot,
        make_update(
            4,
            {
                "message": admin_payload(
                    "We are checking your account.",
                    message_id=10,
                    reply_to_message_id=ticket.admin_message_id,
                )
            },
        ),
    )
    refreshed_ticket = await store.get_ticket(ticket.token_hash)
    assert refreshed_ticket is not None
    assert refreshed_ticket.last_admin_reply_at is not None

    await dispatcher.feed_update(
        bot,
        make_update(
            5,
            {
                "message": admin_payload(
                    "/close",
                    message_id=11,
                    reply_to_message_id=ticket.admin_message_id,
                )
            },
        ),
    )
    closed_ticket = await store.get_ticket(ticket.token_hash)
    assert closed_ticket is not None
    assert closed_ticket.status is TicketStatus.CLOSED
    assert await store.get_active_ticket_hash(USER_ID) is None

    await bot.session.close()


@pytest.mark.asyncio
async def test_non_allowlisted_user_cannot_close_ticket(settings: Settings) -> None:
    store, bot, _fake_session, dispatcher = await build_test_runtime(settings)
    await store.set_pending_category(USER_ID, "general", ttl_seconds=3600)
    await dispatcher.feed_update(
        bot,
        make_update(10, {"message": user_payload("Need help", 20)}),
    )
    history = await store.list_user_tickets(USER_ID, limit=10)
    ticket = await store.get_ticket(history[0])
    assert ticket is not None

    await dispatcher.feed_update(
        bot,
        make_update(
            11,
            {
                "message": admin_payload(
                    "/close",
                    message_id=21,
                    reply_to_message_id=ticket.admin_message_id,
                    from_user_id=999,
                )
            },
        ),
    )

    unchanged_ticket = await store.get_ticket(ticket.token_hash)
    assert unchanged_ticket is not None
    assert unchanged_ticket.status is TicketStatus.OPEN
    await bot.session.close()
