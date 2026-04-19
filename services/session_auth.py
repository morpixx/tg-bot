from __future__ import annotations

import asyncio
import datetime
import io
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import qrcode
import structlog
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

log = structlog.get_logger()

# Auth-state polling interval — safety net in case UpdateLoginToken is missed.
_AUTH_POLL_SECONDS = 2.0
# How long before token expiry to refresh QR — small margin to avoid races.
_REFRESH_MARGIN_SECONDS = 3.0
# Overall cap for a single QR login attempt.
_QR_MAX_TOTAL_SECONDS = 5 * 60


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
    # receive_updates=False is critical: without it, telethon starts an update
    # dispatcher that calls get_me() on an unauthorized client and triggers
    # GetUsersRequest → FloodWaitError(3600s). We only need request/response.
    return TelegramClient(StringSession(string_session), api=api, receive_updates=False)


def _is_recaptcha(err: str) -> bool:
    return "RECAPTCHA" in err or "recaptcha" in err.lower()


# ── QR Login ──────────────────────────────────────────────────────────────────

# Outcome strings produced by the internal loop and surfaced via wait_done().
_OUTCOME_SUCCESS = "success"
_OUTCOME_PASSWORD_NEEDED = "password_needed"
_OUTCOME_TIMEOUT = "timeout"
_OUTCOME_ERROR = "error"
_OUTCOME_CANCELLED = "cancelled"

RefreshCallback = Callable[[bytes, str], Awaitable[None]]


class QRLoginSession:
    """Self-driving QR login with auto-refresh + auth-state polling safety net.

    Lifecycle:
      auth = QRLoginSession()
      img = await auth.start(on_refresh)          # 1st QR
      outcome = await auth.wait_done()            # "success" / "password_needed" / ...
      if outcome == "password_needed":
          result = await auth.submit_password(pwd)
      else:
          result = await auth.finalize()

    The background loop keeps the QR fresh: every time Telegram's 30s token
    nears expiry, we `recreate()` it and notify the UI via on_refresh. That
    way the user never sees an expired QR.

    As a belt-and-suspenders check we also poll `is_user_authorized()` on
    each wait cycle — if telethon's UpdateLoginToken handler misses an update
    for any reason, we still detect the successful login.
    """

    def __init__(self) -> None:
        self._client = _make_client()
        self._qr_login = None
        self._loop_task: asyncio.Task | None = None
        self._done_event = asyncio.Event()
        self._on_refresh: RefreshCallback | None = None
        self._outcome: str | None = None
        self._error: str | None = None
        self._finalized = False

    # ── Public API ────────────────────────────────────────────────────────

    async def start(self, on_refresh: RefreshCallback) -> bytes:
        """Connect, request first token, launch the background auth loop."""
        self._on_refresh = on_refresh
        await self._client.connect()
        self._qr_login = await self._client.qr_login()
        self._loop_task = asyncio.create_task(self._run_loop())
        # Yield so the loop reaches its first await (handler registered inside
        # qr_login.wait()) before we return and the user sees the QR.
        await asyncio.sleep(0)
        return self._generate_qr_image(self._qr_login.url)

    def login_url(self) -> str:
        """Return the tg://login URL — works as a clickable deeplink."""
        assert self._qr_login is not None
        return self._qr_login.url

    async def wait_done(self) -> str:
        """Block until the loop finishes. Returns the outcome string."""
        await self._done_event.wait()
        return self._outcome or _OUTCOME_ERROR

    @property
    def error(self) -> str | None:
        return self._error

    async def submit_password(self, password: str) -> AuthResult:
        """Submit 2FA password after a `password_needed` outcome."""
        try:
            await self._client.sign_in(password=password)
        except Exception as e:
            return AuthResult(success=False, error=str(e))
        return await self._finalize()

    async def finalize(self) -> AuthResult:
        """Pull user data and encrypt the StringSession for DB storage."""
        return await self._finalize()

    async def cancel(self) -> None:
        """Abort the loop and disconnect the client."""
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except BaseException:
                pass
        try:
            await self._client.disconnect()
        except Exception:
            pass

    # ── Loop ──────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Wait on the token, auto-refresh on expiry, poll auth as safety net."""
        deadline = asyncio.get_event_loop().time() + _QR_MAX_TOTAL_SECONDS
        try:
            while not self._done_event.is_set():
                now = asyncio.get_event_loop().time()
                if now >= deadline:
                    self._finish(_OUTCOME_TIMEOUT)
                    return

                token_window = self._seconds_until_expiry() - _REFRESH_MARGIN_SECONDS
                wait_slice = min(max(token_window, _AUTH_POLL_SECONDS), deadline - now)

                try:
                    # qr_login.wait() registers its own UpdateLoginToken handler
                    # and resolves via that OR via token-expiry TimeoutError.
                    await asyncio.wait_for(
                        self._qr_login.wait(wait_slice + 1.0),
                        timeout=wait_slice,
                    )
                    # Primary path: handler fired, token imported, user authed.
                    self._finish(_OUTCOME_SUCCESS)
                    return
                except SessionPasswordNeededError:
                    self._finish(_OUTCOME_PASSWORD_NEEDED)
                    return
                except asyncio.CancelledError:
                    self._finish(_OUTCOME_CANCELLED)
                    return
                except TimeoutError:
                    # Fallback: maybe the update fired but our handler missed it.
                    if await self._safely_is_authorized():
                        self._finish(_OUTCOME_SUCCESS)
                        return
                    # Genuine token expiry — recreate and keep looping.
                    try:
                        await self._qr_login.recreate()
                    except Exception as e:
                        log.exception("qr recreate failed")
                        self._error = str(e)
                        self._finish(_OUTCOME_ERROR)
                        return
                    await self._notify_refresh()
                except Exception as e:
                    log.exception("qr loop unexpected error")
                    self._error = str(e)
                    self._finish(_OUTCOME_ERROR)
                    return
        except asyncio.CancelledError:
            self._finish(_OUTCOME_CANCELLED)

    async def _safely_is_authorized(self) -> bool:
        try:
            return bool(await self._client.is_user_authorized())
        except Exception:
            return False

    def _seconds_until_expiry(self) -> float:
        if not self._qr_login:
            return 0.0
        now = datetime.datetime.now(tz=datetime.UTC)
        return max(0.0, (self._qr_login.expires - now).total_seconds())

    async def _notify_refresh(self) -> None:
        if not self._on_refresh:
            return
        try:
            img = self._generate_qr_image(self._qr_login.url)
            await self._on_refresh(img, self._qr_login.url)
        except Exception:
            log.exception("on_refresh callback failed")

    def _finish(self, outcome: str) -> None:
        if not self._done_event.is_set():
            self._outcome = outcome
            self._done_event.set()

    # ── Finalization ──────────────────────────────────────────────────────

    async def _finalize(self) -> AuthResult:
        if self._finalized:
            return AuthResult(success=False, error="Already finalized")
        self._finalized = True
        try:
            me = await self._client.get_me()
            if me is None:
                return AuthResult(success=False, error="Not authorized")
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
            log.exception("qr finalize failed")
            return AuthResult(success=False, error=str(e))
        finally:
            try:
                await self._client.disconnect()
            except Exception:
                pass

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
