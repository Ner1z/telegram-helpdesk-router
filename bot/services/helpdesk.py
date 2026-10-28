from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.types import Message

from bot import texts
from bot.config import Settings
from bot.models import Ticket, TicketStatus, UserProfile, new_ban_record
from bot.security import (
    derive_ticket_id,
    escape_html,
    extract_ticket_id_from_text,
    generate_reply_token,
    hash_reply_token,
    normalize_ticket_id,
)
from bot.storage.base import StorageError, TicketStore
from bot.timeutils import isoformat_utc

logger = logging.getLogger(__name__)

MAX_TELEGRAM_TEXT_LENGTH = 4_096


class HelpdeskServiceError(RuntimeError):
    pass


class RouteUnavailableError(HelpdeskServiceError):
    pass


class TicketClosedError(HelpdeskServiceError):
    pass


class UserUnreachableError(HelpdeskServiceError):
    pass


class MessageValidationError(HelpdeskServiceError):
    pass


class HelpdeskService:
    def __init__(self, settings: Settings, ticket_store: TicketStore, bot: Bot) -> None:
        self._settings = settings
        self._store = ticket_store
        self._bot = bot

    async def create_ticket(
        self,
        profile: UserProfile,
        category: str,
        message_text: str,
        user_message_id: int,
    ) -> Ticket:
        route = self._settings.get_route(category)
        if route is None:
            raise RouteUnavailableError(category)

        normalized_text = self._validate_user_text(message_text)
        ticket_id, token_hash = await self._allocate_ticket_identity()
        created_at = isoformat_utc()
        admin_text = texts.render_new_ticket(
            ticket_id=ticket_id,
            route=route,
            profile=profile,
            message_text=normalized_text,
            created_at=created_at,
        )

        sent_message = await self._bot.send_message(
            chat_id=route.chat_id,
            text=admin_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            message_thread_id=route.message_thread_id,
        )

        ticket = Ticket(
            ticket_id=ticket_id,
            token_hash=token_hash,
            user=profile,
            category=route.key,
            category_title=route.title,
            category_emoji=route.emoji,
            admin_chat_id=route.chat_id,
            admin_message_id=sent_message.message_id,
            admin_message_thread_id=route.message_thread_id,
            user_message_id=user_message_id,
            status=TicketStatus.OPEN,
            created_at=created_at,
            updated_at=created_at,
            message_count=1,
        )

        try:
            await self._store.register_ticket(
                ticket=ticket,
                ttl_seconds=self._settings.ticket_ttl_seconds,
                history_limit=self._settings.user_ticket_history_limit,
            )
        except StorageError:
            await self._best_effort_delete_admin_message(route.chat_id, sent_message.message_id)
            try:
                await self._store.set_pending_category(
                    user_id=profile.user_id,
                    category=category,
                    ttl_seconds=self._settings.pending_category_ttl_seconds,
                )
            except StorageError:
                logger.exception("restore_pending_category_failed")
            raise

        logger.info(
            "ticket_created",
            extra={
                "ticket_id": ticket.ticket_id,
                "user_id": profile.user_id,
                "category": route.key,
                "admin_chat_id": route.chat_id,
            },
        )
        return ticket

    async def append_follow_up(
        self,
        ticket: Ticket,
        message_text: str,
        user_message_id: int,
    ) -> Ticket:
        if ticket.status is not TicketStatus.OPEN:
            raise TicketClosedError(ticket.ticket_id)

        normalized_text = self._validate_user_text(message_text)
        sent_message = await self._bot.send_message(
            chat_id=ticket.admin_chat_id,
            text=texts.render_follow_up(
                ticket_id=ticket.ticket_id,
                profile=ticket.user,
                message_text=normalized_text,
                created_at=isoformat_utc(),
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            message_thread_id=ticket.admin_message_thread_id,
        )

        updated_ticket = ticket.with_follow_up(user_message_id)
        await self._store.register_follow_up(
            ticket=updated_ticket,
            admin_message_id=sent_message.message_id,
            ttl_seconds=self._settings.ticket_ttl_seconds,
        )
        logger.info(
            "ticket_follow_up",
            extra={
                "ticket_id": ticket.ticket_id,
                "user_id": ticket.user.user_id,
                "message_count": updated_ticket.message_count,
            },
        )
        return updated_ticket

    async def send_admin_reply(
        self,
        ticket: Ticket,
        message_text: str,
        admin_user_id: int,
    ) -> None:
        if ticket.status is not TicketStatus.OPEN:
            raise TicketClosedError(ticket.ticket_id)

        normalized_text = message_text.strip()
        if not normalized_text:
            raise MessageValidationError("empty admin reply")
        if len(normalized_text) > self._settings.max_admin_message_length:
            raise MessageValidationError("admin reply is too long")

        header = texts.render_reply_header(ticket.ticket_id)
        escaped_text = escape_html(normalized_text)

        if len(header) + 1 + len(escaped_text) <= MAX_TELEGRAM_TEXT_LENGTH:
            await self._send_to_user(ticket, f"{header}\n{escaped_text}")
        else:
            await self._send_to_user(ticket, header)
            for chunk in self._split_escaped_text(normalized_text, MAX_TELEGRAM_TEXT_LENGTH):
                await self._send_to_user(ticket, chunk)

        updated_ticket = ticket.with_admin_reply()
        try:
            await self._store.save_ticket(
                ticket=updated_ticket,
                ttl_seconds=self._settings.ticket_ttl_seconds,
            )
        except StorageError:
            logger.exception(
                "ticket_reply_timestamp_update_failed",
                extra={"ticket_id": ticket.ticket_id},
            )

        logger.info(
            "admin_reply_delivered",
            extra={
                "ticket_id": ticket.ticket_id,
                "admin_user_id": admin_user_id,
                "user_id": ticket.user.user_id,
            },
        )

    async def close_ticket(
        self,
        ticket: Ticket,
        admin_user_id: int,
        reason: str | None = None,
    ) -> Ticket:
        if ticket.status is TicketStatus.CLOSED:
            return ticket

        normalized_reason = (reason or "").strip()[:200] or None
        closed_ticket = ticket.closed(admin_user_id=admin_user_id, reason=normalized_reason)
        await self._store.save_ticket(
            ticket=closed_ticket,
            ttl_seconds=self._settings.ticket_ttl_seconds,
        )
        try:
            await self._store.clear_active_ticket_hash(
                user_id=ticket.user.user_id,
                token_hash=ticket.token_hash,
            )
        except StorageError:
            logger.exception(
                "ticket_active_reference_clear_failed",
                extra={"ticket_id": ticket.ticket_id},
            )

        await self._notify_user(
            ticket=ticket,
            text=texts.render_closed_for_user(ticket.ticket_id),
        )
        await self._notify_admin_group(
            ticket=closed_ticket,
            text=texts.render_closed_for_admin(ticket.ticket_id, ticket.user),
        )

        logger.info(
            "ticket_closed",
            extra={
                "ticket_id": ticket.ticket_id,
                "admin_user_id": admin_user_id,
                "user_id": ticket.user.user_id,
                "reason": normalized_reason,
            },
        )
        return closed_ticket

    async def ban_user_from_ticket(
        self,
        ticket: Ticket,
        admin_user_id: int,
        reason: str | None,
    ) -> int:
        normalized_reason = (reason or "").strip()[:200] or None
        await self._store.ban_user(
            ban=new_ban_record(
                user_id=ticket.user.user_id,
                banned_by=admin_user_id,
                reason=normalized_reason,
            ),
            ttl_seconds=self._settings.ban_ttl_seconds,
        )

        token_hashes = await self._store.list_user_tickets(
            user_id=ticket.user.user_id,
            limit=self._settings.user_ticket_history_limit,
        )
        if ticket.token_hash not in token_hashes:
            token_hashes.insert(0, ticket.token_hash)

        closed_count = 0
        seen: set[str] = set()
        for token_hash in token_hashes:
            if token_hash in seen:
                continue
            seen.add(token_hash)
            existing_ticket = await self._store.get_ticket(token_hash)
            if existing_ticket is None or existing_ticket.status is TicketStatus.CLOSED:
                continue
            closed_ticket = existing_ticket.closed(
                admin_user_id=admin_user_id,
                reason="user_banned",
            )
            try:
                await self._store.save_ticket(
                    ticket=closed_ticket,
                    ttl_seconds=self._settings.ticket_ttl_seconds,
                )
            except StorageError:
                logger.exception(
                    "ban_ticket_close_failed",
                    extra={"ticket_id": existing_ticket.ticket_id},
                )
                continue
            closed_count += 1

        await self._store.clear_active_ticket_hash(user_id=ticket.user.user_id)
        await self._notify_user(ticket=ticket, text=texts.render_banned_for_user())

        logger.info(
            "user_banned",
            extra={
                "user_id": ticket.user.user_id,
                "admin_user_id": admin_user_id,
                "ticket_id": ticket.ticket_id,
                "closed_tickets": closed_count,
                "reason": normalized_reason,
            },
        )
        return closed_count

    async def unban_user(self, ticket: Ticket, admin_user_id: int) -> None:
        await self._store.unban_user(ticket.user.user_id)
        await self._notify_user(ticket=ticket, text=texts.render_unbanned_for_user())
        logger.info(
            "user_unbanned",
            extra={
                "user_id": ticket.user.user_id,
                "admin_user_id": admin_user_id,
                "ticket_id": ticket.ticket_id,
            },
        )

    async def resolve_ticket_for_admin(
        self,
        admin_chat_id: int,
        reply_to_message: Message | None,
        ticket_id_argument: str | None,
    ) -> Ticket | None:
        ticket: Ticket | None = None

        if reply_to_message is not None:
            token_hash = await self._store.resolve_admin_message(
                admin_chat_id=admin_chat_id,
                admin_message_id=reply_to_message.message_id,
            )
            if token_hash is not None:
                ticket = await self._store.get_ticket(token_hash)
            if ticket is None:
                parsed_ticket_id = extract_ticket_id_from_text(
                    reply_to_message.text or reply_to_message.caption
                )
                if parsed_ticket_id is not None:
                    ticket = await self._store.get_ticket_by_id(parsed_ticket_id)
        elif ticket_id_argument:
            normalized_ticket_id = normalize_ticket_id(ticket_id_argument)
            if normalized_ticket_id is not None:
                ticket = await self._store.get_ticket_by_id(normalized_ticket_id)

        if ticket is None:
            return None
        if ticket.admin_chat_id != admin_chat_id:
            logger.warning(
                "cross_group_ticket_access_denied",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "admin_chat_id": admin_chat_id,
                    "ticket_admin_chat_id": ticket.admin_chat_id,
                },
            )
            return None
        return ticket

    async def _allocate_ticket_identity(self) -> tuple[str, str]:
        for _ in range(5):
            token = generate_reply_token()
            token_hash = hash_reply_token(token)
            ticket_id = derive_ticket_id(token_hash)
            existing_ticket = await self._store.get_ticket_by_id(ticket_id)
            if existing_ticket is None:
                return ticket_id, token_hash
        raise HelpdeskServiceError("Unable to allocate a unique ticket ID")

    def _validate_user_text(self, message_text: str) -> str:
        normalized_text = message_text.strip()
        if not normalized_text:
            raise MessageValidationError("empty user message")
        if len(normalized_text) > self._settings.max_user_message_length:
            raise MessageValidationError("user message is too long")
        return normalized_text

    async def _send_to_user(self, ticket: Ticket, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=ticket.user.user_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramForbiddenError as error:
            logger.warning(
                "user_unreachable",
                extra={"ticket_id": ticket.ticket_id, "user_id": ticket.user.user_id},
            )
            raise UserUnreachableError(ticket.ticket_id) from error

    async def _notify_user(self, ticket: Ticket, text: str) -> None:
        try:
            await self._send_to_user(ticket, text)
        except UserUnreachableError:
            logger.info(
                "user_notification_skipped",
                extra={"ticket_id": ticket.ticket_id, "user_id": ticket.user.user_id},
            )
        except TelegramAPIError:
            logger.exception(
                "user_notification_failed",
                extra={"ticket_id": ticket.ticket_id},
            )

    async def _notify_admin_group(self, ticket: Ticket, text: str) -> None:
        try:
            await self._bot.send_message(
                chat_id=ticket.admin_chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                message_thread_id=ticket.admin_message_thread_id,
            )
        except TelegramAPIError:
            logger.exception(
                "admin_group_notification_failed",
                extra={"ticket_id": ticket.ticket_id},
            )

    async def _best_effort_delete_admin_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramAPIError:
            logger.warning("orphan_admin_message_cleanup_failed")

    @staticmethod
    def _split_escaped_text(text: str, max_escaped_length: int) -> list[str]:
        chunks: list[str] = []
        current_characters: list[str] = []
        current_length = 0

        for character in text:
            escaped_length = len(escape_html(character))
            if current_characters and current_length + escaped_length > max_escaped_length:
                chunks.append(escape_html("".join(current_characters)))
                current_characters = []
                current_length = 0
            current_characters.append(character)
            current_length += escaped_length

        if current_characters:
            chunks.append(escape_html("".join(current_characters)))
        return chunks
