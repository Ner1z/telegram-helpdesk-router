from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from bot.timeutils import isoformat_utc, utc_now


class TicketStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: int
    full_name: str
    username: str | None = None
    language_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "full_name": self.full_name,
            "username": self.username,
            "language_code": self.language_code,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> UserProfile:
        user_id = payload.get("user_id")
        full_name = payload.get("full_name")
        username = payload.get("username")
        language_code = payload.get("language_code")
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("Invalid user_id in user profile")
        if not isinstance(full_name, str) or not full_name:
            raise ValueError("Invalid full_name in user profile")
        if username is not None and not isinstance(username, str):
            raise ValueError("Invalid username in user profile")
        if language_code is not None and not isinstance(language_code, str):
            raise ValueError("Invalid language_code in user profile")
        return cls(
            user_id=user_id,
            full_name=full_name,
            username=username,
            language_code=language_code,
        )


@dataclass(frozen=True, slots=True)
class Ticket:
    ticket_id: str
    token_hash: str
    user: UserProfile
    category: str
    category_title: str
    category_emoji: str
    admin_chat_id: int
    admin_message_id: int
    admin_message_thread_id: int | None
    user_message_id: int
    status: TicketStatus
    created_at: str
    updated_at: str
    message_count: int = 1
    closed_at: str | None = None
    closed_by: int | None = None
    close_reason: str | None = None
    last_admin_reply_at: str | None = None

    @property
    def is_open(self) -> bool:
        return self.status is TicketStatus.OPEN

    def with_follow_up(self, user_message_id: int) -> Ticket:
        return replace(
            self,
            user_message_id=user_message_id,
            updated_at=isoformat_utc(),
            message_count=self.message_count + 1,
        )

    def with_admin_reply(self) -> Ticket:
        replied_at = isoformat_utc()
        return replace(
            self,
            updated_at=replied_at,
            last_admin_reply_at=replied_at,
        )

    def closed(self, admin_user_id: int, reason: str | None) -> Ticket:
        closed_at = isoformat_utc()
        return replace(
            self,
            status=TicketStatus.CLOSED,
            updated_at=closed_at,
            closed_at=closed_at,
            closed_by=admin_user_id,
            close_reason=reason,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "token_hash": self.token_hash,
            "user": self.user.to_payload(),
            "category": self.category,
            "category_title": self.category_title,
            "category_emoji": self.category_emoji,
            "admin_chat_id": self.admin_chat_id,
            "admin_message_id": self.admin_message_id,
            "admin_message_thread_id": self.admin_message_thread_id,
            "user_message_id": self.user_message_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "closed_at": self.closed_at,
            "closed_by": self.closed_by,
            "close_reason": self.close_reason,
            "last_admin_reply_at": self.last_admin_reply_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Ticket:
        if not isinstance(payload, dict):
            raise ValueError("Ticket payload must be an object")

        ticket_id = payload.get("ticket_id")
        token_hash = payload.get("token_hash")
        user_payload = payload.get("user")
        category = payload.get("category")
        category_title = payload.get("category_title")
        category_emoji = payload.get("category_emoji")
        admin_chat_id = payload.get("admin_chat_id")
        admin_message_id = payload.get("admin_message_id")
        admin_message_thread_id = payload.get("admin_message_thread_id")
        user_message_id = payload.get("user_message_id")
        status_value = payload.get("status")
        created_at = payload.get("created_at")
        updated_at = payload.get("updated_at")
        message_count = payload.get("message_count", 1)
        closed_at = payload.get("closed_at")
        closed_by = payload.get("closed_by")
        close_reason = payload.get("close_reason")
        last_admin_reply_at = payload.get("last_admin_reply_at")

        if not isinstance(ticket_id, str) or not ticket_id:
            raise ValueError("Invalid ticket_id")
        if not isinstance(token_hash, str) or not token_hash:
            raise ValueError("Invalid token_hash")
        if not isinstance(user_payload, dict):
            raise ValueError("Invalid user")
        if not isinstance(category, str) or not category:
            raise ValueError("Invalid category")
        if not isinstance(category_title, str) or not category_title:
            raise ValueError("Invalid category_title")
        if not isinstance(category_emoji, str) or not category_emoji:
            raise ValueError("Invalid category_emoji")
        if isinstance(admin_chat_id, bool) or not isinstance(admin_chat_id, int):
            raise ValueError("Invalid admin_chat_id")
        if isinstance(admin_message_id, bool) or not isinstance(admin_message_id, int):
            raise ValueError("Invalid admin_message_id")
        if admin_message_thread_id is not None and (
            isinstance(admin_message_thread_id, bool)
            or not isinstance(admin_message_thread_id, int)
        ):
            raise ValueError("Invalid admin_message_thread_id")
        if isinstance(user_message_id, bool) or not isinstance(user_message_id, int):
            raise ValueError("Invalid user_message_id")
        if status_value not in {item.value for item in TicketStatus}:
            raise ValueError("Invalid status")
        if not isinstance(created_at, str) or not created_at:
            raise ValueError("Invalid created_at")
        if not isinstance(updated_at, str) or not updated_at:
            raise ValueError("Invalid updated_at")
        if isinstance(message_count, bool) or not isinstance(message_count, int) or message_count < 1:
            raise ValueError("Invalid message_count")
        if closed_at is not None and not isinstance(closed_at, str):
            raise ValueError("Invalid closed_at")
        if closed_by is not None and (
            isinstance(closed_by, bool) or not isinstance(closed_by, int)
        ):
            raise ValueError("Invalid closed_by")
        if close_reason is not None and not isinstance(close_reason, str):
            raise ValueError("Invalid close_reason")
        if last_admin_reply_at is not None and not isinstance(last_admin_reply_at, str):
            raise ValueError("Invalid last_admin_reply_at")

        return cls(
            ticket_id=ticket_id,
            token_hash=token_hash,
            user=UserProfile.from_payload(user_payload),
            category=category,
            category_title=category_title,
            category_emoji=category_emoji,
            admin_chat_id=admin_chat_id,
            admin_message_id=admin_message_id,
            admin_message_thread_id=admin_message_thread_id,
            user_message_id=user_message_id,
            status=TicketStatus(status_value),
            created_at=created_at,
            updated_at=updated_at,
            message_count=message_count,
            closed_at=closed_at,
            closed_by=closed_by,
            close_reason=close_reason,
            last_admin_reply_at=last_admin_reply_at,
        )


@dataclass(frozen=True, slots=True)
class BanRecord:
    user_id: int
    banned_by: int
    reason: str | None
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "banned_by": self.banned_by,
            "reason": self.reason,
            "created_at": self.created_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BanRecord:
        if not isinstance(payload, dict):
            raise ValueError("Ban payload must be an object")
        user_id = payload.get("user_id")
        banned_by = payload.get("banned_by")
        reason = payload.get("reason")
        created_at = payload.get("created_at")
        if isinstance(user_id, bool) or not isinstance(user_id, int):
            raise ValueError("Invalid ban user_id")
        if isinstance(banned_by, bool) or not isinstance(banned_by, int):
            raise ValueError("Invalid banning admin")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("Invalid ban reason")
        if not isinstance(created_at, str) or not created_at:
            raise ValueError("Invalid ban created_at")
        return cls(user_id=user_id, banned_by=banned_by, reason=reason, created_at=created_at)


def new_ban_record(user_id: int, banned_by: int, reason: str | None) -> BanRecord:
    return BanRecord(
        user_id=user_id,
        banned_by=banned_by,
        reason=reason,
        created_at=isoformat_utc(utc_now()),
    )
