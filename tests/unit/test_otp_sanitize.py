"""Tests for OTP digit-sanitization.

Telegram invalidates login codes typed directly inside any Telegram chat
(anti-phishing). Users are instructed to insert separators; the handler
strips everything but digits before submitting to Telethon.
"""
from __future__ import annotations

import pytest

from bot.handlers.sessions import _sanitize_otp


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12345", "12345"),
        ("1-2-3-4-5", "12345"),
        ("1a2b3c4d5", "12345"),
        ("1 2 3 4 5", "12345"),
        (" 12345 ", "12345"),
        ("code: 12345!", "12345"),
        ("один-два-3-4-5", "345"),
        ("", ""),
        ("abc", ""),
    ],
)
def test_sanitize_otp(raw: str, expected: str) -> None:
    assert _sanitize_otp(raw) == expected
