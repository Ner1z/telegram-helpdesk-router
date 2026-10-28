from __future__ import annotations

import html
from types import SimpleNamespace
from typing import cast

from aiogram.types import Message

from bot.config import Settings
from bot.services.helpdesk import HelpdeskService
from bot.storage.memory import MemoryTicketStore
from tests.conftest import make_ticket


def make_service(settings: Settings, store: MemoryTicketStore) -> HelpdeskService:
    return HelpdeskService(settings=settings, ticket_store=store, bot=cast(object, None))  # type: ignore[arg-type]


async def test_ticket_can_be_resolved_by_public_ticket_id(
    settings: Settings,
) -> None:
    store = MemoryTicketStore()
    ticket = make_ticket()
    await store.register_ticket(ticket=ticket, ttl_seconds=3600, history_limit=10)
    service = make_service(settings, store)

    resolved = await service.resolve_ticket_for_admin(
        admin_chat_id=ticket.admin_chat_id,
        reply_to_message=None,
        ticket_id_argument=f"#TKT-{ticket.ticket_id}",
    )

    assert resolved == ticket


async def test_ticket_cannot_be_resolved_from_another_admin_group(
    settings: Settings,
) -> None:
    store = MemoryTicketStore()
    ticket = make_ticket()
    await store.register_ticket(ticket=ticket, ttl_seconds=3600, history_limit=10)
    service = make_service(settings, store)

    resolved = await service.resolve_ticket_for_admin(
        admin_chat_id=-1009999999999,
        reply_to_message=None,
        ticket_id_argument=ticket.ticket_id,
    )

    assert resolved is None


async def test_ticket_can_be_resolved_from_a_reply_mapping(
    settings: Settings,
) -> None:
    store = MemoryTicketStore()
    ticket = make_ticket()
    await store.register_ticket(ticket=ticket, ttl_seconds=3600, history_limit=10)
    service = make_service(settings, store)
    reply = cast(
        Message,
        SimpleNamespace(message_id=ticket.admin_message_id, text=None, caption=None),
    )

    resolved = await service.resolve_ticket_for_admin(
        admin_chat_id=ticket.admin_chat_id,
        reply_to_message=reply,
        ticket_id_argument=None,
    )

    assert resolved == ticket


def test_long_html_text_is_split_without_breaking_entities(settings: Settings) -> None:
    store = MemoryTicketStore()
    service = make_service(settings, store)
    text = "<" * 10_000

    chunks = service._split_escaped_text(text, 4096)

    assert len(chunks) > 1
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert html.unescape("".join(chunks)) == text
