from __future__ import annotations

from typing import Protocol

from bot.models import BanRecord, Ticket


class StorageError(RuntimeError):
    """Raised when the state backend is unavailable or returns an invalid response."""


class TicketStore(Protocol):
    async def close(self) -> None: ...

    async def ping(self) -> bool: ...

    async def claim_update(self, update_id: int, lock_seconds: int) -> bool: ...

    async def is_update_processed(self, update_id: int) -> bool: ...

    async def mark_update_processed(self, update_id: int, ttl_seconds: int) -> None: ...

    async def release_update(self, update_id: int) -> None: ...

    async def increment_rate_limit(self, user_id: int, window_seconds: int) -> int: ...

    async def pop_pending_category(self, user_id: int) -> str | None: ...

    async def set_pending_category(
        self,
        user_id: int,
        category: str,
        ttl_seconds: int,
    ) -> None: ...

    async def clear_pending_category(self, user_id: int) -> None: ...

    async def get_active_ticket_hash(self, user_id: int) -> str | None: ...

    async def set_active_ticket_hash(
        self,
        user_id: int,
        token_hash: str,
        ttl_seconds: int,
    ) -> None: ...

    async def clear_active_ticket_hash(
        self,
        user_id: int,
        token_hash: str | None = None,
    ) -> None: ...

    async def register_ticket(
        self,
        ticket: Ticket,
        ttl_seconds: int,
        history_limit: int,
    ) -> None: ...

    async def register_follow_up(
        self,
        ticket: Ticket,
        admin_message_id: int,
        ttl_seconds: int,
    ) -> None: ...

    async def save_ticket(self, ticket: Ticket, ttl_seconds: int) -> None: ...

    async def get_ticket(self, token_hash: str) -> Ticket | None: ...

    async def get_ticket_by_id(self, ticket_id: str) -> Ticket | None: ...

    async def resolve_admin_message(
        self,
        admin_chat_id: int,
        admin_message_id: int,
    ) -> str | None: ...

    async def list_user_tickets(self, user_id: int, limit: int) -> list[str]: ...

    async def ban_user(self, ban: BanRecord, ttl_seconds: int) -> None: ...

    async def is_user_banned(self, user_id: int) -> bool: ...

    async def unban_user(self, user_id: int) -> None: ...
