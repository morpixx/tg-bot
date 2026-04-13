from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import qrcode
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from bot.core.config import settings
from services.crypto import encrypt


@dataclass
class AuthResult:
    success: bool
    encrypted_session: str = ""
    phone: str | None = None
    has_premium: bool = False
    account_name: str | None = None
    account_username: str | None = None
    error: str | None = None


def _make_client(string_session: str = "") -> TelegramClient:
    return TelegramClient(
        StringSession(string_session),
        settings.telethon_api_id,
        settings.telethon_api_hash,
    )


# ── QR Login ──────────────────────────────────────────────────────────────────

class QRLoginSession:
    """Manages QR login flow. One instance per auth attempt."""

    def __init__(self) -> None:
        self._client = _make_client()
        self._qr_login = None
        self._done = asyncio.Event()
        self._result: AuthResult | None = None
        self._password_needed = asyncio.Event()

    async def start(self) -> bytes:
        """Connect client, start QR login, return QR image bytes."""
        await self._client.connect()
        self._qr_login = await self._client.qr_login()
        return self._generate_qr_image(self._qr_login.url)

    async def wait_for_scan(self, timeout: float = 30.0) -> str | None:
        """
        Wait for QR scan. Returns 'success', 'password_needed', or 'expired'.
        """
        try:
            await asyncio.wait_for(self._qr_login.wait(), timeout=timeout)
            return "success"
        except SessionPasswordNeededError:
            return "password_needed"
        except asyncio.TimeoutError:
            return "expired"

    async def refresh_qr(self) -> bytes:
        """Regenerate QR code after expiry."""
        self._qr_login = await self._qr_login.recreate()
        return self._generate_qr_image(self._qr_login.url)

    async def submit_password(self, password: str) -> AuthResult:
        """Submit 2FA password after QR scan."""
        try:
            await self._client.sign_in(password=password)
        except Exception as e:
            return AuthResult(success=False, error=str(e))
        return await self._finalize()

    async def finalize(self) -> AuthResult:
        return await self._finalize()

    async def _finalize(self) -> AuthResult:
        try:
            me = await self._client.get_me()
            string_session = self._client.session.save()
            return AuthResult(
                success=True,
                encrypted_session=encrypt(string_session),
                phone=me.phone,
                has_premium=getattr(me, "premium", False),
                account_name=f"{me.first_name or ''} {me.last_name or ''}".strip() or None,
                account_username=me.username,
            )
        except Exception as e:
            return AuthResult(success=False, error=str(e))
        finally:
            await self._client.disconnect()

    async def cancel(self) -> None:
        await self._client.disconnect()

    @staticmethod
    def _generate_qr_image(url: str) -> bytes:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


# ── Phone Login ───────────────────────────────────────────────────────────────

class PhoneLoginSession:
    """Manages phone number login flow."""

    def __init__(self) -> None:
        self._client = _make_client()
        self._phone_code_hash: str | None = None
        self._phone: str | None = None

    async def send_code(self, phone: str) -> tuple[bool, str]:
        """
        Send verification code to phone.
        Returns (success, error_message).
        """
        self._phone = phone
        try:
            await self._client.connect()
            result = await self._client.send_code_request(phone)
            self._phone_code_hash = result.phone_code_hash
            return True, ""
        except FloodWaitError as e:
            return False, f"Слишком много попыток. Подождите {e.seconds} сек."
        except Exception as e:
            return False, str(e)

    async def submit_code(self, code: str) -> tuple[str, str]:
        """
        Submit the received code.
        Returns ('success' | 'password_needed' | 'error', message).
        """
        try:
            await self._client.sign_in(
                phone=self._phone,
                code=code,
                phone_code_hash=self._phone_code_hash,
            )
            return "success", ""
        except SessionPasswordNeededError:
            return "password_needed", ""
        except PhoneCodeInvalidError:
            return "error", "Неверный код. Попробуйте ещё раз."
        except PhoneCodeExpiredError:
            return "error", "Код истёк. Запросите новый."
        except Exception as e:
            return "error", str(e)

    async def submit_password(self, password: str) -> tuple[bool, str]:
        """Submit 2FA password. Returns (success, error_message)."""
        try:
            await self._client.sign_in(password=password)
            return True, ""
        except Exception as e:
            return False, str(e)

    async def finalize(self) -> AuthResult:
        try:
            me = await self._client.get_me()
            string_session = self._client.session.save()
            return AuthResult(
                success=True,
                encrypted_session=encrypt(string_session),
                phone=self._phone,
                has_premium=getattr(me, "premium", False),
                account_name=f"{me.first_name or ''} {me.last_name or ''}".strip() or None,
                account_username=me.username,
            )
        except Exception as e:
            return AuthResult(success=False, error=str(e))
        finally:
            await self._client.disconnect()

    async def cancel(self) -> None:
        await self._client.disconnect()
