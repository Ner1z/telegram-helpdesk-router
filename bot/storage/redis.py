from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from bot.models import BanRecord, Ticket
from bot.storage.base import StorageError

_RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

_POP_PENDING_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""

_CLEAR_ACTIVE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if (not ARGV[1] or ARGV[1] == '') or current == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class UpstashRedisClient:
    def __init__(self, url: str, token: str, timeout_seconds: float) -> None:
        base_url = f"{url.rstrip('/')}/"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "telegram-helpdesk-router/1.0",
            },
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(self, command: Sequence[Any]) -> Any:
        try:
            response = await self._client.post("", json=list(command))
        except httpx.HTTPError as error:
            raise StorageError("Redis transport error") from error
        return self._decode_single(response)

    async def pipeline(self, commands: Sequence[Sequence[Any]]) -> list[Any]:
        try:
            response = await self._client.post(
                "pipeline",
                json=[list(command) for command in commands],
            )
        except httpx.HTTPError as error:
            raise StorageError("Redis pipeline transport error") from error

        if response.status_code >= 400:
            raise StorageError(f"Redis pipeline HTTP error: {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise StorageError("Redis pipeline returned invalid JSON") from error
        if not isinstance(payload, list):
            raise StorageError("Redis pipeline returned an unexpected payload")

        results: list[Any] = []
        for item in payload:
            if not isinstance(item, dict):
                raise StorageError("Redis pipeline item has an unexpected format")
            if "error" in item:
                raise StorageError("Redis pipeline command failed")
            results.append(item.get("result"))
        return results

    @staticmethod
    def _decode_single(response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise StorageError(f"Redis HTTP error: {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise StorageError("Redis returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise StorageError("Redis returned an unexpected payload")
        if "error" in payload:
            raise StorageError("Redis command failed")
        if "result" not in payload:
            raise StorageError("Redis response does not contain a result")
        return payload["result"]


class RedisTicketStore:
    def __init__(
        self,
        url: str,
        token: str,
        key_prefix: str,
        timeout_seconds: float,
    ) -> None:
        self._redis = UpstashRedisClient(url=url, token=token, timeout_seconds=timeout_seconds)
        self._prefix = key_prefix

    async def close(self) -> None:
        await self._redis.close()

    def _key(self, *parts: object) -> str:
        return ":".join((self._prefix, *(str(part) for part in parts)))

    async def ping(self) -> bool:
        result = await self._redis.execute(["PING"])
        return result == "PONG"

    async def claim_update(self, update_id: int, lock_seconds: int) -> bool:
        result = await self._redis.execute(
            ["SET", self._key("update", update_id), "processing", "NX", "EX", lock_seconds]
        )
        return result == "OK"

    async def is_update_processed(self, update_id: int) -> bool:
        result = await self._redis.execute(["GET", self._key("update", update_id)])
        return result == "done"

    async def mark_update_processed(self, update_id: int, ttl_seconds: int) -> None:
        await self._redis.execute(
            ["SET", self._key("update", update_id), "done", "EX", ttl_seconds]
        )

    async def release_update(self, update_id: int) -> None:
        await self._redis.execute(["DEL", self._key("update", update_id)])

    async def increment_rate_limit(self, user_id: int, window_seconds: int) -> int:
        result = await self._redis.execute(
            [
                "EVAL",
                _RATE_LIMIT_SCRIPT,
                "1",
                self._key("rate", user_id),
                str(window_seconds),
            ]
        )
        if isinstance(result, bool) or not isinstance(result, int):
            raise StorageError("Redis rate limit script returned an invalid value")
        return result

    async def pop_pending_category(self, user_id: int) -> str | None:
        result = await self._redis.execute(
            ["EVAL", _POP_PENDING_SCRIPT, "1", self._key("pending", user_id)]
        )
        if result is None:
            return None
        if not isinstance(result, str):
            raise StorageError("Redis pending category has an invalid format")
        return result

    async def set_pending_category(
        self,
        user_id: int,
        category: str,
        ttl_seconds: int,
    ) -> None:
        await self._redis.execute(
            ["SET", self._key("pending", user_id), category, "EX", ttl_seconds]
        )

    async def clear_pending_category(self, user_id: int) -> None:
        await self._redis.execute(["DEL", self._key("pending", user_id)])

    async def get_active_ticket_hash(self, user_id: int) -> str | None:
        result = await self._redis.execute(["GET", self._key("active", user_id)])
        if result is None:
            return None
        if not isinstance(result, str):
            raise StorageError("Redis active ticket has an invalid format")
        return result

    async def set_active_ticket_hash(
        self,
        user_id: int,
        token_hash: str,
        ttl_seconds: int,
    ) -> None:
        await self._redis.execute(
            ["SET", self._key("active", user_id), token_hash, "EX", ttl_seconds]
        )

    async def clear_active_ticket_hash(
        self,
        user_id: int,
        token_hash: str | None = None,
    ) -> None:
        await self._redis.execute(
            [
                "EVAL",
                _CLEAR_ACTIVE_SCRIPT,
                "1",
                self._key("active", user_id),
                token_hash or "",
            ]
        )

    async def register_ticket(
        self,
        ticket: Ticket,
        ttl_seconds: int,
        history_limit: int,
    ) -> None:
        ticket_json = json.dumps(ticket.to_payload(), ensure_ascii=False, separators=(",", ":"))
        history_key = self._key("user", ticket.user.user_id, "tickets")
        commands: list[list[Any]] = [
            ["SET", self._key("ticket", ticket.token_hash), ticket_json, "EX", ttl_seconds],
            ["SET", self._key("ticket_id", ticket.ticket_id), ticket.token_hash, "EX", ttl_seconds],
            [
                "SET",
                self._key("reply", ticket.admin_chat_id, ticket.admin_message_id),
                ticket.token_hash,
                "EX",
                ttl_seconds,
            ],
            [
                "SET",
                self._key("active", ticket.user.user_id),
                ticket.token_hash,
                "EX",
                ttl_seconds,
            ],
            ["LPUSH", history_key, ticket.token_hash],
            ["LTRIM", history_key, 0, history_limit - 1],
            ["EXPIRE", history_key, ttl_seconds],
            ["DEL", self._key("pending", ticket.user.user_id)],
        ]
        await self._redis.pipeline(commands)

    async def register_follow_up(
        self,
        ticket: Ticket,
        admin_message_id: int,
        ttl_seconds: int,
    ) -> None:
        ticket_json = json.dumps(ticket.to_payload(), ensure_ascii=False, separators=(",", ":"))
        commands: list[list[Any]] = [
            ["SET", self._key("ticket", ticket.token_hash), ticket_json, "EX", ttl_seconds],
            ["SET", self._key("ticket_id", ticket.ticket_id), ticket.token_hash, "EX", ttl_seconds],
            [
                "SET",
                self._key("reply", ticket.admin_chat_id, admin_message_id),
                ticket.token_hash,
                "EX",
                ttl_seconds,
            ],
        ]
        await self._redis.pipeline(commands)

    async def save_ticket(self, ticket: Ticket, ttl_seconds: int) -> None:
        ticket_json = json.dumps(ticket.to_payload(), ensure_ascii=False, separators=(",", ":"))
        await self._redis.pipeline(
            [
                [
                    "SET",
                    self._key("ticket", ticket.token_hash),
                    ticket_json,
                    "EX",
                    ttl_seconds,
                ],
                [
                    "SET",
                    self._key("ticket_id", ticket.ticket_id),
                    ticket.token_hash,
                    "EX",
                    ttl_seconds,
                ],
            ]
        )

    async def get_ticket(self, token_hash: str) -> Ticket | None:
        raw_ticket = await self._redis.execute(["GET", self._key("ticket", token_hash)])
        if raw_ticket is None:
            return None
        if not isinstance(raw_ticket, str):
            raise StorageError("Redis ticket has an invalid format")
        try:
            payload = json.loads(raw_ticket)
            return Ticket.from_payload(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise StorageError("Stored ticket is corrupted") from error

    async def get_ticket_by_id(self, ticket_id: str) -> Ticket | None:
        token_hash = await self._redis.execute(
            ["GET", self._key("ticket_id", ticket_id)]
        )
        if token_hash is None:
            return None
        if not isinstance(token_hash, str):
            raise StorageError("Redis ticket_id mapping has an invalid format")
        return await self.get_ticket(token_hash)

    async def resolve_admin_message(
        self,
        admin_chat_id: int,
        admin_message_id: int,
    ) -> str | None:
        result = await self._redis.execute(
            ["GET", self._key("reply", admin_chat_id, admin_message_id)]
        )
        if result is None:
            return None
        if not isinstance(result, str):
            raise StorageError("Redis reply mapping has an invalid format")
        return result

    async def list_user_tickets(self, user_id: int, limit: int) -> list[str]:
        result = await self._redis.execute(
            ["LRANGE", self._key("user", user_id, "tickets"), 0, limit - 1]
        )
        if not isinstance(result, list):
            raise StorageError("Redis user ticket history has an invalid format")
        return [item for item in result if isinstance(item, str)]

    async def ban_user(self, ban: BanRecord, ttl_seconds: int) -> None:
        payload = json.dumps(ban.to_payload(), ensure_ascii=False, separators=(",", ":"))
        await self._redis.execute(
            ["SET", self._key("ban", ban.user_id), payload, "EX", ttl_seconds]
        )

    async def is_user_banned(self, user_id: int) -> bool:
        result = await self._redis.execute(["EXISTS", self._key("ban", user_id)])
        return result == 1

    async def unban_user(self, user_id: int) -> None:
        await self._redis.execute(["DEL", self._key("ban", user_id)])
