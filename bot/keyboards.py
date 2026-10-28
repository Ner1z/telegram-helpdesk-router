from __future__ import annotations

from collections.abc import Mapping

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import TicketRoute


def _button_label(route: TicketRoute) -> str:
    label = f"{route.emoji} {route.title}".strip()
    if len(label) > 64:
        label = label[:63] + "…"
    return label


def build_route_keyboard(routes: Mapping[str, TicketRoute]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for route in routes.values():
        builder.button(text=_button_label(route), callback_data=f"route:{route.key}")
    builder.adjust(1)
    return builder.as_markup()


def build_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✖️ Отменить", callback_data="route_cancel")
    builder.adjust(1)
    return builder.as_markup()
