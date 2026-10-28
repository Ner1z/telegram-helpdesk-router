from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the deployed helpdesk webhook.")
    parser.add_argument(
        "--url",
        default=os.getenv("PUBLIC_BASE_URL", ""),
        help="Public HTTPS base URL, for example https://project.vercel.app",
    )
    return parser.parse_args()


async def run(base_url: str) -> int:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("--url or PUBLIC_BASE_URL is required")

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        health_response = await client.get(f"{normalized}/health")
        print(f"GET /health -> HTTP {health_response.status_code}")
        print(json.dumps(health_response.json(), ensure_ascii=False, indent=2))

        rejected = await client.post(
            f"{normalized}/webhook",
            headers={"Content-Type": "application/json"},
            json={"update_id": 1, "message": {}},
        )
        print(f"POST /webhook without secret -> HTTP {rejected.status_code}")
        if rejected.status_code not in {403, 503}:
            print("Expected 403 (bad secret) or 503 (service not configured).")
            return 1
    return 0


def main() -> int:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    args = parse_args()
    try:
        return asyncio.run(run(args.url))
    except (ValueError, httpx.HTTPError) as error:
        print(f"Smoke test failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
