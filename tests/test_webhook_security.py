from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from bot.config import get_settings
from main import app
from tests.conftest import TEST_BOT_TOKEN, TEST_WEBHOOK_SECRET

ENVIRONMENT_VALUES = {
    "BOT_TOKEN": TEST_BOT_TOKEN,
    "TELEGRAM_WEBHOOK_SECRET": TEST_WEBHOOK_SECRET,
    "DEFAULT_ADMIN_CHAT_ID": "-1001234567890",
    "ADMIN_USER_IDS": "42",
    "TICKET_ROUTES_JSON": "",
    "UPSTASH_REDIS_REST_URL": "https://example.upstash.io",
    "UPSTASH_REDIS_REST_TOKEN": "test-token",
    "REDIS_KEY_PREFIX": "helpdesk_test",
    "ENVIRONMENT": "test",
}


@pytest.fixture(autouse=True)
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in ENVIRONMENT_VALUES.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_does_not_expose_secrets() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert "token" not in payload
    assert "secret" not in str(payload).lower()


def test_webhook_rejects_missing_secret() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhook",
            headers={"Content-Type": "application/json"},
            json={"update_id": 1, "message": {}},
        )

    assert response.status_code == 403
    assert response.json() == {"ok": False, "error": "forbidden"}


def test_webhook_rejects_wrong_secret() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhook",
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": "wrong-secret-0123456789",
            },
            json={"update_id": 1, "message": {}},
        )

    assert response.status_code == 403


def test_webhook_requires_json_content_type() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhook",
            headers={
                "Content-Type": "text/plain",
                "X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET,
            },
            content=b"{}",
        )

    assert response.status_code == 415


def test_webhook_rejects_invalid_json_without_touching_redis() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhook",
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET,
            },
            content=b"{not-json",
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid json"


def test_webhook_rejects_invalid_update_shape() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhook",
            headers={
                "Content-Type": "application/json",
                "X-Telegram-Bot-Api-Secret-Token": TEST_WEBHOOK_SECRET,
            },
            json={"message": {}},
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid update"
