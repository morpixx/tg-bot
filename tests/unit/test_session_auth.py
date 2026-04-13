from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.session_auth import AuthResult, PhoneLoginSession, QRLoginSession


# ── QR image generation ───────────────────────────────────────────────────────

class TestQRImage:
    def test_generate_returns_png_bytes(self) -> None:
        png = QRLoginSession._generate_qr_image("tg://login?token=ABC123")
        assert isinstance(png, bytes)
        assert png[:4] == b"\x89PNG"  # PNG magic bytes

    def test_generate_non_empty(self) -> None:
        png = QRLoginSession._generate_qr_image("tg://login?token=XYZ")
        assert len(png) > 1000  # reasonable size for a QR PNG


# ── AuthResult ────────────────────────────────────────────────────────────────

class TestAuthResult:
    def test_success_defaults(self) -> None:
        r = AuthResult(success=True, encrypted_session="ENC", phone="+79001234567")
        assert r.has_premium is False
        assert r.account_name is None
        assert r.error is None

    def test_failure(self) -> None:
        r = AuthResult(success=False, error="Bad code")
        assert r.success is False
        assert r.error == "Bad code"
        assert r.encrypted_session == ""


# ── PhoneLoginSession ─────────────────────────────────────────────────────────

class TestPhoneLoginSession:
    @pytest.fixture
    def phone_session(self) -> PhoneLoginSession:
        with patch("services.session_auth._make_client") as mock_make:
            mock_client = AsyncMock()
            mock_make.return_value = mock_client
            session = PhoneLoginSession()
            session._client = mock_client
            return session

    async def test_send_code_success(self, phone_session) -> None:
        result = MagicMock()
        result.phone_code_hash = "HASH123"
        phone_session._client.connect = AsyncMock()
        phone_session._client.send_code_request = AsyncMock(return_value=result)

        ok, err = await phone_session.send_code("+79001234567")
        assert ok is True
        assert err == ""
        assert phone_session._phone_code_hash == "HASH123"

    async def test_send_code_flood_wait(self, phone_session) -> None:
        from telethon.errors import FloodWaitError
        exc = FloodWaitError(request=MagicMock())
        exc.seconds = 60
        phone_session._client.connect = AsyncMock()
        phone_session._client.send_code_request = AsyncMock(side_effect=exc)

        ok, err = await phone_session.send_code("+79001234567")
        assert ok is False
        assert "60" in err

    async def test_submit_code_invalid(self, phone_session) -> None:
        from telethon.errors import PhoneCodeInvalidError
        phone_session._client.sign_in = AsyncMock(side_effect=PhoneCodeInvalidError(request=MagicMock()))
        result, msg = await phone_session.submit_code("00000")
        assert result == "error"
        assert "Неверный" in msg

    async def test_submit_code_expired(self, phone_session) -> None:
        from telethon.errors import PhoneCodeExpiredError
        phone_session._client.sign_in = AsyncMock(side_effect=PhoneCodeExpiredError(request=MagicMock()))
        result, msg = await phone_session.submit_code("12345")
        assert result == "error"
        assert "истёк" in msg

    async def test_submit_code_password_needed(self, phone_session) -> None:
        from telethon.errors import SessionPasswordNeededError
        phone_session._client.sign_in = AsyncMock(side_effect=SessionPasswordNeededError(request=MagicMock()))
        result, msg = await phone_session.submit_code("12345")
        assert result == "password_needed"
        assert msg == ""

    async def test_submit_code_success(self, phone_session) -> None:
        phone_session._client.sign_in = AsyncMock()
        result, msg = await phone_session.submit_code("12345")
        assert result == "success"
        assert msg == ""

    async def test_finalize_extracts_user_info(self, phone_session) -> None:
        me = MagicMock()
        me.phone = "+79001234567"
        me.first_name = "Ivan"
        me.last_name = "Petrov"
        me.username = "ivanpetrov"
        me.premium = True

        phone_session._client.get_me = AsyncMock(return_value=me)
        phone_session._client.session.save = MagicMock(return_value="SESSION_STRING")
        phone_session._client.disconnect = AsyncMock()

        with patch("services.session_auth.encrypt", return_value="ENC_SESSION"):
            result = await phone_session.finalize()

        assert result.success is True
        assert result.has_premium is True
        assert result.account_name == "Ivan Petrov"
        assert result.account_username == "ivanpetrov"
        assert result.encrypted_session == "ENC_SESSION"

    async def test_submit_password_wrong(self, phone_session) -> None:
        phone_session._client.sign_in = AsyncMock(side_effect=Exception("wrong password"))
        ok, err = await phone_session.submit_password("wrong")
        assert ok is False
        assert "wrong password" in err

    async def test_submit_password_correct(self, phone_session) -> None:
        phone_session._client.sign_in = AsyncMock()
        ok, err = await phone_session.submit_password("correct")
        assert ok is True
        assert err == ""
