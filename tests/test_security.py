from __future__ import annotations

import html

from bot.security import (
    constant_time_equal,
    derive_ticket_id,
    escape_html,
    extract_ticket_id_from_text,
    generate_reply_token,
    hash_reply_token,
    normalize_ticket_id,
)


def test_reply_token_is_high_entropy_and_never_reused() -> None:
    first_token = generate_reply_token()
    second_token = generate_reply_token()
    assert first_token != second_token
    assert len(first_token) >= 40


def test_ticket_id_is_derived_from_the_token_hash() -> None:
    token = generate_reply_token()
    token_hash = hash_reply_token(token)
    ticket_id = derive_ticket_id(token_hash)
    assert len(token_hash) == 64
    assert len(ticket_id) == 16
    assert ticket_id == token_hash[:16].upper()


def test_ticket_id_normalization_accepts_human_formats() -> None:
    ticket_id = "0123456789ABCDEF"
    assert normalize_ticket_id(ticket_id) == ticket_id
    assert normalize_ticket_id(f"#TKT-{ticket_id}") == ticket_id
    assert normalize_ticket_id(f"tkt-{ticket_id.lower()}") == ticket_id
    assert normalize_ticket_id("not-a-ticket") is None


def test_ticket_id_is_extracted_from_replied_message_text() -> None:
    text = "Ticket #TKT-0123456789ABCDEF\nsome text"
    assert extract_ticket_id_from_text(text) == "0123456789ABCDEF"
    assert extract_ticket_id_from_text("no ticket here") is None
    assert extract_ticket_id_from_text(None) is None


def test_content_is_html_escaped() -> None:
    assert escape_html("<script>alert('x')</script>") == (
        "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )
    assert html.unescape(escape_html("a < b & c > d")) == "a < b & c > d"


def test_constant_time_secret_comparison() -> None:
    assert constant_time_equal("secret", "secret") is True
    assert constant_time_equal("secret", "secreT") is False
    assert constant_time_equal("", "") is False
    assert constant_time_equal("secret", "") is False
    assert constant_time_equal("secret", "sécret") is False
