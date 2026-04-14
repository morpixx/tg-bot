from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.core.config import settings
from services.crypto import decrypt

if TYPE_CHECKING:
    from db.models import TelegramSession

log = structlog.get_logger()


class SessionPool:
    """Manages a pool of active Telethon clients."""

    def __init__(self) -> None:
        self._clients: dict[uuid.UUID, TelegramClient] = {}

    async def get_or_connect(self, tg_session: TelegramSession) -> TelegramClient | None:
        """Return existing client or create a new one from stored session."""
        session_id = tg_session.id
        client = self._clients.get(session_id)

        if client and client.is_connected():
            return client

        try:
            plain_session = decrypt(tg_session.encrypted_session)
            client = TelegramClient(
                StringSession(plain_session),
                settings.telethon_api_id,
                settings.telethon_api_hash,
                device_model="iPhone 14 Pro Max",
                system_version="16.0",
                app_version="9.6.3",
                lang_code="ru",
                system_lang_code="ru-RU",
            )
            await client.connect()
            if not await client.is_user_authorized():
                log.warning("Session not authorized", session_id=str(session_id), name=tg_session.name)
                await client.disconnect()
                return None
            self._clients[session_id] = client
            log.info("Session connected", session_id=str(session_id), name=tg_session.name)
            return client
        except Exception as e:
            log.error("Failed to connect session", session_id=str(session_id), error=str(e))
            return None

    async def disconnect(self, session_id: uuid.UUID) -> None:
        client = self._clients.pop(session_id, None)
        if client:
            await client.disconnect()

    async def disconnect_all(self) -> None:
        for client in self._clients.values():
            try:
                await client.disconnect()
            except Exception:
                pass
        self._clients.clear()

    async def health_check(self, tg_session: TelegramSession) -> bool:
        """Ping a session to verify it's still alive."""
        client = await self.get_or_connect(tg_session)
        if not client:
            return False
        try:
            await client.get_me()
            return True
        except Exception:
            self._clients.pop(tg_session.id, None)
            return False
