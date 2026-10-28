from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot import texts
from bot.config import Settings
from bot.filters.access import AdminChatFilter, AdminUserFilter
from bot.services.helpdesk import (
    HelpdeskService,
    HelpdeskServiceError,
    MessageValidationError,
    TicketClosedError,
    UserUnreachableError,
)
from bot.storage.base import StorageError

logger = logging.getLogger(__name__)


def build_admin_router(settings: Settings, helpdesk_service: HelpdeskService) -> Router:
    router = Router(name="admin")
    router.message.filter(
        AdminChatFilter(admin_chat_ids=settings.admin_chat_ids),
        AdminUserFilter(admin_user_ids=settings.admin_user_id_set),
    )

    @router.message(Command("admin_help"))
    async def handle_admin_help(message: Message) -> None:
        await message.reply(texts.render_admin_help())

    @router.message(Command("close"))
    async def handle_close(
        message: Message,
        command: CommandObject,
    ) -> None:
        if message.from_user is None:
            return
        if message.reply_to_message is not None and command.args:
            await message.reply(texts.render_close_with_reply_and_argument())
            return

        try:
            ticket = await helpdesk_service.resolve_ticket_for_admin(
                admin_chat_id=message.chat.id,
                reply_to_message=message.reply_to_message,
                ticket_id_argument=command.args,
            )
        except StorageError:
            logger.exception("admin_close_resolve_failed")
            await message.reply(texts.render_admin_temporary_error())
            return

        if ticket is None:
            if message.reply_to_message is None and not command.args:
                await message.reply(texts.render_reply_usage())
            else:
                await message.reply(
                    f"{texts.render_ticket_not_found()}\n\n{texts.render_reply_usage()}"
                )
            return

        if not ticket.is_open:
            await message.reply(texts.render_ticket_already_closed(ticket.ticket_id))
            return

        try:
            await helpdesk_service.close_ticket(
                ticket=ticket,
                admin_user_id=message.from_user.id,
                reason=None,
            )
        except (StorageError, TelegramAPIError, HelpdeskServiceError):
            logger.exception(
                "admin_close_failed",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "admin_user_id": message.from_user.id,
                    "admin_chat_id": message.chat.id,
                },
            )
            await message.reply(texts.render_admin_temporary_error())
            return

        logger.info(
            "admin_close_completed",
            extra={
                "ticket_id": ticket.ticket_id,
                "admin_user_id": message.from_user.id,
                "admin_chat_id": message.chat.id,
            },
        )

    @router.message(Command("ban"))
    async def handle_ban(
        message: Message,
        command: CommandObject,
    ) -> None:
        if message.from_user is None:
            return
        if message.reply_to_message is None:
            await message.reply(texts.render_ban_usage())
            return

        try:
            ticket = await helpdesk_service.resolve_ticket_for_admin(
                admin_chat_id=message.chat.id,
                reply_to_message=message.reply_to_message,
                ticket_id_argument=None,
            )
        except StorageError:
            logger.exception("admin_ban_resolve_failed")
            await message.reply(texts.render_admin_temporary_error())
            return

        if ticket is None:
            await message.reply(texts.render_not_a_ticket_reply())
            return

        try:
            closed_tickets = await helpdesk_service.ban_user_from_ticket(
                ticket=ticket,
                admin_user_id=message.from_user.id,
                reason=command.args,
            )
        except (StorageError, TelegramAPIError, HelpdeskServiceError):
            logger.exception(
                "admin_ban_failed",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "admin_user_id": message.from_user.id,
                    "admin_chat_id": message.chat.id,
                },
            )
            await message.reply(texts.render_admin_temporary_error())
            return

        await message.reply(
            texts.render_ban_confirmation(
                ticket_id=ticket.ticket_id,
                user=ticket.user,
                closed_tickets=closed_tickets,
            )
        )
        logger.info(
            "admin_ban_completed",
            extra={
                "ticket_id": ticket.ticket_id,
                "admin_user_id": message.from_user.id,
                "target_user_id": ticket.user.user_id,
                "closed_tickets": closed_tickets,
            },
        )

    @router.message(Command("unban"))
    async def handle_unban(message: Message) -> None:
        if message.from_user is None:
            return
        if message.reply_to_message is None:
            await message.reply(texts.render_unban_usage())
            return

        try:
            ticket = await helpdesk_service.resolve_ticket_for_admin(
                admin_chat_id=message.chat.id,
                reply_to_message=message.reply_to_message,
                ticket_id_argument=None,
            )
        except StorageError:
            logger.exception("admin_unban_resolve_failed")
            await message.reply(texts.render_admin_temporary_error())
            return

        if ticket is None:
            await message.reply(texts.render_not_a_ticket_reply())
            return

        try:
            await helpdesk_service.unban_user(
                ticket=ticket,
                admin_user_id=message.from_user.id,
            )
        except (StorageError, TelegramAPIError, HelpdeskServiceError):
            logger.exception(
                "admin_unban_failed",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "admin_user_id": message.from_user.id,
                },
            )
            await message.reply(texts.render_admin_temporary_error())
            return

        await message.reply(texts.render_unban_confirmation(ticket.user))
        logger.info(
            "admin_unban_completed",
            extra={
                "ticket_id": ticket.ticket_id,
                "admin_user_id": message.from_user.id,
                "target_user_id": ticket.user.user_id,
            },
        )

    @router.message(F.reply_to_message, F.text, ~F.text.startswith("/"))
    async def handle_admin_reply(message: Message) -> None:
        if message.from_user is None or message.text is None:
            return
        if message.reply_to_message is None:
            return
        if len(message.text) > settings.max_admin_message_length:
            await message.reply(
                texts.render_message_too_long(settings.max_admin_message_length)
            )
            return

        try:
            ticket = await helpdesk_service.resolve_ticket_for_admin(
                admin_chat_id=message.chat.id,
                reply_to_message=message.reply_to_message,
                ticket_id_argument=None,
            )
        except StorageError:
            logger.exception("admin_reply_resolve_failed")
            await message.reply(texts.render_admin_temporary_error())
            return

        if ticket is None:
            await message.reply(texts.render_not_a_ticket_reply())
            return
        if not ticket.is_open:
            await message.reply(texts.render_closed_reply_blocked(ticket.ticket_id))
            return

        try:
            await helpdesk_service.send_admin_reply(
                ticket=ticket,
                message_text=message.text,
                admin_user_id=message.from_user.id,
            )
        except UserUnreachableError:
            await message.reply(texts.render_delivery_failed())
            return
        except TicketClosedError:
            await message.reply(texts.render_ticket_already_closed(ticket.ticket_id))
            return
        except MessageValidationError:
            await message.reply(
                texts.render_message_too_long(settings.max_admin_message_length)
            )
            return
        except (StorageError, TelegramAPIError, HelpdeskServiceError):
            logger.exception(
                "admin_reply_failed",
                extra={
                    "ticket_id": ticket.ticket_id,
                    "admin_user_id": message.from_user.id,
                    "admin_chat_id": message.chat.id,
                },
            )
            await message.reply(texts.render_admin_temporary_error())
            return

        await message.reply(
            texts.render_delivery_confirmation(
                ticket_id=ticket.ticket_id,
                user=ticket.user,
            )
        )

    @router.message(F.reply_to_message, ~F.text)
    async def handle_admin_non_text_reply(message: Message) -> None:
        await message.reply(texts.render_text_only())

    return router
