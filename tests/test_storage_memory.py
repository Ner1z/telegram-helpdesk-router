from __future__ import annotations

from bot.models import BanRecord, TicketStatus
from bot.storage.memory import MemoryTicketStore
from tests.conftest import make_ticket


async def test_ticket_registration_and_reply_resolution() -> None:
    store = MemoryTicketStore()
    ticket = make_ticket()

    await store.register_ticket(ticket=ticket, ttl_seconds=3600, history_limit=10)

    assert await store.get_ticket(ticket.token_hash) == ticket
    assert await store.get_ticket_by_id(ticket.ticket_id) == ticket
    assert await store.resolve_admin_message(ticket.admin_chat_id, ticket.admin_message_id) == (
        ticket.token_hash
    )
    assert await store.get_active_ticket_hash(ticket.user.user_id) == ticket.token_hash
    assert await store.list_user_tickets(ticket.user.user_id, limit=10) == [ticket.token_hash]


async def test_follow_up_registers_a_second_reply_mapping() -> None:
    store = MemoryTicketStore()
    ticket = make_ticket()
    await store.register_ticket(ticket=ticket, ttl_seconds=3600, history_limit=10)

    updated_ticket = ticket.with_follow_up(user_message_id=101)
    await store.register_follow_up(
        ticket=updated_ticket,
        admin_message_id=501,
        ttl_seconds=3600,
    )

    assert await store.resolve_admin_message(ticket.admin_chat_id, 501) == ticket.token_hash
    stored_ticket = await store.get_ticket(ticket.token_hash)
    assert stored_ticket is not None
    assert stored_ticket.message_count == 2


async def test_closed_ticket_is_persisted() -> None:
    store = MemoryTicketStore()
    ticket = make_ticket()
    await store.register_ticket(ticket=ticket, ttl_seconds=3600, history_limit=10)

    closed_ticket = ticket.closed(admin_user_id=42, reason="resolved")
    await store.save_ticket(closed_ticket, ttl_seconds=3600)

    stored_ticket = await store.get_ticket(ticket.token_hash)
    assert stored_ticket is not None
    assert stored_ticket.status is TicketStatus.CLOSED
    assert stored_ticket.closed_by == 42
    assert stored_ticket.close_reason == "resolved"


async def test_pending_category_is_popped_atomically() -> None:
    store = MemoryTicketStore()
    await store.set_pending_category(1001, "tech", ttl_seconds=3600)

    assert await store.pop_pending_category(1001) == "tech"
    assert await store.pop_pending_category(1001) is None


async def test_ban_and_unban() -> None:
    store = MemoryTicketStore()
    ban = BanRecord(
        user_id=1001,
        banned_by=42,
        reason="spam",
        created_at="2026-10-28T10:00:00+00:00",
    )

    await store.ban_user(ban=ban, ttl_seconds=3600)
    assert await store.is_user_banned(1001) is True

    await store.unban_user(1001)
    assert await store.is_user_banned(1001) is False


async def test_update_claim_lifecycle() -> None:
    store = MemoryTicketStore()

    assert await store.claim_update(100, lock_seconds=120) is True
    assert await store.claim_update(100, lock_seconds=120) is False
    assert await store.is_update_processed(100) is False

    await store.mark_update_processed(100, ttl_seconds=3600)
    assert await store.is_update_processed(100) is True
    assert await store.claim_update(100, lock_seconds=120) is False
