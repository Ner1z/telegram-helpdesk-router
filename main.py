from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from bot import __version__
from bot.config import ConfigurationError, get_settings
from bot.logging_setup import setup_logging
from bot.runtime import (
    InvalidUpdateError,
    UpdateInProgressError,
    process_telegram_update,
)
from bot.security import constant_time_equal
from bot.storage.base import StorageError

setup_logging()
logger = logging.getLogger(__name__)

SERVICE_NAME = "telegram-helpdesk-router"
WEBHOOK_PATHS = frozenset({"/webhook", "/api/webhook"})
DEFAULT_MAX_WEBHOOK_BODY_BYTES = 1_048_576

app = FastAPI(
    title=SERVICE_NAME,
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    if request.method == "POST" and request.url.path in WEBHOOK_PATHS:
        try:
            max_body_bytes = get_settings().webhook_max_body_bytes
        except (ConfigurationError, ValidationError):
            max_body_bytes = DEFAULT_MAX_WEBHOOK_BODY_BYTES
        content_length_header = request.headers.get("content-length")
        if content_length_header is not None:
            try:
                content_length = int(content_length_header)
            except ValueError:
                return JSONResponse(
                    {"ok": False, "error": "invalid content length"},
                    status_code=400,
                )
            if content_length < 0 or content_length > max_body_bytes:
                return JSONResponse(
                    {"ok": False, "error": "payload too large"},
                    status_code=413,
                )

    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.get("/", include_in_schema=False)
@app.get("/health", include_in_schema=False)
@app.get("/api/health", include_in_schema=False)
async def health_check() -> JSONResponse:
    ready = False
    try:
        ready = get_settings().is_operational
    except (ConfigurationError, ValidationError):
        logger.exception("health_configuration_failed")
    except Exception:
        logger.exception("health_unexpected_failure")

    return JSONResponse(
        {
            "ok": True,
            "service": SERVICE_NAME,
            "version": __version__,
            "ready": ready,
        },
        status_code=200,
    )


@app.post("/webhook", include_in_schema=False)
@app.post("/api/webhook", include_in_schema=False)
async def telegram_webhook(request: Request) -> JSONResponse:
    try:
        settings = get_settings()
        settings.require_operational()
    except (ConfigurationError, ValidationError) as error:
        logger.error("webhook_configuration_invalid", extra={"reason": str(error)})
        return JSONResponse(
            {"ok": False, "error": "service is not configured"},
            status_code=503,
        )
    except Exception:
        logger.exception("webhook_configuration_unexpected_failure")
        return JSONResponse(
            {"ok": False, "error": "service is not configured"},
            status_code=503,
        )

    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != "application/json":
        return JSONResponse(
            {"ok": False, "error": "unsupported media type"},
            status_code=415,
        )

    received_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
    expected_secret = settings.telegram_webhook_secret.get_secret_value()
    if not constant_time_equal(expected_secret, received_secret):
        logger.warning(
            "webhook_rejected_invalid_secret",
            extra={"client_host": request.client.host if request.client else None},
        )
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    try:
        payload: Any = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)

    if not isinstance(payload, dict) or not isinstance(payload.get("update_id"), int):
        return JSONResponse({"ok": False, "error": "invalid update"}, status_code=400)

    update_id = payload["update_id"]
    try:
        await process_telegram_update(settings=settings, payload=payload)
    except InvalidUpdateError:
        logger.warning("webhook_invalid_update", extra={"update_id": update_id})
        return JSONResponse({"ok": False, "error": "invalid update"}, status_code=400)
    except UpdateInProgressError:
        logger.info("webhook_update_in_progress", extra={"update_id": update_id})
        return JSONResponse(
            {"ok": False, "error": "update is being processed"},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    except StorageError:
        logger.exception("webhook_storage_error", extra={"update_id": update_id})
        return JSONResponse(
            {"ok": False, "error": "storage unavailable"},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    except Exception:
        logger.exception("webhook_unhandled_error", extra={"update_id": update_id})
        return JSONResponse({"ok": False, "error": "internal error"}, status_code=500)

    return JSONResponse({"ok": True})
