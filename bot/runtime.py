from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent, Update
from pydantic import ValidationError

from bot.config import Settings
from bot.handlers import build_admin_router, build_user_router
from bot.services.helpdesk import HelpdeskService
from bot.storage import build_store
from bot.storage.base import StorageError, TicketStore

logger = logging.getLogger(__name__)


class InvalidUpdateError(RuntimeError):
    pass


class UpdateInProgressError(RuntimeError):
    pass


def build_dispatcher(
    settings: Settings,
    ticket_store: TicketStore,
    helpdesk_service: HelpdeskService,
) -> Dispatcher:
    dispatcher = Dispatcher(name="helpdesk")
    dispatcher["settings"] = settings
    dispatcher["ticket_store"] = ticket_store
    dispatcher["helpdesk_service"] = helpdesk_service

    dispatcher.include_router(build_admin_router(settings, helpdesk_service))
    dispatcher.include_router(build_user_router(settings))

    async def handle_error(event: ErrorEvent) -> None:
        logger.error(
            "handler_error",
            extra={
                "update_id": event.update.update_id,
                "exception_type": type(event.exception).__name__,
            },
            exc_info=event.exception,
        )
        raise event.exception

    dispatcher.errors.register(handle_error)
    return dispatcher


async def process_telegram_update(settings: Settings, payload: dict[str, Any]) -> None:
    update_id = payload.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int):
        raise InvalidUpdateError("update_id is missing or invalid")

    ticket_store = build_store(settings)
    bot: Bot | None = None

    try:
        claimed = await ticket_store.claim_update(
            update_id=update_id,
            lock_seconds=settings.update_lock_seconds,
        )
        if not claimed:
            if await ticket_store.is_update_processed(update_id):
                logger.info("duplicate_update_ignored", extra={"update_id": update_id})
                return
            raise UpdateInProgressError("update is already being processed")

        try:
            update = Update.model_validate(payload)
        except ValidationError as error:
            await _safe_release_update(ticket_store, update_id)
            raise InvalidUpdateError("Telegram update failed validation") from error

        session = AiohttpSession(timeout=settings.telegram_api_timeout_seconds)
        bot = Bot(
            token=settings.bot_token.get_secret_value(),
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        helpdesk_service = HelpdeskService(
            settings=settings,
            ticket_store=ticket_store,
            bot=bot,
        )
        dispatcher = build_dispatcher(
            settings=settings,
            ticket_store=ticket_store,
            helpdesk_service=helpdesk_service,
        )

        try:
            await dispatcher.feed_update(bot, update)
        except Exception:
            await _safe_release_update(ticket_store, update_id)
            raise

        try:
            await ticket_store.mark_update_processed(
                update_id=update_id,
                ttl_seconds=settings.update_deduplication_ttl_seconds,
            )
        except StorageError:
            logger.exception(
                "update_deduplication_marker_failed",
                extra={"update_id": update_id},
            )

        logger.info("update_processed", extra={"update_id": update_id})
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                logger.exception("bot_session_close_failed")
        try:
            await ticket_store.close()
        except Exception:
            logger.exception("ticket_store_close_failed")


async def _safe_release_update(ticket_store: TicketStore, update_id: int) -> None:
    try:
        await ticket_store.release_update(update_id)
    except StorageError:
        logger.exception("update_lock_release_failed", extra={"update_id": update_id})
