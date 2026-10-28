from __future__ import annotations

from bot.config import Settings
from bot.storage.base import StorageError, TicketStore
from bot.storage.memory import MemoryTicketStore
from bot.storage.redis import RedisTicketStore

__all__ = [
    "MemoryTicketStore",
    "RedisTicketStore",
    "StorageError",
    "TicketStore",
    "build_store",
]


def build_store(settings: Settings) -> RedisTicketStore:
    url = settings.upstash_redis_rest_url.strip()
    token = settings.upstash_redis_rest_token.get_secret_value().strip()
    if not url or not token:
        raise StorageError("Redis is not configured")
    return RedisTicketStore(
        url=url,
        token=token,
        key_prefix=settings.redis_key_prefix,
        timeout_seconds=settings.redis_timeout_seconds,
    )
