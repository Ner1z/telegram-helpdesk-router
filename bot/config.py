from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

CATEGORY_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
KEY_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")

DEFAULT_ROUTE_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    ("general", "💬", "Общие вопросы"),
    ("tech", "🛠", "Техническая поддержка"),
    ("billing", "💳", "Оплата и биллинг"),
)

MAX_ROUTES = 8


class ConfigurationError(RuntimeError):
    """Raised when the runtime configuration is incomplete or unsafe."""


class TicketRoute(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    title: str = Field(min_length=1, max_length=64)
    emoji: str = Field(default="💬", min_length=1, max_length=8)
    chat_id: int
    message_thread_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=160)


def _parse_route_payload(
    key: str,
    payload: dict[str, object],
    default_chat_id: int,
) -> TicketRoute:
    allowed_keys = {"title", "emoji", "chat_id", "message_thread_id", "description"}
    unknown_keys = set(payload) - allowed_keys
    if unknown_keys:
        raise ConfigurationError(f"Неизвестные поля маршрута {key!r}: {sorted(unknown_keys)}")

    title = payload.get("title", key)
    emoji = payload.get("emoji", "💬")
    chat_id = payload.get("chat_id", default_chat_id)
    message_thread_id = payload.get("message_thread_id")
    description = payload.get("description")

    if not isinstance(title, str) or not title.strip():
        raise ConfigurationError(f"Маршрут {key!r}: title должен быть непустой строкой.")
    if not isinstance(emoji, str) or not emoji.strip():
        raise ConfigurationError(f"Маршрут {key!r}: emoji должен быть непустой строкой.")
    if isinstance(chat_id, bool) or not isinstance(chat_id, int):
        raise ConfigurationError(f"Маршрут {key!r}: chat_id должен быть целым числом.")
    if chat_id >= 0:
        raise ConfigurationError(
            f"Маршрут {key!r}: chat_id должен быть отрицательным ID группы или супергруппы."
        )
    if message_thread_id is not None and (
        isinstance(message_thread_id, bool)
        or not isinstance(message_thread_id, int)
        or message_thread_id <= 0
    ):
        raise ConfigurationError(
            f"Маршрут {key!r}: message_thread_id должен быть положительным целым числом."
        )
    if description is not None and not isinstance(description, str):
        raise ConfigurationError(f"Маршрут {key!r}: description должен быть строкой.")

    try:
        return TicketRoute(
            key=key,
            title=title.strip(),
            emoji=emoji.strip(),
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            description=description.strip() if isinstance(description, str) else None,
        )
    except ValidationError as error:
        raise ConfigurationError(f"Некорректный маршрут {key!r}: {error}") from error


def parse_ticket_routes(raw_json: str, default_chat_id: int) -> dict[str, TicketRoute]:
    if not raw_json.strip():
        if default_chat_id >= 0:
            raise ConfigurationError(
                "DEFAULT_ADMIN_CHAT_ID обязателен, если TICKET_ROUTES_JSON не задан."
            )
        return {
            key: TicketRoute(
                key=key,
                title=title,
                emoji=emoji,
                chat_id=default_chat_id,
                message_thread_id=None,
                description=None,
            )
            for key, emoji, title in DEFAULT_ROUTE_TEMPLATES
        }

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ConfigurationError("TICKET_ROUTES_JSON содержит некорректный JSON.") from error

    if not isinstance(payload, dict) or not payload:
        raise ConfigurationError("TICKET_ROUTES_JSON должен быть непустым JSON-объектом.")
    if len(payload) > MAX_ROUTES:
        raise ConfigurationError(f"Максимальное количество маршрутов: {MAX_ROUTES}.")

    routes: dict[str, TicketRoute] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not CATEGORY_KEY_PATTERN.fullmatch(key):
            raise ConfigurationError(
                "Ключ маршрута должен соответствовать ^[a-z][a-z0-9_]{1,31}$."
            )
        if not isinstance(value, dict):
            raise ConfigurationError(f"Маршрут {key!r} должен быть JSON-объектом.")
        routes[key] = _parse_route_payload(key, value, default_chat_id)
    return routes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["production", "development", "test"] = "production"
    log_level: str = "INFO"

    bot_token: SecretStr = SecretStr("")
    telegram_webhook_secret: SecretStr = SecretStr("")

    default_admin_chat_id: int = 0
    admin_user_ids: str = ""
    ticket_routes_json: str = ""

    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: SecretStr = SecretStr("")
    redis_key_prefix: str = "helpdesk"
    redis_timeout_seconds: float = Field(default=5.0, gt=0.0, le=30.0)

    rate_limit_window_seconds: int = Field(default=600, ge=30, le=86_400)
    rate_limit_max_messages: int = Field(default=12, ge=1, le=100)
    pending_category_ttl_seconds: int = Field(default=1_800, ge=60, le=86_400)
    ticket_ttl_seconds: int = Field(default=2_592_000, ge=86_400, le=31_536_000)
    update_lock_seconds: int = Field(default=120, ge=30, le=600)
    update_deduplication_ttl_seconds: int = Field(default=86_400, ge=3_600, le=604_800)
    ban_ttl_seconds: int = Field(default=31_536_000, ge=86_400, le=315_360_000)
    user_ticket_history_limit: int = Field(default=50, ge=1, le=100)

    max_user_message_length: int = Field(default=3_000, ge=100, le=4_000)
    max_admin_message_length: int = Field(default=4_000, ge=100, le=4_096)
    telegram_api_timeout_seconds: float = Field(default=20.0, gt=0.0, le=30.0)
    webhook_max_body_bytes: int = Field(default=1_048_576, ge=1_024, le=4_000_000)

    _ticket_routes_cache: dict[str, TicketRoute] | None = PrivateAttr(default=None)

    @property
    def admin_user_id_set(self) -> frozenset[int]:
        raw_values = [part.strip() for part in self.admin_user_ids.split(",") if part.strip()]
        if not raw_values:
            return frozenset()
        parsed: set[int] = set()
        for value in raw_values:
            if not value.isdigit() or int(value) <= 0:
                raise ConfigurationError("ADMIN_USER_IDS должен содержать положительные ID через запятую.")
            parsed.add(int(value))
        return frozenset(parsed)

    @property
    def ticket_routes(self) -> dict[str, TicketRoute]:
        if self._ticket_routes_cache is None:
            self._ticket_routes_cache = parse_ticket_routes(
                raw_json=self.ticket_routes_json,
                default_chat_id=self.default_admin_chat_id,
            )
        return self._ticket_routes_cache

    @property
    def admin_chat_ids(self) -> frozenset[int]:
        routes = self.ticket_routes
        return frozenset(route.chat_id for route in routes.values())

    def get_route(self, category: str) -> TicketRoute | None:
        return self.ticket_routes.get(category)

    def operational_issues(self) -> list[str]:
        issues: list[str] = []

        token = self.bot_token.get_secret_value().strip()
        if not token or ":" not in token or len(token) < 20:
            issues.append("BOT_TOKEN отсутствует или имеет неверный формат.")

        secret = self.telegram_webhook_secret.get_secret_value()
        if not WEBHOOK_SECRET_PATTERN.fullmatch(secret):
            issues.append("TELEGRAM_WEBHOOK_SECRET должен содержать 16-256 символов [A-Za-z0-9_-].")

        if self.default_admin_chat_id >= 0:
            issues.append("DEFAULT_ADMIN_CHAT_ID должен быть отрицательным ID группы.")

        try:
            if not self.admin_user_id_set:
                issues.append("ADMIN_USER_IDS пуст: админ-команды будут запрещены.")
        except ConfigurationError as error:
            issues.append(str(error))

        try:
            if not self.ticket_routes:
                issues.append("Не настроен ни один маршрут тикетов.")
        except ConfigurationError as error:
            issues.append(str(error))

        if not self.redis_key_prefix or not KEY_PREFIX_PATTERN.fullmatch(self.redis_key_prefix):
            issues.append("REDIS_KEY_PREFIX должен соответствовать ^[a-z][a-z0-9_-]{1,31}$.")

        if not self.upstash_redis_rest_url.strip():
            issues.append("UPSTASH_REDIS_REST_URL не задан.")
        else:
            parsed_url = urlparse(self.upstash_redis_rest_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                issues.append("UPSTASH_REDIS_REST_URL должен быть корректным HTTP(S) URL.")

        if not self.upstash_redis_rest_token.get_secret_value().strip():
            issues.append("UPSTASH_REDIS_REST_TOKEN не задан.")

        return issues

    def require_operational(self) -> None:
        issues = self.operational_issues()
        if issues:
            raise ConfigurationError("; ".join(issues))

    @property
    def is_operational(self) -> bool:
        return not self.operational_issues()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
