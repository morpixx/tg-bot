from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from opentele2.api import API
from opentele2.tl import TelegramClient
from telethon.sessions import StringSession

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
                api=API.TelegramIOS.Generate(),
                receive_updates=False,
            )
            await client.connect()
            if not await client.is_user_authorized():
                log.warning("Session not authorized", session_id=str(session_id), name=tg_session.name)
                await client.disconnect()
                return None
            # StringSession doesn't persist entity cache. Without a warm cache,
            # `send_message(chat_id)` fails with "Could not find the input entity
            # for PeerChannel" because Telethon has no access_hash to build an
            # InputPeerChannel. Iterating dialogs populates the in-memory cache
            # for the lifetime of this client.
            try:
                async for _ in client.iter_dialogs(limit=500):
                    pass
            except Exception as e:
                log.warning("Dialog prewarm failed", session_id=str(session_id), error=str(e))
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
