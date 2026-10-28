from __future__ import annotations

from typing import Any

import pytest

from bot.config import Settings
from bot.models import Ticket, TicketStatus, UserProfile

TEST_BOT_TOKEN = "123456789:abcdefghijklmnopqrstuvwxyzABCDE"
TEST_WEBHOOK_SECRET = "test_webhook_secret_0123456789"


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        bot_token=TEST_BOT_TOKEN,
        telegram_webhook_secret=TEST_WEBHOOK_SECRET,
        default_admin_chat_id=-1001234567890,
        admin_user_ids="42,43",
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="test-upstash-token",
        redis_key_prefix="helpdesk_test",
        ticket_routes_json="",
    )


def make_ticket(**overrides: Any) -> Ticket:
    token_hash = overrides.pop("token_hash", "a" * 64)
    profile = overrides.pop(
        "user",
        UserProfile(
            user_id=1001,
            full_name="Test User",
            username="test_user",
            language_code="ru",
        ),
    )
    payload: dict[str, Any] = {
        "ticket_id": token_hash[:16].upper(),
        "token_hash": token_hash,
        "user": profile,
        "category": "general",
        "category_title": "Общие вопросы",
        "category_emoji": "💬",
        "admin_chat_id": -1001234567890,
        "admin_message_id": 500,
        "admin_message_thread_id": None,
        "user_message_id": 100,
        "status": TicketStatus.OPEN,
        "created_at": "2026-10-28T10:00:00+00:00",
        "updated_at": "2026-10-28T10:00:00+00:00",
        "message_count": 1,
        "closed_at": None,
        "closed_by": None,
        "close_reason": None,
        "last_admin_reply_at": None,
    }
    payload.update(overrides)
    return Ticket(**payload)
