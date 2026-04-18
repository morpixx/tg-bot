from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TelegramSession


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, session_id: uuid.UUID) -> TelegramSession | None:
        return await self._session.get(TelegramSession, session_id)

    async def get_by_user(self, user_id: int) -> list[TelegramSession]:
        """Return only active sessions (used by worker / chat resolution)."""
        result = await self._session.execute(
            select(TelegramSession)
            .where(TelegramSession.user_id == user_id, TelegramSession.is_active == True)  # noqa: E712
            .order_by(TelegramSession.created_at)
        )
        return list(result.scalars().all())

    async def get_all_by_user(self, user_id: int) -> list[TelegramSession]:
        """Return all sessions regardless of is_active (used for UI listing)."""
        result = await self._session.execute(
            select(TelegramSession)
            .where(TelegramSession.user_id == user_id)
            .order_by(TelegramSession.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        name: str,
        encrypted_session: str,
        phone: str | None = None,
        has_premium: bool = False,
        account_name: str | None = None,
        account_username: str | None = None,
    ) -> TelegramSession:
        tg_session = TelegramSession(
            user_id=user_id,
            name=name,
            encrypted_session=encrypted_session,
            phone=phone,
            has_premium=has_premium,
            account_name=account_name,
            account_username=account_username,
        )
        self._session.add(tg_session)
        await self._session.flush()
        return tg_session

    async def update(self, session_id: uuid.UUID, **kwargs: object) -> None:
        tg_session = await self.get(session_id)
        if tg_session:
            for key, val in kwargs.items():
                setattr(tg_session, key, val)
            await self._session.flush()

    async def delete(self, session_id: uuid.UUID) -> None:
        tg_session = await self.get(session_id)
        if tg_session:
            await self._session.delete(tg_session)
            await self._session.flush()

    async def get_all_active(self) -> list[TelegramSession]:
        """All active sessions across all users (for worker health checks)."""
        result = await self._session.execute(
            select(TelegramSession).where(TelegramSession.is_active == True)  # noqa: E712
        )
        return list(result.scalars().all())
