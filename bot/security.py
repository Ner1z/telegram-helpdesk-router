from __future__ import annotations

import hashlib
import hmac
import html
import re
import secrets

TICKET_ID_PATTERN = re.compile(r"^[A-F0-9]{16}$")
TICKET_ID_IN_TEXT_PATTERN = re.compile(r"#?\bTKT[- ]?([A-Fa-f0-9]{16})\b")


def generate_reply_token() -> str:
    """Return a 256-bit URL-safe capability token. The token is never persisted."""
    return secrets.token_urlsafe(32)


def hash_reply_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def derive_ticket_id(token_hash: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", token_hash):
        raise ValueError("token_hash must be a lowercase SHA-256 hex digest")
    return token_hash[:16].upper()


def normalize_ticket_id(raw_value: str) -> str | None:
    value = raw_value.strip().lstrip("#").strip()
    if value.upper().startswith("TKT-"):
        value = value[4:]
    elif value.upper().startswith("TKT"):
        value = value[3:].lstrip("- ")
    value = value.upper()
    if not TICKET_ID_PATTERN.fullmatch(value):
        return None
    return value


def extract_ticket_id_from_text(text: str | None) -> str | None:
    if not text:
        return None
    match = TICKET_ID_IN_TEXT_PATTERN.search(text)
    if match is None:
        return None
    return match.group(1).upper()


def constant_time_equal(expected: str, received: str) -> bool:
    if not expected or not received:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), received.encode("utf-8"))


def escape_html(value: str) -> str:
    return html.escape(value, quote=True)
