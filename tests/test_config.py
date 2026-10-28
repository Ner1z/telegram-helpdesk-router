from __future__ import annotations

import pytest

from bot.config import ConfigurationError, Settings, parse_ticket_routes
from tests.conftest import TEST_BOT_TOKEN, TEST_WEBHOOK_SECRET


def test_default_routes_are_created_for_default_group() -> None:
    routes = parse_ticket_routes("", default_chat_id=-1001234567890)
    assert set(routes) == {"general", "tech", "billing"}
    assert all(route.chat_id == -1001234567890 for route in routes.values())


def test_custom_routes_include_topics_and_are_group_only() -> None:
    routes = parse_ticket_routes(
        '{"tech":{"title":"Tech","emoji":"T","chat_id":-1002222222222,"message_thread_id":42}}',
        default_chat_id=-1001234567890,
    )
    assert routes["tech"].chat_id == -1002222222222
    assert routes["tech"].message_thread_id == 42
    assert routes["tech"].title == "Tech"


def test_positive_route_chat_id_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        parse_ticket_routes('{"tech":{"title":"Tech","chat_id":42}}', -1001234567890)


def test_unknown_route_field_is_rejected() -> None:
    with pytest.raises(ConfigurationError):
        parse_ticket_routes('{"tech":{"title":"Tech","chatID":-1001}}', -1001234567890)


def test_admin_ids_are_parsed_and_invalid_values_are_rejected() -> None:
    settings = Settings(
        _env_file=None,
        admin_user_ids="42, 43",
        bot_token=TEST_BOT_TOKEN,
        telegram_webhook_secret=TEST_WEBHOOK_SECRET,
        default_admin_chat_id=-1001234567890,
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="token",
    )
    assert settings.admin_user_id_set == frozenset({42, 43})

    broken = settings.model_copy(update={"admin_user_ids": "42,abc"})
    with pytest.raises(ConfigurationError):
        _ = broken.admin_user_id_set


def test_short_webhook_secret_is_not_operational() -> None:
    settings = Settings(
        _env_file=None,
        bot_token=TEST_BOT_TOKEN,
        telegram_webhook_secret="short",
        default_admin_chat_id=-1001234567890,
        admin_user_ids="42",
        upstash_redis_rest_url="https://example.upstash.io",
        upstash_redis_rest_token="token",
    )
    assert settings.is_operational is False
    with pytest.raises(ConfigurationError):
        settings.require_operational()
