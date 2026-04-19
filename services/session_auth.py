from __future__ import annotations

import asyncio
import io
import random
from dataclasses import dataclass

import qrcode
from opentele2.api import API
from opentele2.tl import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

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


# Rotated in order on RECAPTCHA retries — each generator yields a fresh device
# fingerprint per call, which is often enough to clear Telegram's soft block.
_DEVICE_ROTATION = (
    ("iOS", lambda: API.TelegramIOS.Generate()),
    ("Android", lambda: API.TelegramAndroid.Generate()),
    ("Desktop", lambda: API.TelegramDesktop.Generate()),
)


def _make_client(string_session: str = "", device_factory=None) -> TelegramClient:
    api = device_factory() if device_factory else API.TelegramIOS.Generate()
    return TelegramClient(StringSession(string_session), api=api)


def _is_recaptcha(err: str) -> bool:
    return "RECAPTCHA" in err or "recaptcha" in err.lower()


# ── QR Login ──────────────────────────────────────────────────────────────────

class QRLoginSession:
    """Manages QR login flow. One instance per auth attempt."""

    def __init__(self) -> None:
        self._client = _make_client()
        self._qr_login = None
        self._wait_task: asyncio.Task | None = None
        self._finalized = False  # guard against double-save on refresh race

    async def start(self) -> bytes:
        """Connect client, start QR login, return QR image bytes.

        The wait task is kicked off *before* returning so Telethon's
        UpdateLoginToken handler is registered before the user can scan.
        """
        await self._client.connect()
        self._qr_login = await self._client.qr_login()
        self._wait_task = asyncio.create_task(self._qr_login.wait())
        # Yield once so the task runs up to its first suspension point,
        # which is after add_event_handler — no scan can be missed.
        await asyncio.sleep(0)
        return self._generate_qr_image(self._qr_login.url)

    def login_url(self) -> str:
        """Return the tg://login URL — works as a clickable deeplink."""
        assert self._qr_login is not None
        return self._qr_login.url

    async def wait_for_scan(self, timeout: float = 60.0) -> str:
        """Wait for QR scan. Returns 'success', 'password_needed', or 'expired'."""
        assert self._wait_task is not None
        try:
            await asyncio.wait_for(asyncio.shield(self._wait_task), timeout=timeout)
            return "success"
        except TimeoutError:
            return "expired"
        except SessionPasswordNeededError:
            return "password_needed"

    async def refresh_qr(self) -> bytes:
        """Regenerate QR code after expiry."""
        if self._wait_task and not self._wait_task.done():
            self._wait_task.cancel()
            try:
                await self._wait_task
            except BaseException:
                pass
        # recreate() returns None and mutates self._qr_login._resp in place.
        await self._qr_login.recreate()
        self._wait_task = asyncio.create_task(self._qr_login.wait())
        await asyncio.sleep(0)
        return self._generate_qr_image(self.login_url())

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
        if self._finalized:
            return AuthResult(success=False, error="Already finalized")
        self._finalized = True
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
            try:
                await self._client.disconnect()
            except Exception:
                pass

    async def cancel(self) -> None:
        if self._wait_task and not self._wait_task.done():
            self._wait_task.cancel()
            try:
                await self._wait_task
            except BaseException:
                pass
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

        On RECAPTCHA, rotate through iOS → Android → Desktop device
        fingerprints with randomized backoff. Each opentele2 generator
        yields a fresh device per call, so this hits Telegram's captcha
        heuristics from different angles without falling back to QR.
        """
        self._phone = phone

        async def _attempt() -> tuple[bool, str]:
            try:
                if not self._client.is_connected():
                    await self._client.connect()
                result = await self._client.send_code_request(phone)
                self._phone_code_hash = result.phone_code_hash
                return True, ""
            except FloodWaitError as e:
                return False, f"flood:{e.seconds}"
            except Exception as e:
                return False, str(e)

        ok, err = await _attempt()
        if ok:
            return True, ""

        if err.startswith("flood:"):
            seconds = err.split(":", 1)[1]
            return False, f"Слишком много попыток. Подождите {seconds} сек."

        if _is_recaptcha(err):
            for _device_name, factory in _DEVICE_ROTATION:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(0.8, 2.2))
                self._client = _make_client(device_factory=factory)
                ok_retry, err_retry = await _attempt()
                if ok_retry:
                    return True, ""
                if not _is_recaptcha(err_retry):
                    return False, err_retry
                err = err_retry
            return False, (
                "⚠️ Telegram требует CAPTCHA для этого номера.\n\n"
                "Мы попробовали iOS, Android и Desktop-клиенты — не прошло.\n"
                "Можно: 1) подождать пару минут и повторить, "
                "2) использовать другой номер или 3) войти по <b>QR-коду</b>."
            )

        return False, err

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
