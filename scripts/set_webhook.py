from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TELEGRAM_API_BASE = "https://api.telegram.org"
WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
ALLOWED_UPDATES = ["message", "callback_query"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set, inspect, or delete the Telegram webhook for the helpdesk bot."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("PUBLIC_BASE_URL", ""),
        help="Public HTTPS base URL (for example https://project.vercel.app).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete the current webhook instead of setting it.",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print getWebhookInfo without changing the webhook.",
    )
    parser.add_argument(
        "--drop-pending",
        action="store_true",
        help="Drop pending updates when setting or deleting the webhook.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the target webhook URL without calling Telegram.",
    )
    return parser.parse_args()


def build_webhook_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("--url or PUBLIC_BASE_URL is required")
    if not normalized.startswith("https://"):
        raise ValueError("Telegram requires an HTTPS webhook URL")
    if normalized.endswith("/webhook") or normalized.endswith("/api/webhook"):
        return normalized
    return f"{normalized}/webhook"


async def telegram_request(
    client: httpx.AsyncClient,
    bot_token: str,
    method: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    response = await client.post(
        f"{TELEGRAM_API_BASE}/bot{bot_token}/{method}",
        json=payload or {},
    )
    try:
        response_payload = response.json()
    except ValueError as error:
        raise RuntimeError(f"Telegram returned non-JSON HTTP {response.status_code}") from error
    if response.status_code >= 400 or not response_payload.get("ok"):
        description = response_payload.get("description", "unknown Telegram API error")
        raise RuntimeError(str(description))
    return response_payload


async def run(args: argparse.Namespace) -> int:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        print("BOT_TOKEN is not set.", file=sys.stderr)
        return 1

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        if args.info:
            payload = await telegram_request(client, bot_token, "getWebhookInfo")
            result = payload.get("result")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.delete:
            payload = await telegram_request(
                client,
                bot_token,
                "deleteWebhook",
                {"drop_pending_updates": args.drop_pending},
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        if not WEBHOOK_SECRET_PATTERN.fullmatch(webhook_secret):
            print(
                "TELEGRAM_WEBHOOK_SECRET must contain 16-256 characters [A-Za-z0-9_-].",
                file=sys.stderr,
            )
            return 1

        webhook_url = build_webhook_url(args.url)
        if args.dry_run:
            print(
                json.dumps(
                    {
                        "url": webhook_url,
                        "allowed_updates": ALLOWED_UPDATES,
                        "drop_pending_updates": args.drop_pending,
                        "max_connections": 40,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        payload = await telegram_request(
            client,
            bot_token,
            "setWebhook",
            {
                "url": webhook_url,
                "secret_token": webhook_secret,
                "allowed_updates": ALLOWED_UPDATES,
                "drop_pending_updates": args.drop_pending,
                "max_connections": 40,
            },
        )
        print(
            json.dumps(
                {
                    "ok": payload.get("ok"),
                    "description": payload.get("description"),
                    "url": webhook_url,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0


def main() -> int:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    args = parse_args()
    try:
        return asyncio.run(run(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"Webhook operation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
