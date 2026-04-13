from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tg_id: int) -> User | None:
        return await self._session.get(User, tg_id)

    async def get_or_create(self, tg_id: int, username: str | None = None, full_name: str | None = None) -> tuple[User, bool]:
        user = await self.get(tg_id)
        if user:
            return user, False
        user = User(tg_id=tg_id, username=username, full_name=full_name)
        self._session.add(user)
        await self._session.flush()
        return user, True

    async def update(self, tg_id: int, **kwargs: object) -> None:
        user = await self.get(tg_id)
        if user:
            for key, val in kwargs.items():
                setattr(user, key, val)
            await self._session.flush()

    async def list_active(self) -> list[User]:
        result = await self._session.execute(select(User).where(User.is_active == True))  # noqa: E712
        return list(result.scalars().all())
