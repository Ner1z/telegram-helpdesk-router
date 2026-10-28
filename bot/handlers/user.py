from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message, User

from bot import texts
from bot.config import Settings
from bot.filters.access import BannedUserMiddleware
from bot.keyboards import build_cancel_keyboard, build_route_keyboard
from bot.models import UserProfile
from bot.services.helpdesk import (
    HelpdeskService,
    HelpdeskServiceError,
    MessageValidationError,
    RouteUnavailableError,
    TicketClosedError,
)
from bot.storage.base import StorageError, TicketStore

logger = logging.getLogger(__name__)


def build_user_profile(user: User) -> UserProfile:
    full_name = user.full_name.strip() if user.full_name else ""
    if not full_name:
        full_name = "Пользователь Telegram"
    return UserProfile(
        user_id=user.id,
        full_name=full_name,
        username=user.username,
        language_code=user.language_code,
    )


def build_user_router(settings: Settings) -> Router:
    router = Router(name="user")
    router.message.filter(F.chat.type == ChatType.PRIVATE)

    banned_middleware = BannedUserMiddleware()
    router.message.middleware(banned_middleware)
    router.callback_query.middleware(banned_middleware)

    @router.message(CommandStart())
    async def handle_start(message: Message, ticket_store: TicketStore) -> None:
        if message.from_user is None:
            return
        try:
            await ticket_store.clear_pending_category(message.from_user.id)
        except StorageError:
            logger.exception("pending_category_clear_failed")
        await message.answer(
            texts.render_welcome(),
            reply_markup=build_route_keyboard(settings.ticket_routes),
        )

    @router.message(Command("help"))
    async def handle_help(message: Message) -> None:
        await message.answer(texts.render_user_help())

    @router.message(Command("new"))
    async def handle_new(message: Message, ticket_store: TicketStore) -> None:
        if message.from_user is None:
            return
        try:
            await ticket_store.clear_pending_category(message.from_user.id)
        except StorageError:
            logger.exception("pending_category_clear_failed")
        await message.answer(
            texts.render_choose_category(),
            reply_markup=build_route_keyboard(settings.ticket_routes),
        )

    @router.message(Command("cancel"))
    async def handle_cancel(message: Message, ticket_store: TicketStore) -> None:
        if message.from_user is None:
            return
        try:
            await ticket_store.clear_pending_category(message.from_user.id)
        except StorageError:
            logger.exception("pending_category_clear_failed")
        await message.answer(texts.render_cancelled())

    @router.callback_query(F.data.startswith("route:"))
    async def handle_route_selection(
        callback: CallbackQuery,
        ticket_store: TicketStore,
    ) -> None:
        if callback.message is None or callback.from_user is None:
            await callback.answer("Недоступно.", show_alert=False)
            return
        if callback.message.chat.id != callback.from_user.id:
            await callback.answer("Недоступно.", show_alert=False)
            return

        category = (callback.data or "").partition(":")[2]
        route = settings.get_route(category)
        if route is None:
            await callback.answer("Категория недоступна.", show_alert=True)
            return

        try:
            await ticket_store.set_pending_category(
                user_id=callback.from_user.id,
                category=route.key,
                ttl_seconds=settings.pending_category_ttl_seconds,
            )
        except StorageError:
            logger.exception("pending_category_set_failed")
            await callback.answer("Временная ошибка.", show_alert=True)
            return

        await callback.answer("Тема выбрана.")
        await callback.message.answer(
            texts.render_category_prompt(route),
            reply_markup=build_cancel_keyboard(),
        )

    @router.callback_query(F.data == "route_cancel")
    async def handle_route_cancel(
        callback: CallbackQuery,
        ticket_store: TicketStore,
    ) -> None:
        if callback.from_user is None:
            await callback.answer("Недоступно.", show_alert=False)
            return
        try:
            await ticket_store.clear_pending_category(callback.from_user.id)
        except StorageError:
            logger.exception("pending_category_clear_failed")
            await callback.answer("Временная ошибка.", show_alert=True)
            return
        await callback.answer("Отменено.")
        if callback.message is not None:
            try:
                await callback.message.edit_text(texts.render_cancelled())
            except TelegramAPIError:
                logger.debug("cancel_message_edit_failed")

    @router.message(F.text, ~F.text.startswith("/"))
    async def handle_user_text(
        message: Message,
        ticket_store: TicketStore,
        helpdesk_service: HelpdeskService,
    ) -> None:
        if message.from_user is None or message.text is None:
            return

        user_id = message.from_user.id
        profile = build_user_profile(message.from_user)
        message_text = message.text

        if len(message_text) > settings.max_user_message_length:
            await message.answer(
                texts.render_message_too_long(settings.max_user_message_length)
            )
            return

        try:
            rate_count = await ticket_store.increment_rate_limit(
                user_id=user_id,
                window_seconds=settings.rate_limit_window_seconds,
            )
        except StorageError:
            logger.exception("rate_limit_check_failed")
            await message.answer(texts.render_temporary_error())
            return

        if rate_count > settings.rate_limit_max_messages:
            await message.answer(texts.render_rate_limited())
            return

        try:
            pending_category = await ticket_store.pop_pending_category(user_id)
        except StorageError:
            logger.exception("pending_category_pop_failed")
            await message.answer(texts.render_temporary_error())
            return

        if pending_category is not None:
            await _create_ticket_from_pending_category(
                message=message,
                profile=profile,
                category=pending_category,
                helpdesk_service=helpdesk_service,
                settings=settings,
            )
            return

        try:
            active_ticket_hash = await ticket_store.get_active_ticket_hash(user_id)
        except StorageError:
            logger.exception("active_ticket_read_failed")
            await message.answer(texts.render_temporary_error())
            return

        if active_ticket_hash is not None:
            try:
                active_ticket = await ticket_store.get_ticket(active_ticket_hash)
            except StorageError:
                logger.exception("active_ticket_load_failed")
                await message.answer(texts.render_temporary_error())
                return

            if active_ticket is None or not active_ticket.is_open:
                try:
                    await ticket_store.clear_active_ticket_hash(user_id)
                except StorageError:
                    logger.exception("stale_active_ticket_clear_failed")
                await _prompt_choose_category(message, settings)
                return

            try:
                await helpdesk_service.append_follow_up(
                    ticket=active_ticket,
                    message_text=message_text,
                    user_message_id=message.message_id,
                )
            except TicketClosedError:
                try:
                    await ticket_store.clear_active_ticket_hash(
                        user_id=user_id, token_hash=active_ticket.token_hash
                    )
                except StorageError:
                    logger.exception("active_ticket_clear_failed")
                await _prompt_choose_category(message, settings)
                return
            except (TelegramAPIError, StorageError):
                logger.exception(
                    "follow_up_failed",
                    extra={"ticket_id": active_ticket.ticket_id},
                )
                await message.answer(texts.render_temporary_error())
                return

            await message.answer(texts.render_follow_up_accepted(active_ticket.ticket_id))
            return

        await _prompt_choose_category(message, settings)

    @router.message(F.text.startswith("/"))
    async def handle_unknown_command(message: Message) -> None:
        await message.answer(texts.render_unknown_command())

    @router.message()
    async def handle_non_text(message: Message) -> None:
        await message.answer(texts.render_text_only())

    return router


async def _prompt_choose_category(message: Message, settings: Settings) -> None:
    await message.answer(
        texts.render_choose_category(),
        reply_markup=build_route_keyboard(settings.ticket_routes),
    )


async def _create_ticket_from_pending_category(
    message: Message,
    profile: UserProfile,
    category: str,
    helpdesk_service: HelpdeskService,
    settings: Settings,
) -> None:
    try:
        ticket = await helpdesk_service.create_ticket(
            profile=profile,
            category=category,
            message_text=message.text or "",
            user_message_id=message.message_id,
        )
    except RouteUnavailableError:
        await message.answer(
            texts.render_category_unavailable(),
            reply_markup=build_route_keyboard(settings.ticket_routes),
        )
        return
    except MessageValidationError:
        await message.answer(
            texts.render_message_too_long(settings.max_user_message_length)
        )
        return
    except (TelegramAPIError, StorageError, HelpdeskServiceError):
        logger.exception(
            "ticket_creation_failed",
            extra={"user_id": profile.user_id, "category": category},
        )
        await message.answer(texts.render_temporary_error())
        return

    await message.answer(texts.render_ticket_created(ticket.ticket_id))
