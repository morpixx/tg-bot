from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from opentele2.api import API
from opentele2.tl import TelegramClient
from telethon.sessions import StringSession

from db.models import TelegramSession
from services.crypto import decrypt

log = structlog.get_logger()


@asynccontextmanager
async def borrow_client(tg_session: TelegramSession) -> AsyncIterator[TelegramClient | None]:
    """Connect a one-shot Telethon client for the bot process.

    The worker uses a long-lived SessionPool; the bot needs short-lived clients
    for things like resolving a chat or sending a test message. Yields None if
    the session is unauthorized — caller should check before using.
    """
    plain = decrypt(tg_session.encrypted_session)
    client = TelegramClient(
        StringSession(plain),
        api=API.TelegramIOS.Generate(),
        receive_updates=False,
    )
    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.warning("Borrowed session not authorized", session_id=str(tg_session.id))
            yield None
            return
        yield client
    finally:
        try:
            await client.disconnect()
        except Exception as e:
            log.warning("Error disconnecting borrowed client", error=str(e))
