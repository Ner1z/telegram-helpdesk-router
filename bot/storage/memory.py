from __future__ import annotations

from collections import defaultdict

from bot.models import BanRecord, Ticket


class MemoryTicketStore:
    """In-memory implementation used only by unit tests.

    It deliberately does not implement TTLs: tests must be deterministic. It must
    never be selected for a deployed webhook because serverless invocations do not
    share process memory.
    """

    def __init__(self) -> None:
        self._tickets: dict[str, Ticket] = {}
        self._ticket_ids: dict[str, str] = {}
        self._reply_index: dict[tuple[int, int], str] = {}
        self._active: dict[int, str] = {}
        self._pending: dict[int, str] = {}
        self._rate_limits: dict[int, int] = defaultdict(int)
        self._user_tickets: dict[int, list[str]] = defaultdict(list)
        self._bans: dict[int, BanRecord] = {}
        self._claimed_updates: set[int] = set()
        self._processed_updates: set[int] = set()

    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def claim_update(self, update_id: int, lock_seconds: int) -> bool:
        if update_id in self._claimed_updates or update_id in self._processed_updates:
            return False
        self._claimed_updates.add(update_id)
        return True

    async def is_update_processed(self, update_id: int) -> bool:
        return update_id in self._processed_updates

    async def mark_update_processed(self, update_id: int, ttl_seconds: int) -> None:
        self._claimed_updates.discard(update_id)
        self._processed_updates.add(update_id)

    async def release_update(self, update_id: int) -> None:
        self._claimed_updates.discard(update_id)

    async def increment_rate_limit(self, user_id: int, window_seconds: int) -> int:
        self._rate_limits[user_id] += 1
        return self._rate_limits[user_id]

    async def pop_pending_category(self, user_id: int) -> str | None:
        return self._pending.pop(user_id, None)

    async def set_pending_category(
        self,
        user_id: int,
        category: str,
        ttl_seconds: int,
    ) -> None:
        self._pending[user_id] = category

    async def clear_pending_category(self, user_id: int) -> None:
        self._pending.pop(user_id, None)

    async def get_active_ticket_hash(self, user_id: int) -> str | None:
        return self._active.get(user_id)

    async def set_active_ticket_hash(
        self,
        user_id: int,
        token_hash: str,
        ttl_seconds: int,
    ) -> None:
        self._active[user_id] = token_hash

    async def clear_active_ticket_hash(
        self,
        user_id: int,
        token_hash: str | None = None,
    ) -> None:
        if token_hash is None or self._active.get(user_id) == token_hash:
            self._active.pop(user_id, None)

    async def register_ticket(
        self,
        ticket: Ticket,
        ttl_seconds: int,
        history_limit: int,
    ) -> None:
        self._tickets[ticket.token_hash] = ticket
        self._ticket_ids[ticket.ticket_id] = ticket.token_hash
        self._reply_index[(ticket.admin_chat_id, ticket.admin_message_id)] = ticket.token_hash
        self._active[ticket.user.user_id] = ticket.token_hash
        history = self._user_tickets[ticket.user.user_id]
        history.insert(0, ticket.token_hash)
        del history[history_limit:]
        self._pending.pop(ticket.user.user_id, None)

    async def register_follow_up(
        self,
        ticket: Ticket,
        admin_message_id: int,
        ttl_seconds: int,
    ) -> None:
        self._tickets[ticket.token_hash] = ticket
        self._ticket_ids[ticket.ticket_id] = ticket.token_hash
        self._reply_index[(ticket.admin_chat_id, admin_message_id)] = ticket.token_hash

    async def save_ticket(self, ticket: Ticket, ttl_seconds: int) -> None:
        self._tickets[ticket.token_hash] = ticket
        self._ticket_ids[ticket.ticket_id] = ticket.token_hash

    async def get_ticket(self, token_hash: str) -> Ticket | None:
        return self._tickets.get(token_hash)

    async def get_ticket_by_id(self, ticket_id: str) -> Ticket | None:
        token_hash = self._ticket_ids.get(ticket_id)
        if token_hash is None:
            return None
        return self._tickets.get(token_hash)

    async def resolve_admin_message(
        self,
        admin_chat_id: int,
        admin_message_id: int,
    ) -> str | None:
        return self._reply_index.get((admin_chat_id, admin_message_id))

    async def list_user_tickets(self, user_id: int, limit: int) -> list[str]:
        history = self._user_tickets.get(user_id, [])
        return history[:limit]

    async def ban_user(self, ban: BanRecord, ttl_seconds: int) -> None:
        self._bans[ban.user_id] = ban

    async def is_user_banned(self, user_id: int) -> bool:
        return user_id in self._bans

    async def unban_user(self, user_id: int) -> None:
        self._bans.pop(user_id, None)
